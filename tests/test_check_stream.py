import json
from types import SimpleNamespace

import httpx
import pytest

from scripts.check_stream import StreamCheckError, check_stream, main


def frame(name, payload):
    return f"event: {name}\ndata: {json.dumps(payload)}\n\n"


SOURCES = frame("sources", {"request_id": "test", "model": "azure/gpt-5-mini", "sources": []})
DELTA = frame("delta", {"text": 'Saúde "mental"\n 🧠'})
DONE = frame("done", {"finish_reason": "insufficient_context"})


def test_plan_does_not_read_credentials_or_open_http(monkeypatch, capsys):
    def forbidden(*args, **kwargs):
        raise AssertionError("I/O proibido no plano")
    monkeypatch.setattr("scripts.check_stream.os", SimpleNamespace(environ=SimpleNamespace(get=forbidden)))
    monkeypatch.setattr(httpx, "Client", forbidden)
    assert main([]) == 0
    assert "Nenhuma chamada executada" in capsys.readouterr().out


def test_check_records_event_times_and_no_sensitive_payloads():
    calls, output = [], []
    def handler(request):
        calls.append(request)
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, text=SOURCES + DELTA + DONE)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = check_stream(client, "http://api.test", "PRIVATE QUESTION", token="synthetic-only", report=output.append)
    assert result["delta_before_done"] and result["events"] == ["sources", "delta", "done"]
    assert len(calls) == 1 and calls[0].url.path == "/chat/stream"
    assert calls[0].headers["authorization"] == "Bearer synthetic-only"
    assert "PRIVATE" not in " ".join(output) and "Saúde" not in " ".join(output)


@pytest.mark.parametrize("content,code", [
    (DELTA + DONE, "invalid_event_order"),
    (SOURCES + frame("delta", {"text": ""}) + DONE, "empty_delta"),
    (SOURCES + DELTA, "incomplete_stream"),
    (SOURCES + DELTA + DONE + DELTA, "event_after_terminal"),
    (SOURCES + "event: delta\ndata: PRIVATE invalid\n\n", "invalid_event_payload"),
    (SOURCES + frame("error", {"code": "test", "message": "PRIVATE", "request_id": "test"}), "sse_error"),
])
def test_malformed_or_failed_stream_is_rejected(content, code):
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(
        200, headers={"content-type": "text/event-stream"}, text=content,
    ))) as client:
        with pytest.raises(StreamCheckError, match=code):
            check_stream(client, "http://api.test", "test", report=lambda _: None)


@pytest.mark.parametrize("status,content_type,code", [
    (401, "application/json", "http_status_401"),
    (200, "application/json", "invalid_content_type"),
])
def test_http_failure_is_sanitized(status, content_type, code):
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(
        status, headers={"content-type": content_type}, text="PRIVATE BODY",
    ))) as client:
        with pytest.raises(StreamCheckError, match=code):
            check_stream(client, "http://api.test", "test", report=lambda _: None)
