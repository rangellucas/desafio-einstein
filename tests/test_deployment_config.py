import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.config import load_api_settings


@pytest.mark.parametrize("token", [None, "", "   "])
def test_render_missing_token_fails_before_opening_clients(monkeypatch, token):
    env = {"RENDER": "true"}
    if token is not None:
        env["API_ACCESS_TOKEN"] = token
    monkeypatch.setattr(main, "load_api_settings", lambda: load_api_settings(env))

    def unexpected():
        pytest.fail("Não abrir clientes com autenticação ausente no Render")

    monkeypatch.setattr(main, "load_vector_settings", unexpected)
    monkeypatch.setattr(main, "load_gateway_settings", unexpected)
    with pytest.raises(ValueError, match="API_ACCESS_TOKEN"):
        with TestClient(main.app):
            pass


def test_render_protects_both_query_routes_and_keeps_public_docs(monkeypatch):
    monkeypatch.setattr(main, "load_api_settings", lambda: load_api_settings({
        "RENDER": "true", "API_ACCESS_TOKEN": "synthetic-deployment-token",
    }))
    with TestClient(main.app) as client:
        for route in ("/chat", "/chat/stream"):
            assert client.post(route, json={"question": "Pergunta sintética"}).status_code == 401
            assert client.post(route, json={"question": "Pergunta", "model": "invalid"},
                               headers={"Authorization": "Bearer synthetic-deployment-token"}).status_code == 422
        for route in ("/health", "/models", "/docs", "/openapi.json"):
            assert client.get(route).status_code == 200
        assert client.get("/ready").status_code == 503


def test_local_development_still_accepts_no_token():
    assert load_api_settings({}).access_token is None
