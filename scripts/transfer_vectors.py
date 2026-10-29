"""Copia explícita da base local para Qdrant remoto, sem gateway ou embeddings."""

import argparse
import asyncio
from contextlib import AsyncExitStack
import json
import math
from pathlib import Path
from typing import TypedDict

from qdrant_client import AsyncQdrantClient, models
from qdrant_client.http.exceptions import UnexpectedResponse, ResponseHandlingException
from pydantic import ValidationError

from app.config import VectorSettings, load_vector_settings, invalid_variable_names
from app.vector_store import (
    BaseUnavailable, check_ready, collection_contract, create_vector_client,
    validate_collection, validate_vector,
)

BATCH_SIZE = 32
READINESS_FIELDS = ("document_name", "document_hash", "pipeline_version", "embedding_model")


def failure_details(error: Exception) -> dict[str, object]:
    """Publica apenas categorias e campos conhecidos, nunca a mensagem do SDK."""
    if isinstance(error, ValidationError):
        return {"reason": "invalid_configuration",
                "variables": invalid_variable_names(error, "vector")}
    if isinstance(error, UnexpectedResponse):
        details: dict[str, object] = {"reason": "remote_http_error", "http_status": error.status_code}
        # Classifica o corpo sem publicá-lo: respostas podem ecoar dados privados.
        body = error.content.decode("utf-8", errors="replace").lower()
        if any(term in body for term in ("api key", "api-key", "jwt", "unauthorized")):
            details["hint"] = "authentication_response"
        elif "https" in body and any(term in body for term in ("http request", "plain http")):
            details["hint"] = "http_https_mismatch"
        elif "grpc" in body:
            details["hint"] = "possible_grpc_endpoint"
        elif "index" in body and any(term in body for term in ("required", "not indexed", "non-indexed", "unindexed")):
            details["hint"] = "missing_payload_index"
            details["fields"] = [field for field in (
                "document_name", "document_hash", "pipeline_version", "embedding_model",
            ) if field in body]
        elif "<html" in body or "<!doctype html" in body:
            details["hint"] = "html_response_check_endpoint_or_proxy"
        return details
    if isinstance(error, ResponseHandlingException):
        return {"reason": "remote_transport_or_response_error"}
    safe_codes = {
        "remote_https_required", "local_base_missing", "collection_missing",
        "collection_manifest_invalid", "collection_vectors_incompatible",
        "collection_version_incompatible", "collection_incomplete",
        "collection_document_incomplete", "chunk_payload_invalid", "vector_invalid",
        "transfer_vector_invalid", "transfer_payload_invalid", "transfer_dimension_mismatch",
        "transfer_source_changed", "transfer_manifest_mismatch", "transfer_creation_failed",
        "transfer_readback_mismatch", "payload_index_incompatible", "payload_index_creation_failed",
    }
    if isinstance(error, ValueError) and str(error) in safe_codes:
        return {"reason": str(error)}
    return {"reason": "unclassified_error"}


class TransferReport(TypedDict):
    status: str
    points: int
    written: int
    reused: int
    model_calls: int


async def prepare_payload_indexes(client: AsyncQdrantClient, settings: VectorSettings) -> dict[str, object]:
    """Cria só índices ausentes; não altera pontos, vetores ou índices existentes."""
    await validate_collection(client, settings)
    schema = (await client.get_collection(settings.collection)).payload_schema
    # Conferir todos os tipos antes da primeira escrita evita reparos parciais por incompatibilidade.
    if any(field in schema and schema[field].data_type != models.PayloadSchemaType.KEYWORD
           for field in READINESS_FIELDS):
        raise BaseUnavailable("payload_index_incompatible")
    missing = [field for field in READINESS_FIELDS if field not in schema]
    for field in missing:
        # Await espera a criação do índice antes da próxima operação; não gera embeddings.
        result = await client.create_payload_index(
            settings.collection, field_name=field, field_schema=models.PayloadSchemaType.KEYWORD,
            wait=True,
        )
        if result.status != models.UpdateStatus.COMPLETED:
            raise BaseUnavailable("payload_index_creation_failed")
    return {"status": "indexes_prepared", "created": missing,
            "reused": [field for field in READINESS_FIELDS if field in schema], "model_calls": 0}


