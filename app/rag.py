"""Recuperação e preparação comuns; JSON acumula a geração do mesmo adaptador."""

import asyncio
import logging
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from time import perf_counter
from typing import Literal

from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionMessageParam
from qdrant_client import AsyncQdrantClient

from app.config import GatewaySettings, VectorSettings
from app.gateway import ChatPart, GatewayContractError, embed_texts, open_chat_stream
from app.prompts import build_context, build_messages
from app.schemas import Source
from app.vector_store import BaseUnavailable, SearchHit, check_ready, search_chunks

logger = logging.getLogger(__name__)


async def retrieve_chunks(
    question: str, store: AsyncQdrantClient, vector_settings: VectorSettings,
    gateway: AsyncOpenAI, gateway_settings: GatewaySettings,
    *, request_id: str = "offline",
) -> list[SearchHit]:
    question = question.strip()
    if not 1 <= len(question) <= 1500:
        raise ValueError("invalid_question")
    if gateway_settings.embedding_dimension != vector_settings.dimension:
        raise BaseUnavailable("embedding_dimension_configuration_mismatch")
    # Falhas da base são detectadas antes de consumir o gateway.
    try:
        await check_ready(store, vector_settings)
    except BaseUnavailable:
        raise
    except Exception:
        raise BaseUnavailable("base_unavailable") from None
    started = perf_counter()
    async with asyncio.timeout(gateway_settings.request_timeout_seconds):
        vectors = await embed_texts(gateway, gateway_settings, [question], "search_query")
    logger.info("rag_step request_id=%s stage=embedding duration_ms=%.1f", request_id, (perf_counter() - started) * 1000)
    started = perf_counter()
    try:
        hits = await search_chunks(store, vector_settings, vectors[0])
    except BaseUnavailable:
        raise
    except Exception:
        raise BaseUnavailable("base_unavailable") from None
    logger.info("rag_step request_id=%s stage=search duration_ms=%.1f chunks=%d", request_id, (perf_counter() - started) * 1000, len(hits))
    return hits


async def prepare_answer(
    question: str, store: AsyncQdrantClient, vector_settings: VectorSettings,
    gateway: AsyncOpenAI, gateway_settings: GatewaySettings, *, request_id: str,
) -> tuple[list[ChatCompletionMessageParam], list[Source]]:
    """Recupera e prepara fontes/mensagens sem iniciar geração; reutilizável por SSE."""
    hits = await retrieve_chunks(
        question, store, vector_settings, gateway, gateway_settings, request_id=request_id,
    )
    context, sources = build_context(hits)
    return build_messages(question, context), sources


@asynccontextmanager
async def open_answer(
    gateway: AsyncOpenAI, settings: GatewaySettings, model: str,
    messages: list[ChatCompletionMessageParam], *, request_id: str,
) -> AsyncIterator[AsyncIterator[ChatPart]]:
    """Uma abertura e uma validação de geração para JSON e SSE, sem acumular texto."""
    started = perf_counter()
    try:
        async with open_chat_stream(gateway, settings, model, messages) as parts:
            validated = valid_answer_parts(parts)
            try:
                yield validated
            finally:
                await validated.aclose()
    finally:
        logger.info("rag_step request_id=%s stage=generation duration_ms=%.1f", request_id, (perf_counter() - started) * 1000)


async def valid_answer_parts(parts: AsyncIterator[ChatPart]) -> AsyncGenerator[ChatPart, None]:
    has_text = False
    reason = None
    async for part in parts:
        has_text = has_text or bool(part["text"].strip())
        if part["finish_reason"] is not None:
            reason = part["finish_reason"]
            if reason not in {"stop", "length"}:
                raise GatewayContractError("chat_completion_invalid")
        yield part
    if not has_text or reason not in {"stop", "length"}:
        raise GatewayContractError("chat_completion_invalid")


async def collect_answer(parts: AsyncIterator[ChatPart]) -> tuple[str, Literal["stop", "length"]]:
    """Somente a rota JSON acumula os fragmentos já validados do fluxo comum."""
    fragments: list[str] = []
    reason: Literal["stop", "length"] = "stop"
    async for part in parts:
        fragments.append(part["text"])
        if part["finish_reason"] == "length":
            reason = "length"
    return "".join(fragments), reason
