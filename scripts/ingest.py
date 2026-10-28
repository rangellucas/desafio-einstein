"""Execute da raiz: python -m scripts.ingest --dry-run."""

import argparse
import asyncio
import json
import logging
import math
from pathlib import Path

from pypdf.errors import PyPdfError
from pydantic import ValidationError

from app.config import (
    CHUNK_OVERLAP,
    CHUNK_SIZE,
    EXPECTED_DOCUMENTS,
    RAW_PDF_DIR,
    SHORT_PAGE_CHARS,
    EMBEDDING_BATCH_SIZE, invalid_variable_names, load_gateway_settings, load_vector_settings,
)
from app.ingestion import DocumentReport, IndexedChunk, index_chunks, prepare_document


async def execute_ingestion(chunks: list[IndexedChunk]) -> dict[str, object]:
    from app.gateway import create_gateway_client
    from app.vector_store import create_vector_client

    try:
        gateway_settings = load_gateway_settings()
    except ValidationError as exc:
        return {"status": "invalid_config", "failures": [{"code": "invalid_config", "variables": invalid_variable_names(exc, "gateway")}]}
    try:
        vector_settings = load_vector_settings()
    except ValidationError as exc:
        return {"status": "invalid_config", "failures": [{"code": "invalid_config", "variables": invalid_variable_names(exc, "vector")}]}
    if gateway_settings.embedding_dimension != vector_settings.dimension:
        raise ValueError("embedding_dimension_configuration_mismatch")
    store = create_vector_client(vector_settings)
    try:
        async with create_gateway_client(gateway_settings) as gateway:
            return await index_chunks(store, vector_settings, gateway, gateway_settings, chunks)
    finally:
        await store.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inspeção ou ingestão explícita dos quatro PDFs do PRD.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="Extrair e dividir sem indexar.")
    mode.add_argument("--execute", action="store_true", help="Indexar após autorização e revisão do dry-run.")
    parser.add_argument("--gateway-verified", action="store_true", help="Atestar compatibilidade real já conferida na Etapa 2.")
    parser.add_argument("--extraction-reviewed", action="store_true", help="Atestar revisão/aceitação das perdas de extração.")
    parser.add_argument("--max-embedding-calls", type=int, help="Teto de chamadas revisado antes de executar.")
    parser.add_argument("--input-dir", type=Path, default=RAW_PDF_DIR)
    args = parser.parse_args(argv)
    if args.execute and (not args.gateway_verified or not args.extraction_reviewed
                         or args.max_embedding_calls is None or args.max_embedding_calls < 1):
        parser.error("--execute exige --gateway-verified, --extraction-reviewed e --max-embedding-calls positivo.")

    documents: list[DocumentReport] = []
    failures: list[dict[str, str]] = []
    chunks: list[IndexedChunk] = []
    for name in EXPECTED_DOCUMENTS:
        path = args.input_dir / name
        if not path.is_file():
            failures.append({"document_name": name, "code": "missing_file"})
            continue
        try:
            report, prepared = prepare_document(path)
        except (OSError, PyPdfError, ValueError):
            # Não publicar mensagens brutas do parser nem conteúdo do documento.
            failures.append({"document_name": name, "code": "pdf_extraction_failed"})
            continue
        documents.append(report)
        chunks.extend(prepared)
        if report["total_pages"] == 0:
            failures.append({"document_name": name, "code": "pdf_without_pages"})
        elif report["total_chunks"] == 0:
            failures.append({"document_name": name, "code": "pdf_without_chunks"})

    max_calls = math.ceil(len(chunks) / EMBEDDING_BATCH_SIZE)
    result: dict[str, object] = {
        "mode": "dry-run" if args.dry_run else "execute",
        "chunk_size": CHUNK_SIZE,
        "chunk_overlap": CHUNK_OVERLAP,
        "short_page_chars": SHORT_PAGE_CHARS,
        "expected_documents": len(EXPECTED_DOCUMENTS),
        "processed_documents": len(documents),
        "total_chunks": sum(doc["total_chunks"] for doc in documents),
        "documents": documents,
        "failures": failures,
        "manual_review_required": True,
        "embedding_batch_size": EMBEDDING_BATCH_SIZE,
        "max_embedding_calls": max_calls,
        "max_qdrant_operations": 4 + 2 * max_calls + 7,
    }
    if args.execute and not failures:
        if max_calls > args.max_embedding_calls:
            result["failures"] = [{"code": "embedding_call_budget_exceeded"}]
        else:
            for name in ("openai", "httpx", "httpcore", "qdrant_client"):
                logging.getLogger(name).setLevel(logging.CRITICAL)
            try:
                result["indexing"] = asyncio.run(execute_ingestion(chunks))
                if result["indexing"]["status"] != "passed":
                    result["failures"] = result["indexing"]["failures"]
            except Exception:
                result["failures"] = [{"code": "indexing_configuration_or_connection_failed"}]
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
