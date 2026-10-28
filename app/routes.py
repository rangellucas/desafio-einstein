"""Rotas JSON, autenticação Bearer e erros públicos sem mensagens do provedor."""

import hmac
import logging
from typing import Annotated
from uuid import uuid4

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from openai import APIConnectionError, APIError, APIStatusError, APITimeoutError

from app.gateway import GatewayContractError
from app.prompts import INSUFFICIENT_CONTEXT
from app.rag import generate_answer, prepare_answer
from app.schemas import ChatRequest, ChatResponse, ErrorResponse, ModelsResponse
from app.vector_store import BaseUnavailable

router = APIRouter()
logger = logging.getLogger(__name__)
bearer = HTTPBearer(auto_error=False, description="Token da aplicação (API_ACCESS_TOKEN), quando configurado.")


def public_error(status: int, code: str, message: str, request_id: str) -> HTTPException:
    logger.info("chat_error request_id=%s route=/chat code=%s status=%d", request_id, code, status)
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
        return public_error(504, "gateway_timeout", "O serviço de modelos excedeu o prazo de resposta.", request_id)
    if isinstance(error, (APIConnectionError, httpx.TransportError)):
        return public_error(503, "gateway_unavailable", "Serviço de modelos temporariamente indisponível.", request_id)
    if isinstance(error, APIStatusError) and (error.status_code == 429 or error.status_code >= 500):
        return public_error(503, "gateway_unavailable", "Serviço de modelos temporariamente indisponível.", request_id)
    return public_error(502, "gateway_error", "Não foi possível obter uma resposta válida do serviço de modelos.", request_id)


@router.post(
    "/chat", response_model=ChatResponse, summary="Consultar o material e receber resposta JSON com fontes",
    dependencies=[Depends(authenticate)],
    responses={
        401: {"model": ErrorResponse, "description": "Token ausente ou incorreto"},
        502: {"model": ErrorResponse, "description": "Falha ou resposta inválida do gateway"},
        503: {"model": ErrorResponse, "description": "Base ou serviço de modelos indisponível"},
        504: {"model": ErrorResponse, "description": "Timeout do serviço de modelos"},
    },
    openapi_extra={"requestBody": {"content": {"application/json": {"example": {
        "question": "Como a atenção primária participa do cuidado em saúde mental?",
        "model": "azure/gpt-5-mini",
    }}}}},
)
async def chat(body: ChatRequest, request: Request) -> ChatResponse:
    """Cada pergunta recupera suas próprias fontes; não mantém mensagens anteriores."""
    state = request.app.state
    request_id = request.state.request_id
    model = state.api_settings.default_chat_model if body.model is None else body.model
    if model not in state.api_settings.chat_models:
        raise public_error(422, "model_not_allowed", "Modelo não permitido. Consulte /models.", request_id)
    if state.vector_client is None:
        raise public_error(503, "base_unavailable", "Base indisponível para consulta.", request_id)
    if state.gateway_client is None:
        raise public_error(503, "gateway_unavailable", "Serviço de modelos não configurado para consulta.", request_id)
    try:
        messages, sources = await prepare_answer(
            body.question, state.vector_client, state.vector_settings,
            state.gateway_client, state.gateway_settings, request_id=request_id,
        )
        if not sources:
            answer, reason = INSUFFICIENT_CONTEXT, "insufficient_context"
        else:
            answer, reason = await generate_answer(
                state.gateway_client, state.gateway_settings, model, messages, request_id=request_id,
            )
    except (BaseUnavailable, GatewayContractError, APIError, httpx.HTTPError, TimeoutError) as error:
        raise dependency_error(error, request_id) from None
    logger.info("chat_done request_id=%s route=/chat model=%s chunks=%d finish_reason=%s", request_id, model, len(sources), reason)
    return ChatResponse(request_id=request_id, model=model, answer=answer, sources=sources, finish_reason=reason)
