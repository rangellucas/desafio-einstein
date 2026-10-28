"""Consultas JSON/SSE com RAG único, autenticação e erros públicos."""

import asyncio
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import AsyncExitStack
import hmac
import logging
from time import perf_counter
from typing import Annotated
from uuid import uuid4

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from openai import APIConnectionError, APIStatusError, APITimeoutError
from starlette.requests import ClientDisconnect

from app.execution import QueryStreamingResponse, close_after_failure, run_connected, sse_event
from app.gateway import ChatPart
from app.prompts import INSUFFICIENT_CONTEXT
from app.rag import collect_answer, open_answer, prepare_answer
from app.schemas import (
    ChatRequest, ChatResponse, DeltaEvent, DoneEvent, ErrorDetail, ErrorResponse,
    ModelsResponse, Source, SourcesEvent,
)
from app.vector_store import BaseUnavailable

router = APIRouter()
logger = logging.getLogger(__name__)
bearer = HTTPBearer(auto_error=False, description="Token da aplicação (API_ACCESS_TOKEN), quando configurado.")


def public_error(status: int, code: str, message: str, request_id: str) -> HTTPException:
    logger.info("chat_error request_id=%s code=%s status=%d", request_id, code, status)
    return HTTPException(status_code=status, detail={"code": code, "message": message, "request_id": request_id})