async def execute_prepare_indexes() -> dict[str, object]:
    settings = load_vector_settings()
    if not settings.url or not settings.url.startswith("https://"):
        raise ValueError("remote_https_required")
    client = create_vector_client(settings)
    try:
        return await prepare_payload_indexes(client, settings)
    finally:
        await client.close()


async def read_points(client: AsyncQdrantClient, settings: VectorSettings) -> list[models.Record]:
    points: list[models.Record] = []
    offset = None
    while True:
        batch, offset = await client.scroll(
            settings.collection, limit=BATCH_SIZE, offset=offset,
            with_payload=True, with_vectors=True,
        )
        for point in batch:
            if not isinstance(point.vector, list):
                raise BaseUnavailable("transfer_vector_invalid")
            validate_vector(point.vector, settings.dimension)
            if (point.payload or {}).get("chunk_id") != str(point.id):
                raise BaseUnavailable("transfer_payload_invalid")
        points.extend(batch)
        if offset is None:
            return points


def same_points(source: list[models.Record], target: list[models.Record]) -> bool:
    observed = {str(point.id): point for point in target}
    if len(source) != len(target) or len(observed) != len(target):
        return False
    for point in source:
        other = observed.get(str(point.id))
        if other is None or other.payload != point.payload:
            return False
        # O servidor pode normalizar novamente vetores de cosseno em float32.
        if not isinstance(point.vector, list) or not isinstance(other.vector, list):
            return False
        if len(point.vector) != len(other.vector) or any(
            not math.isclose(a, b, rel_tol=1e-5, abs_tol=1e-7)
            for a, b in zip(point.vector, other.vector, strict=True)
        ):
            return False
    return True


async def transfer_vectors(
    source: AsyncQdrantClient, local: VectorSettings,
    target: AsyncQdrantClient, remote: VectorSettings, *, verify_only: bool = False,
) -> TransferReport:
    if local.dimension != remote.dimension:
        raise BaseUnavailable("transfer_dimension_mismatch")
    await check_ready(source, local)
    manifest = await validate_collection(source, local)
    points = await read_points(source, local)
    if len(points) != sum(int(doc["chunks"]) for doc in manifest):
        raise BaseUnavailable("transfer_source_changed")
    exists = await target.collection_exists(remote.collection)
    if exists:
        # Uma base parcial ou diferente é preservada e exige decisão manual.
        # Mesmo uma coleção vazia existente não é sobrescrita por este comando.
        await check_ready(target, remote)
        if await validate_collection(target, remote) != manifest:
            raise BaseUnavailable("transfer_manifest_mismatch")
    elif verify_only:
        raise BaseUnavailable("collection_missing")
    else:
        # Criação direta falha em colisão, inclusive se outro operador criou a
        # coleção após a checagem. Nunca reutilizar silenciosamente nesse caso.
        created = await target.create_collection(
            remote.collection,
            vectors_config=models.VectorParams(size=remote.dimension, distance=models.Distance.COSINE),
            metadata={"rag_contract": collection_contract(remote), "documents": manifest},
        )
        if not created:
            raise BaseUnavailable("transfer_creation_failed")
        # Cloud bloqueia contagens filtradas sem esses índices. Preparar antes dos pontos.
        await prepare_payload_indexes(target, remote)
        for start in range(0, len(points), BATCH_SIZE):
            await target.upsert(remote.collection, wait=True, points=[
                models.PointStruct(id=p.id, vector=p.vector, payload=p.payload)
                for p in points[start:start + BATCH_SIZE]
            ])
    await check_ready(target, remote)
    if not same_points(points, await read_points(target, remote)):
        raise BaseUnavailable("transfer_readback_mismatch")
    return TransferReport(status="verified", points=len(points), written=0 if exists else len(points),
                          reused=len(points) if exists else 0, model_calls=0)


