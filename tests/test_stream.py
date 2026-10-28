"""Contratos SSE em memória; a prova de entrega pela rede está em test_stream_http."""

import asyncio
import json
from contextlib import AsyncExitStack
from time import monotonic

import httpx
import pytest
from pydantic import ValidationError
from starlette.requests import ClientDisconnect, Request

import app.main as main
from app.config import ApiSettings, CHAT_MODELS, load_api_settings
from app.execution import QueryStreamingResponse
from app.schemas import ErrorDetail
from test_chat import api, gateway_case, hit, event, assert_no_services


def stream(api, body=None, headers=None):
    return api.client.post("/chat/stream", json=body or {"question": "Pergunta sintética?"},
                           headers=api.headers if headers is None else headers)


def events(response):
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["x-accel-buffering"] == "no"
    result = []
    assert response.text.endswith("\n\n")
    for frame in response.text.split("\n\n")[:-1]:
        name, data = frame.split("\n")
        assert name.startswith("event: ") and data.startswith("data: ")
        result.append((name[7:], json.loads(data[6:])))
    return result


@pytest.mark.parametrize("model", [None, *CHAT_MODELS])
def test_sources_deltas_done_models_and_same_json_flow(api, model):
    api.answer = 'Saúde: "atenção"\\apoio\n\nevent: error\r\n日本語 🧠 [S1]'
    body = {"question": "  Pergunta sintética?  "}
    if model:
        body["model"] = model
    response = stream(api, body)
    assert response.status_code == 200
    frames = events(response)
    assert [name for name, _ in frames] == ["sources", "delta", "delta", "done"]
    assert "".join(payload["text"] for name, payload in frames if name == "delta") == api.answer
    assert frames[0][1]["model"] == (model or CHAT_MODELS[0])
    assert frames[-1][1] == {"finish_reason": "stop"}
    assert api.calls[-1][1]["model"] == (model or CHAT_MODELS[0])
    response_json = api.client.post("/chat", json=body, headers=api.headers).json()
    assert frames[0][1]["sources"] == response_json["sources"]
    assert api.calls[1][1] == api.calls[3][1]
    assert main.app.state.query_slots._value == 2


def test_default_model_can_be_alternate(api):
    main.app.state.api_settings = ApiSettings(default_chat_model=CHAT_MODELS[1])
    assert events(stream(api))[0][1]["model"] == CHAT_MODELS[1]
    assert api.calls[-1][1]["model"] == CHAT_MODELS[1]


def test_no_context_local_delta_without_generation(api):
    api.search.return_value = []
    frames = events(stream(api))
    assert [name for name, _ in frames] == ["sources", "delta", "done"]
    assert frames[0][1]["sources"] == []
    assert "Não há trechos" in frames[1][1]["text"]
    assert frames[-1][1] == {"finish_reason": "insufficient_context"}
    assert [phase for phase, _ in api.calls] == ["embedding"]


@pytest.mark.parametrize("body", [
    {"question": " "}, {"question": "x" * 1501}, {"question": 4}, {},
    {"question": "ok", "model": "unknown"}, {"question": "ok", "model": 1},
    {"question": "ok", "top_k": 4},
])
def test_invalid_body_before_services(api, body):
    assert api.client.post("/chat/stream", json=body, headers=api.headers).status_code == 422
    assert_no_services(api)


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer wrong"}, {"Authorization": "Basic wrong"}])
def test_auth_before_services(api, headers):
    response = stream(api, headers=headers)
    assert response.status_code == 401 and response.headers["www-authenticate"] == "Bearer"
    assert_no_services(api)


@pytest.mark.parametrize("phase", ["embedding", "generation"])
@pytest.mark.parametrize("error,status", [(400, 502), (429, 503), (500, 503), (httpx.ReadTimeout("PRIVATE"), 504)])
def test_http_errors_before_sse_headers(api, phase, error, status):
    api.fail_phase, api.error = phase, error
    response = stream(api)
    assert response.status_code == status
    assert response.headers["content-type"].startswith("application/json")
    assert "PRIVATE" not in response.text
    assert main.app.state.query_slots._value == 2


@pytest.mark.parametrize("stage", ["ready", "search"])
def test_base_error_before_headers(api, stage):
    getattr(api, stage).side_effect = RuntimeError("PRIVATE BASE")
    response = stream(api)
    assert response.status_code == 503 and "PRIVATE" not in response.text


@pytest.mark.parametrize("reason", ["stop", "length", "tool_calls", "content_filter"])
def test_finish_reasons(api, reason):
    api.reason = reason
    response = stream(api)
    assert response.status_code == 200
    frames = events(response)
    if reason in {"stop", "length"}:
        assert frames[-1] == ("done", {"finish_reason": reason})
    else:
        assert frames[-1][0] == "error"
        assert not any(name == "done" for name, _ in frames)
    assert main.app.state.query_slots._value == 2


