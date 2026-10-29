import asyncio
import json
from unittest.mock import AsyncMock

import pytest
from qdrant_client import AsyncQdrantClient, models

from app.config import VectorSettings, EXPECTED_DOCUMENTS, EMBEDDING_MODEL, PIPELINE_VERSION
from app.vector_store import BaseUnavailable, collection_contract
from scripts import transfer_vectors as module


async def seed(client, settings):
    manifest = [{"document_name": name, "document_hash": "a" * 64, "chunks": 1}
                for name in EXPECTED_DOCUMENTS]
    await client.create_collection(
        settings.collection, vectors_config=models.VectorParams(size=2, distance=models.Distance.COSINE),
        metadata={"rag_contract": collection_contract(settings), "documents": manifest},
    )
    await client.upsert(settings.collection, wait=True, points=[
        models.PointStruct(id=i, vector=[0.6, 0.8], payload={
            "chunk_id": str(i), "document_name": name, "document_hash": "a" * 64,
            "page": 1, "text": "Conteúdo sintético privado.",
            "pipeline_version": PIPELINE_VERSION, "embedding_model": EMBEDDING_MODEL,
        }) for i, name in enumerate(EXPECTED_DOCUMENTS)
    ])


@pytest.mark.parametrize("mode", ["copy", "reuse", "verify", "partial", "changed", "missing", "write_failure"])
def test_copy_readback_and_collisions_preserve_existing_collections(tmp_path, mode):
    async def run():
        local = VectorSettings(path=tmp_path / "source", collection="synthetic_v1", dimension=2)
        remote = VectorSettings(path=tmp_path / "target", collection=local.collection, dimension=2)
        source = AsyncQdrantClient(path=str(local.path))
        target = AsyncQdrantClient(path=str(remote.path))
        try:
            await seed(source, local)
            if mode in {"reuse", "verify", "partial", "changed"}:
                await seed(target, remote)
            if mode == "partial":
                await target.delete(remote.collection, points_selector=models.PointIdsList(points=[0]))
            if mode == "changed":
                await target.set_payload(remote.collection, points=[0], payload={"text": "Outro texto"})
            before = await module.read_points(target, remote) if mode in {"reuse", "verify", "partial", "changed"} else None
            if mode == "write_failure":
                target.upsert = AsyncMock(side_effect=RuntimeError("PRIVATE KEY URL"))
            if mode in {"partial", "changed", "missing", "write_failure"}:
                with pytest.raises((BaseUnavailable, RuntimeError)):
                    await module.transfer_vectors(source, local, target, remote, verify_only=mode == "missing")
                if before is not None:
                    assert module.same_points(before, await module.read_points(target, remote))
                if mode == "write_failure":
                    # A repetição não escreve nem apaga a nova coleção parcial.
                    with pytest.raises(BaseUnavailable):
                        await module.transfer_vectors(source, local, target, remote)
                    assert target.upsert.await_count == 1
                return
            report = await module.transfer_vectors(source, local, target, remote, verify_only=mode == "verify")
            assert report == {"status": "verified", "points": 4, "written": 4 if mode == "copy" else 0,
                              "reused": 0 if mode == "copy" else 4, "model_calls": 0}
            assert "Conteúdo" not in json.dumps(report)
            assert module.same_points(await module.read_points(source, local), await module.read_points(target, remote))
            await target.close()
            target = AsyncQdrantClient(path=str(remote.path))
            assert (await module.transfer_vectors(source, local, target, remote, verify_only=True))["reused"] == 4
        finally:
            await source.close()
            await target.close()
    asyncio.run(run())


def test_dimension_mismatch_does_not_create_collection():
    source, target = AsyncMock(), AsyncMock()
    with pytest.raises(BaseUnavailable, match="dimension_mismatch"):
        asyncio.run(module.transfer_vectors(
            source, VectorSettings(collection="synthetic", dimension=2),
            target, VectorSettings(collection="synthetic", dimension=3),
        ))
    target.create_collection.assert_not_awaited()
    source.collection_exists.assert_not_awaited()


def test_plan_does_not_load_configuration_or_connect(monkeypatch, capsys):
    def unexpected():
        pytest.fail("Plano não deve ler credenciais")
    monkeypatch.setattr(module, "load_vector_settings", unexpected)
    assert module.main([]) == 0
    assert "Zero chamadas" in capsys.readouterr().out