async def execute(source_path: Path, verify_only: bool) -> TransferReport:
    remote = load_vector_settings()
    if not remote.url or not remote.url.startswith("https://"):
        raise ValueError("remote_https_required")
    if not (source_path / "meta.json").is_file():
        raise ValueError("local_base_missing")
    local = VectorSettings(path=source_path, collection=remote.collection, dimension=remote.dimension)
    async with AsyncExitStack() as resources:
        source = create_vector_client(local)
        resources.push_async_callback(source.close)
        target = create_vector_client(remote)
        resources.push_async_callback(target.close)
        return await transfer_vectors(source, local, target, remote, verify_only=verify_only)


async def diagnose_connection(*, check_readiness: bool = False) -> dict[str, object]:
    """Até 2 leituras, ou 9 com prontidão; não abre base local nem grava."""
    remote = load_vector_settings()
    if not remote.url or not remote.url.startswith("https://"):
        raise ValueError("remote_https_required")
    target = create_vector_client(remote)
    checks: list[dict[str, object]] = []
    try:
        # Await aguarda cada leitura antes da próxima, sem repetir chamadas com erro.
        operations = ["list_collections", "collection_exists"]
        if check_readiness:
            operations.append("check_ready")
        for operation in operations:
            try:
                if operation == "list_collections":
                    await target.get_collections()
                    result: dict[str, object] = {"status": "ok"}
                elif operation == "collection_exists":
                    result = {"status": "ok", "exists": await target.collection_exists(remote.collection)}
                else:
                    await check_ready(target, remote)
                    result = {"status": "ok"}
            except Exception as error:
                result = {"status": "failed", **failure_details(error)}
            checks.append({"operation": operation, **result})
    finally:
        # Fecha a conexão também quando uma sondagem falha.
        await target.close()
    return {"status": "diagnosed", "checks": checks, "model_calls": 0}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--verify-only", action="store_true", help="Apenas leitura; exige coleção remota existente.")
    parser.add_argument("--source-path", type=Path, default=Path("data/qdrant"))
    parser.add_argument("--diagnose-connection", action="store_true",
                        help="Até dois GETs remotos, sem escrita, base local ou modelos; exige --execute.")
    parser.add_argument("--diagnose-ready", action="store_true",
                        help="Inclui a verificação de /ready: até nove leituras remotas, sem escrita ou modelos; exige --execute.")
    parser.add_argument("--prepare-payload-indexes", action="store_true",
                        help="Cria até quatro índices keyword ausentes na coleção remota existente; exige --execute e chave de escrita.")
    args = parser.parse_args(argv)
    if args.prepare_payload_indexes and (args.verify_only or args.diagnose_connection or args.diagnose_ready):
        parser.error("--prepare-payload-indexes deve ser usado separadamente dos modos de leitura.")
    if not args.execute:
        if args.prepare_payload_indexes:
            print("Plano: validar coleção remota existente e criar até quatro índices keyword ausentes; "
                  "sem alterar pontos/vetores, abrir base local ou chamar modelos. Exige chave de escrita.")
            return 0
        if args.diagnose_ready:
            print("Plano: até nove leituras remotas incluindo prontidão; sem escrita, base local ou modelos.")
            return 0
        if args.diagnose_connection:
            print("Plano: até dois GETs remotos para listar/verificar coleções; sem escrita, base local ou modelos.")
            return 0
        print("Plano: conferir base local e remota; copiar somente se a coleção remota não existir; "
              "verificar IDs, vetores, payloads, metadados e contagens. Zero chamadas de modelos. "
              "Pare processos que usem a base local e confirme o plano Free do cluster no painel.")
        return 0
    try:
        if args.prepare_payload_indexes:
            print(json.dumps(asyncio.run(execute_prepare_indexes())))
            return 0
        if args.diagnose_connection or args.diagnose_ready:
            report = asyncio.run(diagnose_connection(check_readiness=args.diagnose_ready))
            print(json.dumps(report))
            return 0 if all(check["status"] == "ok" for check in report["checks"]) else 1
        print(json.dumps(asyncio.run(execute(args.source_path, args.verify_only))))
        return 0
    except Exception as error:
        # Não imprimir exceções do SDK: podem conter URL, payload ou chave.
        print(json.dumps({"status": "failed", "code": "transfer_not_verified", "model_calls": 0,
                          **failure_details(error),
                          "action": "Conferir configuração, lock local e compatibilidade. "
                                    "Coleções existentes foram preservadas; uma nova coleção pode estar parcial."}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
