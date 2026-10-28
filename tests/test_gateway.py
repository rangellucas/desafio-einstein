import asyncio
import json
from collections.abc import AsyncIterator

import httpx
import pytest

from app.config import CHAT_MODELS, GatewaySettings, load_gateway_settings
from app.gateway import GatewayContractError, create_gateway_client, embed_texts, open_chat_stream


@pytest.fixture
def settings() -> GatewaySettings:
    return load_gateway_settings({"LLM_BASE_URL": "https://gateway.test/v1", "LLM_API_KEY": "synthetic-test-only"})


def embedding_response(vectors: list[list[float]], indices: list[int] | None = None) -> httpx.Response:
    return httpx.Response(200, json={
        "object": "list", "model": "cohere/embed-v4.0",
        "data": [{"object": "embedding", "index": index, "embedding": vector}
                 for index, vector in zip(indices if indices is not None else range(len(vectors)), vectors)],
        "usage": {"prompt_tokens": 1, "total_tokens": 1},
    })


def chat_event(text: str | None = None, reason: str | None = None) -> bytes:
    return ("data: " + json.dumps({
        "id": "synthetic", "object": "chat.completion.chunk", "created": 0,
        "model": "synthetic", "choices": [{"index": 0, "delta": {"content": text}, "finish_reason": reason}],
    }, ensure_ascii=False) + "\n\n").encode()


class SimulatedSSE(httpx.AsyncByteStream):
    """Fragmentos HTTP controlados para verificar leitura incremental e fechamento."""

    def __init__(self, chunks: list[bytes], *, failure: Exception | None = None) -> None:
        self.chunks = chunks
        self.failure = failure
        self.sent = 0
        self.closed = False

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for chunk in self.chunks:
            self.sent += 1
            yield chunk
        if self.failure:
            raise self.failure

    async def aclose(self) -> None:
        self.closed = True


def test_embedding_payload_and_original_order(settings: GatewaySettings) -> None:
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return embedding_response([[0.3, 0.4], [0.1, 0.2]], [1, 0])

    async def run() -> None:
        async with create_gateway_client(settings, transport=httpx.MockTransport(handle)) as client:
            for input_type in ("search_document", "search_query"):
                assert await embed_texts(client, settings, ["primeiro", "segundo"], input_type) == [[0.1, 0.2], [0.3, 0.4]]
        assert client.is_closed()

    asyncio.run(run())
    assert len(requests) == 2
    for request, input_type in zip(requests, ("search_document", "search_query")):
        assert request.method == "POST"
        assert str(request.url) == "https://gateway.test/v1/embeddings"
        assert request.headers["authorization"] == "Bearer synthetic-test-only"
        assert json.loads(request.content) == {
            "model": "cohere/embed-v4.0", "input": ["primeiro", "segundo"],
            "encoding_format": "float", "input_type": input_type,
        }


@pytest.mark.parametrize(("vectors", "indices", "expected"), [
    ([], [], "embedding_count_mismatch"),
    ([[1.0], [2.0]], [0, 0], "embedding_indices_invalid"),
    ([[1.0], [2.0]], [0, 2], "embedding_indices_invalid"),
    ([[], []], [0, 1], "embedding_vector_invalid"),
    ([[0.0], [1.0]], [0, 1], "embedding_vector_invalid"),
    ([[float("nan")], [1.0]], [0, 1], "embedding_vector_invalid"),
    ([[float("inf")], [1.0]], [0, 1], "embedding_vector_invalid"),
    ([[True], [1.0]], [0, 1], "embedding_vector_invalid"),
    ([["invalid"], [1.0]], [0, 1], "embedding_vector_invalid"),
    ([[1.0], [1.0, 2.0]], [0, 1], "embedding_dimension_mismatch"),
])
def test_rejects_invalid_embeddings(settings: GatewaySettings, vectors: list, indices: list[int], expected: str) -> None:
    async def run() -> None:
        # content permite testar JSON não finito vindo de provedor incompatível.
        response = embedding_response([[1.0], [2.0]])
        body = response.json()
        body["data"] = [{"object": "embedding", "index": i, "embedding": v} for i, v in zip(indices, vectors)]
        transport = httpx.MockTransport(lambda request: httpx.Response(200, content=json.dumps(body)))
        async with create_gateway_client(settings, transport=transport) as client:
            with pytest.raises(GatewayContractError, match=expected):
                await embed_texts(client, settings, ["a", "b"], "search_document")
    asyncio.run(run())