@pytest.mark.parametrize("failure", ["read", "invalid_json", "invalid_delta", "missing_finish", "empty"])
def test_read_failures_terminal_error_no_done(api, failure):
    if failure == "read":
        api.stream_failure = httpx.ReadError("PRIVATE CONNECTION")
    elif failure == "invalid_json":
        api.invalid_json = "generation"
    elif failure == "invalid_delta":
        api.invalid_delta = True
    elif failure == "missing_finish":
        api.malformed = True
    else:
        api.answer = "  "
    response = stream(api)
    assert response.status_code == 200
    frames = events(response)
    assert frames[0][0] == "sources" and frames[-1][0] == "error"
    assert set(frames[-1][1]) == {"code", "message", "request_id"}
    assert frames[-1][1]["request_id"] == frames[0][1]["request_id"]
    assert "PRIVATE" not in json.dumps(frames[-1][1])
    assert "done" not in [name for name, _ in frames]
    assert len(api.calls) == 2  # Nunca reinicia a geração.
    assert main.app.state.query_slots._value == 2
    if failure == "read":
        assert api.stream_closed


def test_empty_provider_fragments_are_not_deltas(api):
    class EmptyParts(httpx.AsyncByteStream):
        async def __aiter__(self):
            for part in [event(""), event(None), event("texto"), event(""), event(None, "stop")]:
                yield part
    api.stream_factory = EmptyParts
    assert [name for name, _ in events(stream(api))] == ["sources", "delta", "done"]


@pytest.mark.parametrize("route", ["/chat", "/chat/stream"])
@pytest.mark.parametrize("stage", ["ready", "embedding", "search", "opening"])
def test_timeout_before_headers_all_stages(api, route, stage):
    main.app.state.api_settings = ApiSettings(request_timeout_seconds=0.02)
    async def delayed(*args):
        await asyncio.sleep(0.1)
        return [hit()] if stage == "search" else None
    if stage in {"ready", "search"}:
        getattr(api, stage).side_effect = delayed
    else:
        api.delay = "embedding" if stage == "embedding" else "generation"
    response = api.client.post(route, json={"question": "ok"}, headers=api.headers)
    assert response.status_code == 504 and main.app.state.query_slots._value == 2


@pytest.mark.parametrize("route", ["/chat", "/chat/stream"])
def test_total_deadline_is_not_restarted_between_stages(api, route):
    main.app.state.api_settings = ApiSettings(request_timeout_seconds=0.08)
    async def ready(*args):
        await asyncio.sleep(0.05)
    async def search(*args):
        await asyncio.sleep(0.05)
        return [hit()]
    api.ready.side_effect, api.search.side_effect = ready, search
    response = api.client.post(route, json={"question": "ok"}, headers=api.headers)
    assert response.status_code == 504
    assert [phase for phase, _ in api.calls] == ["embedding"]
    assert main.app.state.query_slots._value == 2


