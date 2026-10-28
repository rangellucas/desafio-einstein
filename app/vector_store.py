"""Qdrant assíncrono: nunca apaga/recria coleções nem calcula embeddings."""

import math
from typing import TypedDict, cast

from qdrant_client import AsyncQdrantClient, models

from app.config import (
    CHUNK_OVERLAP, CHUNK_SIZE, EMBEDDING_MODEL, EXPECTED_DOCUMENTS,
    PIPELINE_VERSION, SEARCH_LIMIT, VectorSettings,
)
from app.ingestion import IndexedChunk


class BaseUnavailable(ValueError):
    """Código fixo local; mensagens externas nunca são públicas."""


class SearchHit(TypedDict):
    chunk: IndexedChunk
    score: float


def create_vector_client(settings: VectorSettings) -> AsyncQdrantClient:
    if settings.url:
        return AsyncQdrantClient(
            url=settings.url, api_key=settings.api_key.get_secret_value(),
            prefer_grpc=False, timeout=15, check_compatibility=False,
            # Evita a sondagem de versão em uma thread e redirecionamentos implícitos.
            follow_redirects=False,
        )
    return AsyncQdrantClient(path=str(settings.path))


def collection_contract(settings: VectorSettings) -> dict[str, object]:
    return {
        "pipeline_version": PIPELINE_VERSION, "embedding_model": EMBEDDING_MODEL,
        "dimension": settings.dimension, "chunk_size": CHUNK_SIZE,
        "chunk_overlap": CHUNK_OVERLAP,
    }


def validate_manifest(value: object) -> list[dict[str, str | int]]:
    if not isinstance(value, list) or len(value) != len(EXPECTED_DOCUMENTS):
        raise BaseUnavailable("collection_manifest_invalid")
    names = []
    for item in value:
        if (not isinstance(item, dict) or set(item) != {"document_name", "document_hash", "chunks"}
                or item["document_name"] not in EXPECTED_DOCUMENTS
                or not isinstance(item["document_hash"], str) or len(item["document_hash"]) != 64
                or type(item["chunks"]) is not int or item["chunks"] <= 0):
            raise BaseUnavailable("collection_manifest_invalid")
        names.append(item["document_name"])
    if len(set(names)) != len(EXPECTED_DOCUMENTS):
        raise BaseUnavailable("collection_manifest_invalid")
    return cast(list[dict[str, str | int]], value)


async def validate_collection(
    client: AsyncQdrantClient, settings: VectorSettings,
) -> list[dict[str, str | int]]:
    if not await client.collection_exists(settings.collection):
        raise BaseUnavailable("collection_missing")
    info = await client.get_collection(settings.collection)
    params = info.config.params.vectors
    if (not isinstance(params, models.VectorParams) or params.size != settings.dimension
            or params.distance != models.Distance.COSINE):
        raise BaseUnavailable("collection_vectors_incompatible")
    metadata = info.config.metadata or {}
    if metadata.get("rag_contract") != collection_contract(settings):
        raise BaseUnavailable("collection_version_incompatible")
    return validate_manifest(metadata.get("documents"))


async def ensure_collection(
    client: AsyncQdrantClient, settings: VectorSettings, manifest: list[dict[str, str | int]],
) -> None:
    validate_manifest(manifest)
    if not await client.collection_exists(settings.collection):
        await client.create_collection(
            settings.collection,
            vectors_config=models.VectorParams(size=settings.dimension, distance=models.Distance.COSINE),
            metadata={"rag_contract": collection_contract(settings), "documents": manifest},
        )
    observed = await validate_collection(client, settings)
    if observed != manifest:
        raise BaseUnavailable("collection_documents_changed_use_new_collection")


def validate_vector(vector: list[float], dimension: int) -> None:
    if (len(vector) != dimension or any(type(v) not in {int, float} or not math.isfinite(v) for v in vector)
            or not any(v != 0 for v in vector)):
        raise BaseUnavailable("vector_invalid")


async def existing_chunks(
    client: AsyncQdrantClient, settings: VectorSettings, chunks: list[IndexedChunk],
) -> set[str]:
    records = await client.retrieve(
        settings.collection, ids=[c["chunk_id"] for c in chunks], with_payload=True, with_vectors=False,
    )
    expected = {c["chunk_id"]: c for c in chunks}
    for record in records:
        if record.payload != expected.get(str(record.id)):
            raise BaseUnavailable("existing_chunk_incompatible")
    return {str(record.id) for record in records}


async def upsert_chunks(
    client: AsyncQdrantClient, settings: VectorSettings,
    chunks: list[IndexedChunk], vectors: list[list[float]],
) -> None:
    if len(chunks) != len(vectors):
        raise BaseUnavailable("embedding_count_mismatch")
    # Validar o lote inteiro antes de qualquer escrita.
    for vector in vectors:
        validate_vector(vector, settings.dimension)
    await client.upsert(
        settings.collection, wait=True,
        points=[models.PointStruct(id=chunk["chunk_id"], vector=vector, payload=dict(chunk))
                for chunk, vector in zip(chunks, vectors, strict=True)],
    )


async def check_ready(client: AsyncQdrantClient, settings: VectorSettings) -> None:
    """Confere contagens exatas e cobertura dos quatro documentos, sem modelos."""
    manifest = await validate_collection(client, settings)
    total = await client.count(settings.collection, exact=True)
    if total.count != sum(int(doc["chunks"]) for doc in manifest):
        raise BaseUnavailable("collection_incomplete")
    for doc in manifest:
        filters = {
            "document_name": doc["document_name"], "document_hash": doc["document_hash"],
            "pipeline_version": PIPELINE_VERSION, "embedding_model": EMBEDDING_MODEL,
        }
        count = await client.count(
            settings.collection, exact=True,
            count_filter=models.Filter(must=[
                models.FieldCondition(key=key, match=models.MatchValue(value=value))
                for key, value in filters.items()
            ]),
        )
        if count.count != doc["chunks"]:
            raise BaseUnavailable("collection_document_incomplete")


async def search_chunks(
    client: AsyncQdrantClient, settings: VectorSettings, vector: list[float],
) -> list[SearchHit]:
    validate_vector(vector, settings.dimension)
    result = await client.query_points(
        settings.collection, query=vector, limit=SEARCH_LIMIT,
        with_payload=True, with_vectors=False,
    )
    hits: list[SearchHit] = []
    for point in result.points:
        payload = point.payload or {}
        if (not isinstance(payload.get("text"), str) or not payload["text"].strip()
                or payload.get("document_name") not in EXPECTED_DOCUMENTS
                or type(payload.get("page")) is not int or payload["page"] < 1
                or payload.get("chunk_id") != str(point.id)
                or payload.get("embedding_model") != EMBEDDING_MODEL
                or payload.get("pipeline_version") != PIPELINE_VERSION):
            raise BaseUnavailable("chunk_payload_invalid")
        hits.append(SearchHit(chunk=cast(IndexedChunk, payload), score=point.score))
    return hits