def test_rejects_configured_dimension_mismatch(settings: GatewaySettings) -> None:
    async def run() -> None:
        transport = httpx.MockTransport(lambda request: embedding_response([[1.0, 2.0]]))
        async with create_gateway_client(settings, transport=transport) as client:
            with pytest.raises(GatewayContractError, match="embedding_dimension_mismatch"):
                await embed_texts(client, settings.model_copy(update={"embedding_dimension": 3}), ["a"], "search_query")
    asyncio.run(run())


@pytest.mark.parametrize("texts", [[], [""], ["  "]])
def test_rejects_empty_inputs_before_http(settings: GatewaySettings, texts: list[str]) -> None:
    async def run() -> None:
        def unexpected(request: httpx.Request) -> httpx.Response:
            pytest.fail("Não deveria chamar HTTP.")
        async with create_gateway_client(settings, transport=httpx.MockTransport(unexpected)) as client:
            with pytest.raises(ValueError, match="empty_embedding_input"):
                await embed_texts(client, settings, texts, "search_query")
    asyncio.run(run())


@pytest.mark.parametrize("model", CHAT_MODELS)
def test_stream_payload_incremental_parts_and_close(settings: GatewaySettings, model: str) -> None:
    stream = SimulatedSSE([
        chat_event(), chat_event("Olá, "), chat_event("ação!"),
        chat_event(reason="stop"), b'data: {"choices": [], "usage": {"total_tokens": 3}}\n\n', b"data: [DONE]\n\n",
    ])
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=stream)

    async def run() -> None:
        async with create_gateway_client(settings, transport=httpx.MockTransport(handle)) as client:
            async with open_chat_stream(client, settings, model, [{"role": "user", "content": "teste"}]) as parts:
                assert await anext(parts) == {"text": "Olá, ", "finish_reason": None}
                assert stream.sent == 2  # O restante do stream ainda não foi lido.
                assert [part async for part in parts] == [
                    {"text": "ação!", "finish_reason": None}, {"text": "", "finish_reason": "stop"},
                ]
            assert stream.closed
        assert client.is_closed()

    asyncio.run(run())
    assert len(requests) == 1
    assert str(requests[0].url) == "https://gateway.test/v1/chat/completions"
    assert json.loads(requests[0].content) == {
        "model": model, "messages": [{"role": "user", "content": "teste"}],
        "stream": True, "max_completion_tokens": 600,
    }


@pytest.mark.parametrize("mode", ["early_exit", "consumer_error", "cancelled", "provider_error", "missing_finish", "duplicate_finish"])
def test_stream_closes_on_interruption(settings: GatewaySettings, mode: str) -> None:
    chunks = [chat_event("início")]
    if mode == "duplicate_finish":
        chunks += [chat_event(reason="stop"), chat_event(reason="stop")]
    stream = SimulatedSSE(chunks, failure=RuntimeError("synthetic failure") if mode == "provider_error" else None)

    async def run() -> None:
        transport = httpx.MockTransport(lambda request: httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=stream))
        async with create_gateway_client(settings, transport=transport) as client:
            expected: type[BaseException] = {
                "consumer_error": RuntimeError, "cancelled": asyncio.CancelledError,
                "provider_error": RuntimeError, "missing_finish": GatewayContractError,
                "duplicate_finish": GatewayContractError,
            }.get(mode, Exception)

            async def consume() -> None:
                async with open_chat_stream(client, settings, CHAT_MODELS[0], [{"role": "user", "content": "teste"}]) as parts:
                    await anext(parts)
                    if mode == "early_exit":
                        return
                    if mode == "consumer_error":
                        raise RuntimeError("consumer")
                    if mode == "cancelled":
                        raise asyncio.CancelledError()
                    async for _ in parts:
                        pass

            if mode == "early_exit":
                await consume()
            else:
                with pytest.raises(expected):
                    await consume()
            assert stream.closed
    asyncio.run(run())


def test_invalid_model_rejected_before_http(settings: GatewaySettings) -> None:
    async def run() -> None:
        def unexpected(request: httpx.Request) -> httpx.Response:
            pytest.fail("Não deveria chamar HTTP.")
        async with create_gateway_client(settings, transport=httpx.MockTransport(unexpected)) as client:
            with pytest.raises(ValueError, match="model_not_allowed"):
                async with open_chat_stream(client, settings, "unknown", []):
                    pass
    asyncio.run(run())
