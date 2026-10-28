import asyncio
import json

import httpx
import pytest

from app.config import GatewaySettings, load_gateway_settings
from app.gateway import create_gateway_client
from scripts import check_gateway as command
from test_gateway import SimulatedSSE, chat_event, embedding_response


def config() -> GatewaySettings:
    return load_gateway_settings({"LLM_BASE_URL": "https://gateway.test/v1", "LLM_API_KEY": "synthetic-test-only"})


def success_response(request: httpx.Request) -> httpx.Response:
    if request.url.path.endswith("/embeddings"):
        return embedding_response([[1.0, 0.2, 0.3]])
    return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=SimulatedSSE([
        chat_event("texto sintético privado"), chat_event(" restante"), chat_event(reason="stop"), b"data: [DONE]\n\n",
    ]))


def test_plan_never_loads_settings_or_creates_client(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    def forbidden(*args: object) -> None:
        pytest.fail("Plano não pode carregar credenciais nem construir cliente.")
    monkeypatch.setattr(command, "load_gateway_settings", forbidden)
    monkeypatch.setattr(command, "create_gateway_client", forbidden)
    assert command.main([]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["mode"] == "plan"
    assert len(report["calls"]) == report["max_calls"] == 4


def test_simulated_cli_success_four_calls_and_no_content(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    requests: list[httpx.Request] = []
    clients = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return success_response(request)

    def factory(settings: GatewaySettings):
        client = create_gateway_client(settings, transport=httpx.MockTransport(handle))
        clients.append(client)
        return client

    monkeypatch.setattr(command, "load_gateway_settings", config)
    monkeypatch.setattr(command, "create_gateway_client", factory)
    assert command.main(["--execute"]) == 0
    output = capsys.readouterr().out
    report = json.loads(output)
    assert report["calls_attempted"] == len(requests) == 4
    assert report["status"] == "passed"
    assert report["output_limit"] == 600
    assert [check.get("dimension") for check in report["checks"][:2]] == [3, 3]
    assert [json.loads(request.content).get("input_type") for request in requests[:2]] == ["search_document", "search_query"]
    assert [json.loads(request.content)["model"] for request in requests[2:]] == ["azure/gpt-5-mini", "azure/gpt-6-luna"]
    assert all(client.is_closed() for client in clients)
    assert "texto sintético privado" not in output
    assert "synthetic-test-only" not in output
    assert "[1.0, 0.2, 0.3]" not in output


@pytest.mark.parametrize("status", [301, 400, 401, 404, 429, 500, 503])
def test_http_failure_stops_without_retry_or_redirect(status: int) -> None:
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(status, headers={"location": "https://other.test/"}, json={"error": {"message": "PRIVATE provider details"}})

    async def run() -> None:
        settings = config()
        async with create_gateway_client(settings, transport=httpx.MockTransport(handle)) as client:
            report = await command.check_gateway(client, settings)
        assert report["error"] == f"gateway_http_{status}"
        assert report["status"] == "failed"
        assert report["calls_attempted"] == len(requests) == 1
        assert "PRIVATE" not in json.dumps(report)
    asyncio.run(run())


def test_document_and_query_dimensions_must_match() -> None:
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return embedding_response([[1.0] if len(requests) == 1 else [1.0, 2.0]])

    async def run() -> None:
        settings = config()
        async with create_gateway_client(settings, transport=httpx.MockTransport(handle)) as client:
            report = await command.check_gateway(client, settings)
        assert report["error"] == "embedding_dimension_mismatch_between_input_types"
        assert report["calls_attempted"] == len(requests) == 2
        assert [check["dimension"] for check in report["checks"]] == [1, 2]
    asyncio.run(run())


@pytest.mark.parametrize("kind", ["empty", "length", "missing_finish", "bad_json", "provider_error"])
def test_bad_stream_stops_before_second_model(kind: str) -> None:
    streams: list[SimulatedSSE] = []
    count = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal count
        count += 1
        if request.url.path.endswith("/embeddings"):
            return success_response(request)
        chunks = {
            "empty": [chat_event(reason="stop")],
            "length": [chat_event("incompleto", "length")],
            "missing_finish": [chat_event("incompleto")],
            "bad_json": [b"data: invalid-json\n\n"],
            "provider_error": [b'data: {"error": {"message": "PRIVATE"}}\n\n'],
        }[kind]
        stream = SimulatedSSE(chunks + [b"data: [DONE]\n\n"])
        streams.append(stream)
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=stream)

    async def run() -> None:
        settings = config()
        async with create_gateway_client(settings, transport=httpx.MockTransport(handle)) as client:
            report = await command.check_gateway(client, settings)
        assert report["status"] == "failed"
        assert report["calls_attempted"] == count == 3
        assert all(stream.closed for stream in streams)
        assert "PRIVATE" not in json.dumps(report)
    asyncio.run(run())


@pytest.mark.parametrize("failure", [httpx.ReadTimeout("PRIVATE"), httpx.ConnectError("PRIVATE")])
def test_connection_and_timeout_failures_are_sanitized(failure: Exception) -> None:
    attempts = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise failure

    async def run() -> None:
        settings = config()
        async with create_gateway_client(settings, transport=httpx.MockTransport(handle)) as client:
            report = await command.check_gateway(client, settings)
        assert attempts == report["calls_attempted"] == 1
        assert report["error"] in {"gateway_timeout", "gateway_connection_failed"}
        assert "PRIVATE" not in json.dumps(report)
    asyncio.run(run())


def test_total_stream_timeout_closes_resources() -> None:
    class WaitingSSE(SimulatedSSE):
        async def __aiter__(self):
            yield chat_event("começo")
            await asyncio.Event().wait()

    stream = WaitingSSE([])

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/embeddings"):
            return success_response(request)
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=stream)

    async def run() -> None:
        settings = config().model_copy(update={"request_timeout_seconds": 0.05})
        async with create_gateway_client(settings, transport=httpx.MockTransport(handle)) as client:
            report = await command.check_gateway(client, settings)
        assert report["error"] == "gateway_timeout"
        assert report["calls_attempted"] == 3
        assert stream.closed
        assert client.is_closed()
    asyncio.run(run())


@pytest.mark.parametrize("failure", [httpx.ReadTimeout("PRIVATE"), httpx.ReadError("PRIVATE")])
def test_http_failure_during_stream_is_sanitized_and_closes(failure: Exception) -> None:
    stream = SimulatedSSE([chat_event("início")], failure=failure)

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/embeddings"):
            return success_response(request)
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=stream)

    async def run() -> None:
        settings = config()
        async with create_gateway_client(settings, transport=httpx.MockTransport(handle)) as client:
            report = await command.check_gateway(client, settings)
        assert report["status"] == "failed"
        assert report["calls_attempted"] == 3
        assert report["error"] in {"gateway_timeout", "gateway_connection_failed"}
        assert "PRIVATE" not in json.dumps(report)
        assert stream.closed
    asyncio.run(run())


def test_verification_caps_output_and_cli_failure_exit(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    limits: list[int] = []

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/embeddings"):
            return success_response(request)
        limits.append(json.loads(request.content)["max_completion_tokens"])
        return httpx.Response(400, json={"error": {"message": "PRIVATE"}})

    settings = config().model_copy(update={"max_output_tokens": 1000})
    monkeypatch.setattr(command, "load_gateway_settings", lambda: settings)
    monkeypatch.setattr(command, "create_gateway_client", lambda settings: create_gateway_client(settings, transport=httpx.MockTransport(handle)))
    assert command.main(["--execute"]) == 1
    assert limits == [600]
    output = capsys.readouterr().out
    assert json.loads(output)["calls_attempted"] == 3
    assert "PRIVATE" not in output


def test_invalid_config_cli_exits_before_client(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    monkeypatch.setattr(command, "load_gateway_settings", lambda: load_gateway_settings({}))
    monkeypatch.setattr(command, "create_gateway_client", lambda *args: pytest.fail("Não deveria criar cliente."))
    assert command.main(["--execute"]) == 2
    report = json.loads(capsys.readouterr().out)
    assert report["calls_attempted"] == 0
    assert report["invalid_variables"] == ["LLM_API_KEY", "LLM_BASE_URL"]
