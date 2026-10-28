from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

import app.main as module
from app.config import VectorSettings


@pytest.fixture(autouse=True)
def isolate_config(monkeypatch):
    def no_config():
        raise ValueError("Synthetic unconfigured environment")
    monkeypatch.setattr(module, "load_vector_settings", no_config)


def test_ready_without_configuration_keeps_health_available():
    with TestClient(module.app) as client:
        response = client.get("/ready")
        assert response.status_code == 503
        assert set(response.json()["detail"]) == {"code", "message", "request_id"}
        assert response.json()["detail"]["code"] == "base_unavailable"
        assert client.get("/health").status_code == 200


@pytest.mark.parametrize("failure", [False, True])
def test_ready_uses_shared_client_and_closes_it(tmp_path, monkeypatch, failure):
    settings = VectorSettings(path=tmp_path, collection="synthetic", dimension=2)
    store = AsyncMock()
    check = AsyncMock(side_effect=RuntimeError("PRIVATE URL AND KEY") if failure else None)
    monkeypatch.setattr(module, "load_vector_settings", lambda: settings)
    monkeypatch.setattr(module, "create_vector_client", lambda s: store)
    monkeypatch.setattr(module, "check_ready", check)
    with TestClient(module.app) as client:
        for _ in range(2):
            response = client.get("/ready")
            assert response.status_code == (503 if failure else 200)
            assert "PRIVATE" not in response.text
        assert client.get("/health").json() == {"status": "ok"}
    assert check.await_count == 2
    store.close.assert_awaited_once()


def test_store_initialization_failure_does_not_leak_or_break_health(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "load_vector_settings", lambda: VectorSettings(path=tmp_path, collection="test", dimension=2))
    def fail(settings):
        raise RuntimeError("PRIVATE LOCK PATH")
    monkeypatch.setattr(module, "create_vector_client", fail)
    with TestClient(module.app) as client:
        assert client.get("/health").status_code == 200
        response = client.get("/ready")
        assert response.status_code == 503 and "PRIVATE" not in response.text