@pytest.mark.parametrize("route", ["/chat", "/chat/stream"])
def test_timeout_during_read_closes_stream(api, route):
    main.app.state.api_settings = ApiSettings(request_timeout_seconds=0.03)
    class Waiting(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield event("primeiro")
            await asyncio.sleep(1)
            yield event("último", "stop")
        async def aclose(self):
            await asyncio.sleep(0)
            api.stream_closed = True
    api.stream_factory = Waiting
    response = api.client.post(route, json={"question": "ok"}, headers=api.headers)
    if route == "/chat":
        assert response.status_code == 504
    else:
        assert response.status_code == 200
        frames = events(response)
        assert [name for name, _ in frames] == ["sources", "delta", "error"]
        assert frames[-1][1]["code"] == "gateway_timeout"
    assert api.stream_closed and main.app.state.query_slots._value == 2


@pytest.mark.parametrize("name,value", [
    ("REQUEST_TIMEOUT_SECONDS", "0"), ("REQUEST_TIMEOUT_SECONDS", "nan"),
    ("REQUEST_TIMEOUT_SECONDS", "inf"), ("MAX_CONCURRENT_REQUESTS", "0"),
    ("MAX_CONCURRENT_REQUESTS", "1.5"), ("MAX_CONCURRENT_REQUESTS", "private"),
])
def test_invalid_execution_configuration(name, value):
    with pytest.raises(ValidationError):
        load_api_settings({name: value})


def test_execution_defaults_and_environment():
    settings = load_api_settings({})
    assert settings.request_timeout_seconds == 90 and settings.max_concurrent_requests == 2
    settings = load_api_settings({"REQUEST_TIMEOUT_SECONDS": "1.5", "MAX_CONCURRENT_REQUESTS": "3"})
    assert settings.request_timeout_seconds == 1.5 and settings.max_concurrent_requests == 3


def test_stream_openapi(api):
    schema = api.client.get("/openapi.json").json()
    route = schema["paths"]["/chat/stream"]["post"]
    assert route["security"] == [{"HTTPBearer": []}]
    assert {"200", "401", "422", "429", "502", "503", "504"} <= route["responses"].keys()
    assert set(route["responses"]["200"]["content"]) == {"text/event-stream"}
    assert "429" in schema["paths"]["/chat"]["post"]["responses"]
    assert_no_services(api)


@pytest.mark.parametrize("spec", ["2.3", "2.4"])
def test_response_disconnect_before_iterator_starts_releases_resources(spec):
    async def run():
        closed = []
        stack = AsyncExitStack()
        stack.callback(lambda: closed.append(True))
        async def body():
            yield "never sent"
        response = QueryStreamingResponse(body(), stack, monotonic() + 2,
            lambda e: ErrorDetail(code="test", message="public", request_id="test"))
        async def receive():
            return {"type": "http.disconnect"}
        async def send(message):
            await asyncio.sleep(2)
        await response({"type": "http", "asgi": {"spec_version": spec}}, receive, send)
        assert closed == [True]
    asyncio.run(run())


@pytest.mark.parametrize("route", ["/chat", "/chat/stream"])
def test_provider_close_failure_releases_capacity_and_is_public(api, route, caplog):
    class FailsOnClose(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield event("texto", "stop")
        async def aclose(self):
            raise RuntimeError("PRIVATE CLOSE DETAIL")
    api.stream_factory = FailsOnClose
    response = api.client.post(route, json={"question": "ok"}, headers=api.headers)
    if route == "/chat":
        assert response.status_code == 502
    else:
        frames = events(response)
        assert frames[-1][0] == "error" and "done" not in [name for name, _ in frames]
    assert "PRIVATE" not in response.text and "PRIVATE" not in caplog.text
    assert main.app.state.query_slots._value == 2


@pytest.mark.parametrize("failure", ["cancel", "send", "timeout_send"])
def test_response_cleans_resources_when_send_is_interrupted(failure):
    async def run():
        closed, frames = [], []
        stack = AsyncExitStack()
        async def close():
            await asyncio.sleep(0)
            closed.append(True)
        stack.push_async_callback(close)
        async def body():
            yield 'event: delta\ndata: {"text":"texto"}\n\n'
        response = QueryStreamingResponse(body(), stack, asyncio.get_running_loop().time() + 0.02,
            lambda e: ErrorDetail(code="timeout", message="public", request_id="test"))
        async def receive():
            await asyncio.sleep(10)
        async def send(message):
            frames.append(message)
            if message["type"] == "http.response.body" and message.get("body", b"").startswith(b"event: delta"):
                if failure == "send":
                    raise OSError("PRIVATE WRITE")
                await asyncio.sleep(10)
        task = asyncio.create_task(response({"type": "http", "asgi": {"spec_version": "2.4"}}, receive, send))
        if failure == "cancel":
            await asyncio.sleep(0.005)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            await task
        assert closed == [True]
        if failure == "timeout_send":
            assert any(m.get("body", b"").startswith(b"event: error") for m in frames)
    asyncio.run(run())


def test_stream_logs_only_metadata(api, caplog):
    import logging
    caplog.set_level(logging.INFO, logger="app")
    api.answer = "PRIVATE GENERATED TEXT"
    api.search.return_value = [hit("PRIVATE DOCUMENT")]
    response = stream(api, {"question": "PRIVATE QUESTION"})
    assert response.status_code == 200
    assert "PRIVATE" not in caplog.text
    assert "synthetic-access" not in caplog.text and "synthetic-gateway" not in caplog.text
    assert events(response)[0][1]["request_id"] in caplog.text


def test_timeout_after_done_finishes_http_without_second_terminal():
    async def run():
        frames, empty_attempts = [], 0
        async def body():
            yield 'event: done\ndata: {"finish_reason":"stop"}\n\n'
        async def receive():
            await asyncio.sleep(10)
        async def send(message):
            nonlocal empty_attempts
            if message["type"] == "http.response.body" and not message.get("more_body", False):
                empty_attempts += 1
                if empty_attempts == 1:
                    await asyncio.sleep(10)
            frames.append(message)
        response = QueryStreamingResponse(body(), AsyncExitStack(), asyncio.get_running_loop().time() + 0.02,
            lambda e: ErrorDetail(code="timeout", message="public", request_id="test"))
        await response({"type": "http", "asgi": {"spec_version": "2.4"}}, receive, send)
        assert sum(m.get("body", b"").startswith(b"event: done") for m in frames) == 1
        assert not any(m.get("body", b"").startswith(b"event: error") for m in frames)
        assert frames[-1] == {"type": "http.response.body", "body": b"", "more_body": False}
    asyncio.run(run())
