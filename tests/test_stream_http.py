"""HTTP real em loopback + Uvicorn; gateway/Qdrant continuam substituídos."""

import asyncio
import json
import socket
import threading
from time import monotonic, sleep

import httpx
import pytest
import uvicorn

import app.main as main
from app.config import ApiSettings
from scripts.check_stream import check_stream
from test_chat import gateway_case, event


class ControlledStream(httpx.AsyncByteStream):
    def __init__(self, case):
        self.gate = asyncio.Event()
        self.started = threading.Event()
        self.completed = threading.Event()
        self.closed = threading.Event()
        case.current = self

    async def __aiter__(self):
        self.started.set()
        yield event('Primeiro: saúde "mental"\n [S1]')
        await self.gate.wait()
        yield event(" Segundo.")
        yield event(None, "stop")
        self.completed.set()

    async def aclose(self):
        await asyncio.sleep(0)  # Confirma que o fechamento assíncrono é aguardado.
        self.closed.set()


@pytest.fixture
def live_api(gateway_case, loopback_network):
    case = gateway_case
    case.api_settings = ApiSettings(max_concurrent_requests=1, request_timeout_seconds=3)
    case.stream_factory = lambda: ControlledStream(case)
    case.headers = {"Authorization": "Bearer synthetic-access-only"}
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    case.port = listener.getsockname()[1]
    case.url = f"http://127.0.0.1:{case.port}"
    server = uvicorn.Server(uvicorn.Config(main.app, host="127.0.0.1", log_level="critical", access_log=False))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()
    try:
        deadline = monotonic() + 5
        while not server.started and thread.is_alive() and monotonic() < deadline:
            sleep(0.01)
        assert server.started, "Uvicorn não iniciou"
        yield case
    finally:
        server.should_exit = True
        thread.join(timeout=6)
        listener.close()
        assert not thread.is_alive(), "Uvicorn deve encerrar sem tarefas órfãs"


def read_event(lines):
    name = next(lines)
    data = next(lines)
    assert next(lines) == ""
    return name.removeprefix("event: "), json.loads(data.removeprefix("data: "))


def raw_query(case, route):
    connection = socket.create_connection(("127.0.0.1", case.port), timeout=2)
    body = b'{"question":"Pergunta sintetica?"}'
    request = (
        f"POST {route} HTTP/1.1\r\nHost: 127.0.0.1\r\n"
        "Authorization: Bearer synthetic-access-only\r\nContent-Type: application/json\r\n"
        f"Content-Length: {len(body)}\r\n\r\n"
    ).encode() + body
    connection.sendall(request)
    return connection


def wait_current(case):
    deadline = monotonic() + 2
    while not hasattr(case, "current") and monotonic() < deadline:
        sleep(0.005)
    assert case.current.started.wait(timeout=2)
    return case.current


def assert_available_again(case, client):
    case.stream_factory = None
    response = client.post(case.url + "/chat", json={"question": "Outra?"}, headers=case.headers)
    assert response.status_code == 200
    assert main.app.state.query_slots._value == 1


def test_delta_arrives_over_http_before_generation_finishes(live_api):
    case = live_api
    start = monotonic()
    with httpx.Client(timeout=2, trust_env=False) as client:
        with client.stream("POST", case.url + "/chat/stream", json={"question": "Sintética?"}, headers=case.headers) as response:
            assert response.status_code == 200
            lines = response.iter_lines()
            sources = read_event(lines)
            first = read_event(lines)
            first_at = monotonic() - start
            assert sources[0] == "sources" and first[0] == "delta"
            assert first[1]["text"] == 'Primeiro: saúde "mental"\n [S1]'
            assert not case.current.completed.is_set()
            assert not case.current.closed.is_set()
            assert not case.current.gate.is_set()
            # Intervalo controlado depois do recebimento real do primeiro delta.
            sleep(0.08)
            case.loop.call_soon_threadsafe(case.current.gate.set)
            assert read_event(lines) == ("delta", {"text": " Segundo."})
            assert read_event(lines) == ("done", {"finish_reason": "stop"})
            done_at = monotonic() - start
            assert list(lines) == []
        assert case.current.completed.is_set() and case.current.closed.is_set()
        assert done_at - first_at >= 0.08
        print(f"HTTP real: primeiro delta +{first_at:.3f}s; done +{done_at:.3f}s; geração bloqueada ao receber primeiro delta.")
        assert_available_again(case, client)