def test_cli_failure_does_not_expose_exception(monkeypatch, capsys):
    async def fail(*args):
        raise RuntimeError("PRIVATE KEY URL PAYLOAD")
    monkeypatch.setattr(module, "execute", fail)
    assert module.main(["--execute"]) == 1
    output = capsys.readouterr().out
    assert "PRIVATE" not in output
    assert json.loads(output)["code"] == "transfer_not_verified"


def test_safe_failure_categories():
    import httpx
    from qdrant_client.http.exceptions import UnexpectedResponse, ResponseHandlingException
    from pydantic import ValidationError

    error = UnexpectedResponse(403, "PRIVATE", b"PRIVATE", httpx.Headers())
    assert module.failure_details(error) == {"reason": "remote_http_error", "http_status": 403}
    assert module.failure_details(ResponseHandlingException(RuntimeError("PRIVATE"))) == {
        "reason": "remote_transport_or_response_error"}
    assert module.failure_details(ValueError("local_base_missing")) == {"reason": "local_base_missing"}
    assert module.failure_details(BaseUnavailable("collection_incomplete")) == {
        "reason": "collection_incomplete"}
    with pytest.raises(ValidationError) as caught:
        VectorSettings.model_validate({"collection": "PRIVATE", "dimension": "PRIVATE"})
    details = module.failure_details(caught.value)
    assert details == {"reason": "invalid_configuration", "variables": ["EMBEDDING_DIMENSION"]}
    assert "PRIVATE" not in json.dumps(details)


@pytest.mark.parametrize("body,hint", [
    (b"Invalid API key or JWT PRIVATE", "authentication_response"),
    (b"plain HTTP request sent to HTTPS port PRIVATE", "http_https_mismatch"),
    (b"gRPC endpoint PRIVATE", "possible_grpc_endpoint"),
    (b"<html>PRIVATE</html>", "html_response_check_endpoint_or_proxy"),
])
def test_http_error_hints_never_publish_body(body, hint):
    import httpx
    from qdrant_client.http.exceptions import UnexpectedResponse
    details = module.failure_details(UnexpectedResponse(400, "PRIVATE", body, httpx.Headers()))
    assert details == {"reason": "remote_http_error", "http_status": 400, "hint": hint}
    assert "PRIVATE" not in json.dumps(details)


@pytest.mark.parametrize("fails", [True, False])
def test_diagnostic_uses_only_two_gets_and_closes_client(monkeypatch, capsys, fails):
    import httpx
    from qdrant_client.http.exceptions import UnexpectedResponse

    async def run():
        def handle(request):
            assert request.method == "GET"
            paths.append(request.url.path)
            if fails:
                return httpx.Response(400, json={"status": {"error": "Invalid API key PRIVATE"}})
            if request.url.path.endswith("/exists"):
                return httpx.Response(200, json={"result": {"exists": False}, "status": "ok", "time": 0})
            return httpx.Response(200, json={"result": {"collections": []}, "status": "ok", "time": 0})

        client = AsyncQdrantClient(url="https://synthetic.invalid", check_compatibility=False,
                                   transport=httpx.MockTransport(handle))
        closed = AsyncMock(wraps=client.close)
        client.close = closed
        monkeypatch.setattr(module, "load_vector_settings", lambda: VectorSettings(
            url="https://synthetic.invalid", api_key="synthetic", collection="synthetic", dimension=2))
        monkeypatch.setattr(module, "create_vector_client", lambda settings: client)
        report = await module.diagnose_connection()
        closed.assert_awaited_once()
        assert [check["operation"] for check in report["checks"]] == ["list_collections", "collection_exists"]
        assert all(check["status"] == ("failed" if fails else "ok") for check in report["checks"])
        if not fails:
            assert report["checks"][1]["exists"] is False
        assert "PRIVATE" not in json.dumps(report)

    paths = []
    asyncio.run(run())
    assert paths == ["/collections", "/collections/synthetic/exists"]


def test_diagnostic_plan_does_not_load_configuration(monkeypatch, capsys):
    monkeypatch.setattr(module, "load_vector_settings", lambda: pytest.fail("sem credenciais no plano"))
    assert module.main(["--diagnose-connection"]) == 0
    assert "dois GETs" in capsys.readouterr().out


