"""Contrato candidato do gateway; aceitação real depende da verificação opt-in."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import json
import math
from typing import Literal, TypedDict

import httpx
from openai import AsyncOpenAI, AsyncStream
from openai.types.chat import ChatCompletionChunk, ChatCompletionMessageParam

from app.config import GatewaySettings

InputType = Literal["search_document", "search_query"]


class GatewayContractError(ValueError):
    """Código local fixo, sem incluir resposta bruta do provedor."""


class ChatPart(TypedDict):
    text: str
    finish_reason: str | None


def create_gateway_client(
    settings: GatewaySettings, *, transport: httpx.AsyncBaseTransport | None = None,
) -> AsyncOpenAI:
    """O chamador deve fechar o cliente com async with; transporte injetável nos testes."""
    return AsyncOpenAI(
        base_url=settings.base_url,
        api_key=settings.api_key.get_secret_value(),
        max_retries=0,
        timeout=settings.request_timeout_seconds,
        http_client=httpx.AsyncClient(
            transport=transport, timeout=settings.request_timeout_seconds,
            # Redirecionamentos também poderiam aumentar a quantidade de requisições.
            follow_redirects=False,
        ),
    )


async def embed_texts(
    client: AsyncOpenAI, settings: GatewaySettings, texts: list[str], input_type: InputType,
) -> list[list[float]]:
    """Uma chamada por lote; devolve vetores na ordem original, sem presumir dimensão."""
    if input_type not in {"search_document", "search_query"}:
        raise ValueError("invalid_input_type")
    if not texts or any(not text.strip() for text in texts):
        raise ValueError("empty_embedding_input")
    response = await client.embeddings.with_raw_response.create(
        model=settings.embedding_model, input=texts, encoding_format="float",
        # Campo Cohere candidato, concentrado aqui para eventual ajuste do gateway.
        extra_body={"input_type": input_type},
    )
    # Validar o JSON antes de conversões permissivas do SDK (ex.: bool para float).
    try:
        payload: object = response.http_response.json()
    except ValueError:
        raise GatewayContractError("embedding_response_invalid") from None
    if not isinstance(payload, dict):
        raise GatewayContractError("embedding_response_invalid")
    data = payload.get("data")
    if not isinstance(data, list) or len(data) != len(texts):
        raise GatewayContractError("embedding_count_mismatch")
    if any(not isinstance(item, dict) for item in data):
        raise GatewayContractError("embedding_response_invalid")
    indices = [item.get("index") for item in data]
    if any(type(index) is not int for index in indices) or set(indices) != set(range(len(texts))):
        raise GatewayContractError("embedding_indices_invalid")
    vectors: list[list[float]] = []
    dimension = settings.embedding_dimension
    for item in sorted(data, key=lambda item: item["index"]):
        vector = item.get("embedding")
        if (not isinstance(vector, list) or not vector
                or any(type(value) not in {int, float} or not math.isfinite(value) for value in vector)
                or not any(value != 0 for value in vector)):
            raise GatewayContractError("embedding_vector_invalid")
        if dimension is None:
            dimension = len(vector)
        if len(vector) != dimension:
            raise GatewayContractError("embedding_dimension_mismatch")
        vectors.append([float(value) for value in vector])
    return vectors


async def iter_chat_parts(stream: AsyncStream[ChatCompletionChunk]) -> AsyncIterator[ChatPart]:
    """Gerador: yield repassa cada fragmento; nunca acumula para subdividir a resposta."""
    finished = False
    async for chunk in stream:
        choices = getattr(chunk, "choices", None)
        if choices == []:
            # Alguns provedores enviam metadados de uso sem choices ao final.
            continue
        if not isinstance(choices, list) or len(choices) != 1:
            raise GatewayContractError("chat_choices_invalid")
        choice = choices[0]
        delta = getattr(choice, "delta", None)
        if getattr(choice, "index", None) != 0 or finished or delta is None:
            raise GatewayContractError("chat_sequence_invalid")
        text = getattr(delta, "content", None)
        reason = getattr(choice, "finish_reason", None)
        if text is not None and not isinstance(text, str):
            raise GatewayContractError("chat_content_invalid")
        if reason is not None and reason not in {"stop", "length", "content_filter", "tool_calls", "function_call"}:
            raise GatewayContractError("chat_finish_reason_invalid")
        if text or reason is not None:
            yield {"text": text or "", "finish_reason": reason}
        finished = reason is not None
    if not finished:
        raise GatewayContractError("chat_missing_finish_reason")


@asynccontextmanager
async def open_chat_stream(
    client: AsyncOpenAI, settings: GatewaySettings, model: str,
    messages: list[ChatCompletionMessageParam], *, max_output_tokens: int | None = None,
) -> AsyncIterator[AsyncIterator[ChatPart]]:
    """Abre ao entrar no contexto; fecha o HTTP em sucesso, erro ou saída antecipada."""
    if model not in settings.chat_models:
        raise ValueError("model_not_allowed")
    limit = settings.max_output_tokens if max_output_tokens is None else max_output_tokens
    if limit <= 0:
        raise ValueError("invalid_output_limit")
    stream = await client.chat.completions.create(
        model=model, messages=messages, stream=True, max_completion_tokens=limit,
    )
    async with stream:
        try:
            yield iter_chat_parts(stream)
        except json.JSONDecodeError:
            raise GatewayContractError("chat_response_invalid") from None