@pytest.mark.parametrize("owner", ["/chat", "/chat/stream"])
def test_shared_capacity_rejects_both_routes_before_external_calls_and_disconnect_releases(live_api, owner):
    case = live_api
    connection = raw_query(case, owner)
    try:
        current = wait_current(case)
        count = len(case.calls)
        with httpx.Client(timeout=2, trust_env=False) as client:
            for route in ("/chat", "/chat/stream"):
                response = client.post(case.url + route, json={"question": "Outra?"}, headers=case.headers)
                assert response.status_code == 429
                assert response.json()["detail"]["code"] == "capacity_exceeded"
                assert len(case.calls) == count
            assert case.ready.await_count == 1 and case.search.await_count == 1
            connection.close()
            assert current.closed.wait(timeout=2)
            assert not current.completed.is_set()
            # closed ocorre antes do callback de vaga; aguarda o ciclo concluir.
            deadline = monotonic() + 2
            while main.app.state.query_slots.locked() and monotonic() < deadline:
                sleep(0.005)
            assert_available_again(case, client)
    finally:
        connection.close()


@pytest.mark.parametrize("route", ["/chat", "/chat/stream"])
@pytest.mark.parametrize("phase", ["ready", "embedding", "search", "opening"])
def test_disconnect_before_headers_cancels_preparation(live_api, route, phase):
    case = live_api
    entered, cancelled = threading.Event(), threading.Event()
    async def block(*args, **kwargs):
        entered.set()
        try:
            await asyncio.sleep(10)
        finally:
            cancelled.set()
    if phase in {"ready", "search"}:
        getattr(case, phase).side_effect = block
    from unittest.mock import patch
    target = {"embedding": "app.rag.embed_texts", "opening": "app.rag.open_chat_stream"}.get(phase)
    if phase == "opening":
        # O contexto substituto bloqueia na abertura, antes de produzir iterador.
        from contextlib import asynccontextmanager
        @asynccontextmanager
        async def opening(*args, **kwargs):
            await block()
            yield None
        replacement = opening
    else:
        replacement = block
    from contextlib import nullcontext
    with patch(target, replacement) if target else nullcontext():
        connection = raw_query(case, route)
        try:
            assert entered.wait(timeout=2)
            connection.close()
            assert cancelled.wait(timeout=2)
            deadline = monotonic() + 2
            while main.app.state.query_slots.locked() and monotonic() < deadline:
                sleep(0.005)
            assert not main.app.state.query_slots.locked()
            assert not hasattr(case, "current")
        finally:
            connection.close()


def test_verification_client_consumes_real_http_and_reports_times_without_content(live_api):
    case = live_api
    output = []
    def report(line):
        output.append(line)
        if "event=delta" in line and not case.current.gate.is_set():
            assert not case.current.completed.is_set()
            case.loop.call_soon_threadsafe(case.current.gate.set)
    with httpx.Client(timeout=2, trust_env=False) as client:
        result = check_stream(client, case.url, "PRIVATE QUESTION", token="synthetic-access-only", report=report)
    assert result["events"] == ["sources", "delta", "delta", "done"]
    assert result["delta_before_done"]
    assert result["first_delta_seconds"] < result["terminal_seconds"]
    assert all("PRIVATE" not in line and "Primeiro" not in line and "synthetic-access" not in line for line in output)


@pytest.mark.parametrize("route", ["/chat", "/chat/stream"])
def test_total_timeout_over_http_closes_provider_and_releases_capacity(live_api, route):
    case = live_api
    main.app.state.api_settings = ApiSettings(max_concurrent_requests=1, request_timeout_seconds=0.12)
    async def ready(*args):
        await asyncio.sleep(0.04)
    case.ready.side_effect = ready
    with httpx.Client(timeout=2, trust_env=False) as client:
        start = monotonic()
        response = client.post(case.url + route, json={"question": "Sintética?"}, headers=case.headers)
        elapsed = monotonic() - start
        assert case.current.closed.is_set() and not case.current.completed.is_set()
        assert elapsed < 1
        if route == "/chat":
            assert response.status_code == 504
        else:
            assert response.status_code == 200
            assert 'event: delta\n' in response.text and 'event: error\n' in response.text
            assert '"code":"gateway_timeout"' in response.text and "event: done" not in response.text
        assert_available_again(case, client)
