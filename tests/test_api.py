from fastapi.testclient import TestClient

from app.main import app
from app.config import VectorSettings


def test_health_and_docs_without_external_services(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("app.main.load_vector_settings", lambda: VectorSettings(
        path=tmp_path / "unindexed", collection="synthetic", dimension=2,
    ))
    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
        docs = client.get("/docs")
        assert docs.status_code == 200
        assert "text/html" in docs.headers["content-type"]
        schema = client.get("/openapi.json").json()
        assert set(schema["paths"]) == {"/health", "/ready"}