@pytest.mark.parametrize("missing_index", [True, False])
def test_ready_diagnostic_reproduces_cloud_count_without_writes(monkeypatch, missing_index):
    import httpx

    async def run():
        settings = VectorSettings(collection="synthetic", dimension=2)
        local = AsyncQdrantClient(location=":memory:")
        try:
            await seed(local, settings)
            info = (await local.get_collection(settings.collection)).model_dump(mode="json")
        finally:
            await local.close()
        calls = []

        def handle(request):
            calls.append((request.method, request.url.path))
            assert request.method == "GET" or request.url.path.endswith("/points/count")
            if request.url.path.endswith("/points/count"):
                body = json.loads(request.content)
                if body.get("filter"):
                    if missing_index:
                        return httpx.Response(400, json={"status": {"error":
                            "Index required for document_name PRIVATE"}})
                    result = {"count": 1}
                else:
                    result = {"count": 4}
            elif request.url.path.endswith("/exists"):
                result = {"exists": True}
            elif request.url.path == "/collections":
                result = {"collections": []}
            else:
                result = info
            return httpx.Response(200, json={"result": result, "status": "ok", "time": 0})

        client = AsyncQdrantClient(url="https://synthetic.invalid", check_compatibility=False,
                                   transport=httpx.MockTransport(handle))
        monkeypatch.setattr(module, "load_vector_settings", lambda: VectorSettings(
            url="https://synthetic.invalid", api_key="synthetic", collection="synthetic", dimension=2))
        monkeypatch.setattr(module, "create_vector_client", lambda settings: client)
        report = await module.diagnose_connection(check_readiness=True)
        check = report["checks"][-1]
        assert check["operation"] == "check_ready"
        if missing_index:
            assert check == {"operation": "check_ready", "status": "failed",
                             "reason": "remote_http_error", "http_status": 400,
                             "hint": "missing_payload_index", "fields": ["document_name"]}
        else:
            assert check["status"] == "ok"
        assert "PRIVATE" not in json.dumps(report)
        assert len(calls) <= 9

    asyncio.run(run())


@pytest.mark.parametrize("mode", ["prepare", "incompatible", "failure"])
def test_remote_index_preparation_preserves_points_and_reuses_indexes(mode):
    import httpx

    async def run():
        settings = VectorSettings(collection="synthetic", dimension=2)
        local = AsyncQdrantClient(location=":memory:")
        try:
            await seed(local, settings)
            info = (await local.get_collection(settings.collection)).model_dump(mode="json")
            before = await module.read_points(local, settings)
            schema = {"document_name": {"data_type": "keyword", "points": 4}}
            if mode == "incompatible":
                schema["embedding_model"] = {"data_type": "integer", "points": 4}
            writes = []

            def handle(request):
                if request.method == "PUT":
                    assert request.url.path == "/collections/synthetic/index"
                    body = json.loads(request.content)
                    assert body["field_schema"] == "keyword"
                    writes.append(body["field_name"])
                    if mode == "failure":
                        return httpx.Response(403, json={"status": {"error": "PRIVATE"}})
                    schema[body["field_name"]] = {"data_type": "keyword", "points": 4}
                    result = {"operation_id": 0, "status": "completed"}
                else:
                    assert request.method == "GET"
                    result = {"exists": True} if request.url.path.endswith("/exists") else {
                        **info, "payload_schema": dict(schema)}
                return httpx.Response(200, json={"result": result, "status": "ok", "time": 0})

            client = AsyncQdrantClient(url="https://synthetic.invalid", check_compatibility=False,
                                       transport=httpx.MockTransport(handle))
            try:
                if mode != "prepare":
                    from qdrant_client.http.exceptions import UnexpectedResponse
                    with pytest.raises(BaseUnavailable if mode == "incompatible" else UnexpectedResponse):
                        await module.prepare_payload_indexes(client, settings)
                    assert len(writes) == (0 if mode == "incompatible" else 1)
                else:
                    report = await module.prepare_payload_indexes(client, settings)
                    assert report["created"] == list(module.READINESS_FIELDS[1:])
                    assert report["reused"] == ["document_name"]
                    again = await module.prepare_payload_indexes(client, settings)
                    assert again["created"] == []
                    assert len(writes) == 3
                assert module.same_points(before, await module.read_points(local, settings))
            finally:
                await client.close()
        finally:
            await local.close()

    asyncio.run(run())


def test_index_preparation_plan_and_readonly_flags(monkeypatch, capsys):
    monkeypatch.setattr(module, "load_vector_settings", lambda: pytest.fail("sem credenciais no plano"))
    assert module.main(["--prepare-payload-indexes"]) == 0
    assert "quatro índices" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        module.main(["--execute", "--prepare-payload-indexes", "--verify-only"])
