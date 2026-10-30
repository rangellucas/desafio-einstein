"""Entrega pública da demonstração, sem modelos nem configuração real."""

from pathlib import Path
from unittest.mock import Mock

from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.config import ApiSettings
from app.main import app


def test_demo_is_public_module_relative_and_does_not_call_models(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("app.main.load_api_settings", lambda: ApiSettings(
        access_token=SecretStr("synthetic-demo-access"),
    ))
    gateway = Mock(side_effect=AssertionError("A página não deve criar o gateway."))
    monkeypatch.setattr("app.main.create_gateway_client", gateway)
    expected = (Path(__file__).resolve().parents[1] / "app/static/demo.html").read_bytes()
    with TestClient(app) as client:
        monkeypatch.chdir(tmp_path)
        response = client.get("/teste")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/html")
        assert response.content == expected
        assert '<html lang="pt-BR">' in response.text
        assert 'id="token" type="password"' in response.text
        assert "/teste" not in client.get("/openapi.json").json()["paths"]
        # A rota pública não enfraquece a autenticação da consulta.
        assert client.post("/chat/stream", json={"question": "Sintética?"}).status_code == 401
    gateway.assert_not_called()