def authenticate(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> None:
    request.state.request_id = str(uuid4())
    token = request.app.state.api_settings.access_token
    if token is None:
        return
    if credentials is None or not hmac.compare_digest(
        credentials.credentials.encode(), token.get_secret_value().encode(),
    ):
        error = public_error(401, "unauthorized", "Token de acesso ausente ou incorreto.", request.state.request_id)
        error.headers = {"WWW-Authenticate": "Bearer"}
        raise error


@router.get("/models", response_model=ModelsResponse, summary="Listar modelos configurados, sem consultar o gateway")
def models(request: Request) -> ModelsResponse:
    settings = request.app.state.api_settings
    return ModelsResponse(models=list(settings.chat_models), default_model=settings.default_chat_model)


def dependency_error(error: Exception, request_id: str) -> HTTPException:
    if isinstance(error, BaseUnavailable):
        return public_error(503, "base_unavailable", "Base indisponível para consulta.", request_id)
    if isinstance(error, (TimeoutError, APITimeoutError, httpx.TimeoutException)):
        return public_error(504, "gateway_timeout", "A consulta excedeu o prazo de resposta.", request_id)
    if isinstance(error, (APIConnectionError, httpx.TransportError)):
        return public_error(503, "gateway_unavailable", "Serviço de modelos temporariamente indisponível.", request_id)
    if isinstance(error, APIStatusError) and (error.status_code == 429 or error.status_code >= 500):
        return public_error(503, "gateway_unavailable", "Serviço de modelos temporariamente indisponível.", request_id)
    return public_error(502, "gateway_error", "Não foi possível obter uma resposta válida do serviço de modelos.", request_id)


ERROR_RESPONSES = {
    401: {"model": ErrorResponse, "description": "Token ausente ou incorreto"},
    429: {"model": ErrorResponse, "description": "Capacidade simultânea ocupada; nenhuma chamada externa iniciada"},
    502: {"model": ErrorResponse, "description": "Falha ou resposta inválida do gateway antes dos cabeçalhos"},
    503: {"model": ErrorResponse, "description": "Base ou serviço de modelos indisponível"},
    504: {"model": ErrorResponse, "description": "Prazo total excedido antes dos cabeçalhos"},
}
REQUEST_EXAMPLE = {"requestBody": {"content": {"application/json": {"example": {
    "question": "Como a atenção primária participa do cuidado em saúde mental?",
    "model": "azure/gpt-5-mini",
}}}}}


async def answer_events(
    parts: AsyncIterator[ChatPart] | None, sources: list[Source], model: str,
    request_id: str, resources: AsyncExitStack, route: str,
) -> AsyncGenerator[str, None]:
    yield sse_event("sources", SourcesEvent(request_id=request_id, model=model, sources=sources))
    reason = "insufficient_context"
    if parts is None:
        # Exceção explicitada pelo escopo da Etapa 5: explicação local sem geração.
        yield sse_event("delta", DeltaEvent(text=INSUFFICIENT_CONTEXT))
    else:
        async for part in parts:
            if part["text"]:
                yield sse_event("delta", DeltaEvent(text=part["text"]))
            if part["finish_reason"] is not None:
                reason = part["finish_reason"]
    # Fechar o provedor antes de declarar sucesso; falha de fechamento vira error.
    await resources.aclose()
    logger.info("chat_done request_id=%s route=%s model=%s chunks=%d finish_reason=%s", request_id, route, model, len(sources), reason)
    yield sse_event("done", DoneEvent(finish_reason=reason))


async def run_chat(body: ChatRequest, request: Request, *, streaming: bool) -> ChatResponse | QueryStreamingResponse:
    """Mesma admissão, preparação e geração; só a forma de consumir difere."""
    state = request.app.state
    request_id = request.state.request_id
    model = state.api_settings.default_chat_model if body.model is None else body.model
    if model not in state.api_settings.chat_models:
        raise public_error(422, "model_not_allowed", "Modelo não permitido. Consulte /models.", request_id)
    # acquire não suspende quando há vaga; não há await entre locked e acquire.
    # Rejeição imediata, sem fila e antes de prontidão/embedding/busca/geração.
    slots = state.query_slots
    if slots.locked():
        raise public_error(429, "capacity_exceeded", "Capacidade de consultas ocupada. Tente novamente mais tarde.", request_id)
    await slots.acquire()
    resources = AsyncExitStack()
    resources.callback(slots.release)
    generation = AsyncExitStack()
    resources.push_async_callback(generation.aclose)
    deadline = asyncio.get_running_loop().time() + state.api_settings.request_timeout_seconds
    started = perf_counter()

    async def prepare() -> tuple[AsyncIterator[ChatPart] | None, list[Source]]:
        if state.vector_client is None:
            raise BaseUnavailable("base_not_configured")
        if state.gateway_client is None:
            raise public_error(503, "gateway_unavailable", "Serviço de modelos não configurado para consulta.", request_id)
        messages, sources = await prepare_answer(
            body.question, state.vector_client, state.vector_settings,
            state.gateway_client, state.gateway_settings, request_id=request_id,
        )
        parts = None
        if sources:
            # Abrir antes de devolver StreamingResponse permite erro HTTP nesta fase.
            async with asyncio.timeout(state.gateway_settings.request_timeout_seconds):
                parts = await generation.enter_async_context(open_answer(
                    state.gateway_client, state.gateway_settings, model, messages, request_id=request_id,
                ))
        return parts, sources

    try:
        async with asyncio.timeout_at(deadline):
            parts, sources = await run_connected(request, prepare())
            if not streaming:
                if parts is None:
                    answer, reason = INSUFFICIENT_CONTEXT, "insufficient_context"
                else:
                    answer, reason = await run_connected(request, collect_answer(parts))
                await resources.aclose()
                logger.info("chat_done request_id=%s route=%s model=%s chunks=%d finish_reason=%s", request_id, request.url.path, model, len(sources), reason)
                return ChatResponse(request_id=request_id, model=model, answer=answer, sources=sources, finish_reason=reason)
        return QueryStreamingResponse(
            answer_events(parts, sources, model, request_id, generation, request.url.path),
            resources, deadline,
            lambda error: ErrorDetail(**dependency_error(error, request_id).detail),
        )
    except BaseException as error:
        await close_after_failure(resources)
        if isinstance(error, (ClientDisconnect, asyncio.CancelledError)):
            logger.info("query_cancelled request_id=%s route=%s", request_id, request.url.path)
            raise
        if isinstance(error, HTTPException):
            raise
        if isinstance(error, Exception):
            raise dependency_error(error, request_id) from None
        raise
    finally:
        logger.info("chat_prepared request_id=%s route=%s model=%s duration_ms=%.1f", request_id, request.url.path, model, (perf_counter() - started) * 1000)


@router.post(
    "/chat", response_model=ChatResponse, summary="Consultar o material e receber resposta JSON com fontes",
    dependencies=[Depends(authenticate)], responses=ERROR_RESPONSES, openapi_extra=REQUEST_EXAMPLE,
)
async def chat(body: ChatRequest, request: Request) -> ChatResponse:
    return await run_chat(body, request, streaming=False)


@router.post(
    "/chat/stream", response_class=QueryStreamingResponse, response_model=None, status_code=200,
    summary="Consultar o material e receber eventos SSE progressivos",
    description=("sources {request_id, model, sources:[{id, document, page, excerpt}]} precede "
                 "delta {text}; done {finish_reason:stop/length/insufficient_context} ou "
                 "error {code, message, request_id} encerra. Payloads JSON separados por linha vazia. "
                 "Depois dos cabeçalhos, falhas usam error sem mudar o HTTP 200. "
                 "Sem contexto, delta contém explicação local e não há geração. "
                 "Use curl -N ou scripts/check_stream.py; Swagger não prova entrega incremental."),
    dependencies=[Depends(authenticate)], openapi_extra=REQUEST_EXAMPLE,
    responses={**ERROR_RESPONSES, 200: {"description": "Eventos sources, delta e done, ou error terminal",
        "content": {"text/event-stream": {"schema": {"type": "string"}, "examples": {
            "success": {"summary": "Geração com fonte e término normal", "value":
                'event: sources\ndata: {"request_id":"abc","model":"azure/gpt-5-mini","sources":[{"id":"S1","document":"apostila.pdf","page":12,"excerpt":"Trecho ilustrativo."}]}\n\n'
                'event: delta\ndata: {"text":"Resposta educacional. [S1]"}\n\n'
                'event: done\ndata: {"finish_reason":"stop"}\n\n'},
            "length": {"summary": "Saída interrompida por limite", "value":
                'event: done\ndata: {"finish_reason":"length"}\n\n'},
            "no_context": {"summary": "Explicação local sem gerar", "value":
                'event: sources\ndata: {"request_id":"abc","model":"azure/gpt-5-mini","sources":[]}\n\n'
                'event: delta\ndata: {"text":"Não há trechos utilizáveis."}\n\n'
                'event: done\ndata: {"finish_reason":"insufficient_context"}\n\n'},
            "error": {"summary": "Falha terminal após os cabeçalhos; não há done", "value":
                'event: error\ndata: {"code":"gateway_error","message":"Não foi possível obter uma resposta válida do serviço de modelos.","request_id":"abc"}\n\n'},
        }}}}},
)
async def chat_stream(body: ChatRequest, request: Request) -> QueryStreamingResponse:
    return await run_chat(body, request, streaming=True)
