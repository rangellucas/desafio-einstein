"""Recuperação compartilhável pelas futuras rotas JSON e SSE, sem geração."""

import asyncio

from openai import AsyncOpenAI
from qdrant_client import AsyncQdrantClient

from app.config import GatewaySettings, VectorSettings
from app.gateway import embed_texts
from app.vector_store import SearchHit, check_ready, search_chunks


async def retrieve_chunks(
    question: str, store: AsyncQdrantClient, vector_settings: VectorSettings,
    gateway: AsyncOpenAI, gateway_settings: GatewaySettings,
) -> list[SearchHit]:
    question = question.strip()
    if not 1 <= len(question) <= 1500:
        raise ValueError("invalid_question")
    if gateway_settings.embedding_dimension != vector_settings.dimension:
        raise ValueError("embedding_dimension_configuration_mismatch")
    # Falhas da base são detectadas antes de consumir o gateway.
    await check_ready(store, vector_settings)
    async with asyncio.timeout(gateway_settings.request_timeout_seconds):
        vectors = await embed_texts(gateway, gateway_settings, [question], "search_query")
    return await search_chunks(store, vector_settings, vectors[0])
