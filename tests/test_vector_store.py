import asyncio
import copy
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from qdrant_client import AsyncQdrantClient, models

from app.config import EXPECTED_DOCUMENTS, GatewaySettings, VectorSettings, load_vector_settings
from app.gateway import create_gateway_client
from app.ingestion import build_manifest, index_chunks, prepare_document
from app.rag import retrieve_chunks
from app.vector_store import (
    BaseUnavailable, check_ready, collection_contract, create_vector_client,
    ensure_collection, search_chunks, upsert_chunks,
)
from scripts.check_retrieval import check_retrieval


@pytest.fixture
def prepared(tmp_path, make_pdf):
    chunks = []
    for i, name in enumerate(EXPECTED_DOCUMENTS):
        path = make_pdf(tmp_path / name, [f"Synthetic {i} " + "abc " * 1200])
        _, document_chunks = prepare_document(path)
        chunks.extend(document_chunks)
    return chunks


def settings_pair(tmp_path):
    vector = VectorSettings(collection="synthetic_v1", dimension=2, path=tmp_path / "vectors")
    gateway = GatewaySettings(base_url="https://gateway.test/v1", api_key="synthetic", embedding_dimension=2)
    return vector, gateway


def simulated_gateway(request):
    body = json.loads(request.content)
    assert request.url.path == "/v1/embeddings"
    assert body["input_type"] in {"search_document", "search_query"}
    # Ordem invertida exercita a associação dos vetores pelo índice do gateway.
    return httpx.Response(200, json={"data": [
        {"index": i, "embedding": [1.0, float(i + 1)]}
        for i in reversed(range(len(body["input"])))
    ]})


def test_persistence_resume_no_calls_and_physical_sources(tmp_path, prepared):
    vector, gateway_settings = settings_pair(tmp_path)
    calls = []

    def handle(request):
        calls.append(json.loads(request.content))
        return simulated_gateway(request)

    async def run():
        store = create_vector_client(vector)
        async with create_gateway_client(gateway_settings, transport=httpx.MockTransport(handle)) as gateway:
            first = await index_chunks(store, vector, gateway, gateway_settings, prepared)
            assert first["status"] == "passed"
            assert first["written_chunks"] == len(prepared)
            assert first["calls_attempted"] == 2
            assert all(len(call["input"]) <= 16 for call in calls)
            points = await store.retrieve(vector.collection, [prepared[0]["chunk_id"]], with_vectors=True)
            assert points[0].payload == prepared[0]
            assert points[0].vector == pytest.approx([2 ** -0.5, 2 ** -0.5])
            await store.close()
            store = create_vector_client(vector)
            second = await index_chunks(store, vector, gateway, gateway_settings, prepared)
            assert second["status"] == "passed"
            assert second["written_chunks"] == second["calls_attempted"] == 0
            assert second["reused_chunks"] == len(prepared)
            assert (await store.count(vector.collection, exact=True)).count == len(prepared)
            assert len(calls) == 2
            hits = await retrieve_chunks("Pergunta sintética?", store, vector, gateway, gateway_settings)
            assert len(hits) == 4
            assert calls[-1]["input_type"] == "search_query"
            assert calls[-1]["input"] == ["Pergunta sintética?"]
            assert all(h["chunk"]["page"] == 1 and h["chunk"]["document_name"] in EXPECTED_DOCUMENTS for h in hits)
            assert all(h["chunk"] in prepared for h in hits)
        await store.close()
    asyncio.run(run())


def test_partial_failure_resumes_only_missing_batch(tmp_path, prepared):
    vector, gateway_settings = settings_pair(tmp_path)
    calls = []

    def handle(request):
        calls.append(request)
        if len(calls) == 2:
            return httpx.Response(503, json={"error": {"message": "PRIVATE PROVIDER BODY"}})
        return simulated_gateway(request)

    async def run():
        store = create_vector_client(vector)
        try:
            async with create_gateway_client(gateway_settings, transport=httpx.MockTransport(handle)) as gateway:
                failed = await index_chunks(store, vector, gateway, gateway_settings, prepared)
                assert failed["status"] == "failed" and failed["written_chunks"] == 16
                assert "PRIVATE" not in json.dumps(failed)
                with pytest.raises(BaseUnavailable, match="incomplete"):
                    await check_ready(store, vector)
                resumed = await index_chunks(store, vector, gateway, gateway_settings, prepared)
                assert resumed["status"] == "passed"
                assert resumed["reused_chunks"] == 16
                assert resumed["calls_attempted"] == 1
                assert len(calls) == 3
        finally:
            await store.close()
    asyncio.run(run())


@pytest.mark.parametrize("change", ["dimension", "distance", "pipeline", "model", "manifest", "missing_metadata"])
def test_incompatible_collection_preserves_data_without_embeddings(tmp_path, prepared, change):
    vector, gateway_settings = settings_pair(tmp_path)

    async def run():
        store = create_vector_client(vector)
        try:
            metadata = {"rag_contract": collection_contract(vector), "documents": build_manifest(prepared)}
            size = 3 if change == "dimension" else 2
            distance = models.Distance.DOT if change == "distance" else models.Distance.COSINE
            if change == "pipeline":
                metadata["rag_contract"]["pipeline_version"] = "old"
            if change == "model":
                metadata["rag_contract"]["embedding_model"] = "old"
            if change == "manifest":
                metadata["documents"][0]["document_hash"] = "b" * 64
            await store.create_collection(vector.collection, vectors_config=models.VectorParams(size=size, distance=distance),
                                          metadata=None if change == "missing_metadata" else metadata)
            sentinel = models.PointStruct(id=1, vector=[1.0] * size, payload={"sentinel": "keep"})
            await store.upsert(vector.collection, points=[sentinel])
            async with create_gateway_client(gateway_settings, transport=httpx.MockTransport(
                lambda request: pytest.fail("Não deve chamar embeddings"),
            )) as gateway:
                report = await index_chunks(store, vector, gateway, gateway_settings, prepared)
                assert report["status"] == "failed" and report["calls_attempted"] == 0
            assert (await store.retrieve(vector.collection, [1]))[0].payload == {"sentinel": "keep"}
            assert (await store.count(vector.collection, exact=True)).count == 1
        finally:
            await store.close()
    asyncio.run(run())


def test_existing_payload_collision_stops_before_model(tmp_path, prepared):
    vector, gateway_settings = settings_pair(tmp_path)

    async def run():
        store = create_vector_client(vector)
        try:
            await ensure_collection(store, vector, build_manifest(prepared))
            changed = copy.deepcopy(prepared[0])
            changed["text"] = "corrupted"
            await upsert_chunks(store, vector, [changed], [[1.0, 1.0]])
            gateway = AsyncMock()
            report = await index_chunks(store, vector, gateway, gateway_settings, prepared)
            assert report["failures"][0]["code"] == "existing_chunk_incompatible"
            assert report["calls_attempted"] == 0
        finally:
            await store.close()
    asyncio.run(run())


@pytest.mark.parametrize("vectors", [[[1.0, 2.0, 3.0]], [[0.0, 0.0]], [[True, 1.0]], [[float('nan'), 1.0]], []])
def test_invalid_batch_is_not_written(tmp_path, prepared, vectors):
    vector, _ = settings_pair(tmp_path)

    async def run():
        store = create_vector_client(vector)
        try:
            await ensure_collection(store, vector, build_manifest(prepared))
            with pytest.raises(BaseUnavailable):
                await upsert_chunks(store, vector, prepared[:1], vectors)
            assert (await store.count(vector.collection, exact=True)).count == 0
        finally:
            await store.close()
    asyncio.run(run())


def test_missing_base_and_invalid_question_do_not_consume_models(tmp_path):
    vector, gateway_settings = settings_pair(tmp_path)

    async def run():
        store = create_vector_client(vector)
        try:
            gateway = AsyncMock()
            with pytest.raises(BaseUnavailable, match="collection_missing"):
                await retrieve_chunks("Pergunta", store, vector, gateway, gateway_settings)
            for question in [" ", "x" * 1501]:
                with pytest.raises(ValueError, match="invalid_question"):
                    await retrieve_chunks(question, store, vector, gateway, gateway_settings)
            gateway.embeddings.with_raw_response.create.assert_not_awaited()
        finally:
            await store.close()
    asyncio.run(run())


def test_id_stability_and_new_document_content(tmp_path, make_pdf):
    path = make_pdf(tmp_path / EXPECTED_DOCUMENTS[0], ["Primeira pagina", "Segunda pagina"])
    report, first = prepare_document(path)
    assert first == prepare_document(path)[1]
    assert [c["page"] for c in first] == [1, 2]
    assert [c["chunk_index"] for c in first] == [0, 0]
    make_pdf(path, ["Outro conteudo", "Segunda pagina"])
    changed = prepare_document(path)[1]
    assert {c["chunk_id"] for c in first}.isdisjoint(c["chunk_id"] for c in changed)
    assert first[0]["document_id"] == changed[0]["document_id"]
    assert first[0]["document_hash"] != changed[0]["document_hash"]


def test_remote_client_uses_explicit_rest_without_probe(monkeypatch):
    import app.vector_store as module
    seen = {}

    def factory(**kwargs):
        seen.update(kwargs)
        return object()

    monkeypatch.setattr(module, "AsyncQdrantClient", factory)
    settings = VectorSettings(url="https://qdrant.test", api_key="synthetic", collection="test", dimension=2)
    create_vector_client(settings)
    assert seen["check_compatibility"] is False
    assert seen["prefer_grpc"] is False
    assert seen["follow_redirects"] is False
    assert "path" not in seen


@pytest.mark.parametrize("env", [
    {}, {"QDRANT_COLLECTION": "test"},
    {"QDRANT_COLLECTION": "test", "EMBEDDING_DIMENSION": "0"},
    {"QDRANT_COLLECTION": "test", "EMBEDDING_DIMENSION": "2", "QDRANT_URL": "https://qdrant.test"},
    {"QDRANT_COLLECTION": "test", "EMBEDDING_DIMENSION": "2", "QDRANT_URL": "https://user:private@qdrant.test"},
])
def test_invalid_vector_config(env):
    with pytest.raises(ValueError):
        load_vector_settings(env)


def test_evaluation_with_simulated_vectors_reports_ranks_without_text(tmp_path, prepared):
    vector, gateway_settings = settings_pair(tmp_path)

    async def run():
        store = create_vector_client(vector)
        try:
            async with create_gateway_client(gateway_settings, transport=httpx.MockTransport(simulated_gateway)) as gateway:
                await index_chunks(store, vector, gateway, gateway_settings, prepared)
                hits = await search_chunks(store, vector, [1.0, 1.0])
                source = {"document": hits[0]["chunk"]["document_name"], "page": hits[0]["chunk"]["page"]}
                cases = [{"id": f"S{i}", "question": "PRIVATE QUESTION", "expected_sources": [source]} for i in range(8)]
                report = await check_retrieval(store, vector, gateway, gateway_settings, cases)
                assert report["status"] == "passed" and report["hits_at_4"] == 8
                assert report["calls_attempted"] == 8
                assert "PRIVATE QUESTION" not in json.dumps(report)
                assert "Synthetic" not in json.dumps(report)
                for case in cases[:2]:
                    case["expected_sources"] = [{"document": "absent", "page": 99}]
                report = await check_retrieval(store, vector, gateway, gateway_settings, cases)
                assert report["status"] == "below_target" and report["hits_at_4"] == 6
        finally:
            await store.close()
    asyncio.run(run())


def test_remote_rest_round_trip_with_simulated_server(tmp_path, prepared, monkeypatch):
    """SDK remoto serializa requests reais em MockTransport; armazenamento é temporário."""
    import app.vector_store as module
    vector, gateway_settings = settings_pair(tmp_path)
    vector = vector.model_copy(update={"url": "https://qdrant.test:6333", "api_key": gateway_settings.api_key})
    requests = []

    async def run():
        backing = AsyncQdrantClient(":memory:")

        async def handle(request):
            requests.append((request.method, request.url.path))
            assert request.headers["api-key"] == "synthetic"
            body = json.loads(request.content) if request.content else {}
            suffix = request.url.path.removeprefix("/collections/synthetic_v1")
            if request.method == "GET" and suffix == "/exists":
                result = {"exists": await backing.collection_exists(vector.collection)}
            elif request.method == "GET" and suffix == "":
                result = (await backing.get_collection(vector.collection)).model_dump(mode="json")
            elif request.method == "PUT" and suffix == "":
                result = await backing.create_collection(
                    vector.collection, vectors_config=models.VectorParams.model_validate(body["vectors"]), metadata=body["metadata"],
                )
            elif request.method == "POST" and suffix == "/points":
                points = await backing.retrieve(vector.collection, body["ids"], with_payload=body["with_payload"])
                result = [p.model_dump(mode="json") for p in points]
            elif request.method == "PUT" and suffix == "/points":
                result = (await backing.upsert(vector.collection, points=[models.PointStruct.model_validate(p) for p in body["points"]])).model_dump(mode="json")
            elif request.method == "POST" and suffix == "/points/count":
                filters = models.Filter.model_validate(body["filter"]) if body.get("filter") else None
                result = (await backing.count(vector.collection, count_filter=filters, exact=body["exact"])).model_dump(mode="json")
            elif request.method == "POST" and suffix == "/points/query":
                result = (await backing.query_points(vector.collection, query=models.NearestQuery.model_validate(body["query"]), limit=body["limit"], with_payload=True)).model_dump(mode="json")
            else:
                pytest.fail(f"Operação inesperada: {request.method} {suffix}")
            return httpx.Response(200, json={"result": result, "status": "ok", "time": 0.0})

        monkeypatch.setattr(module, "AsyncQdrantClient", lambda **kwargs: AsyncQdrantClient(**kwargs, transport=httpx.MockTransport(handle)))
        store = create_vector_client(vector)
        try:
            async with create_gateway_client(gateway_settings, transport=httpx.MockTransport(simulated_gateway)) as gateway:
                report = await index_chunks(store, vector, gateway, gateway_settings, prepared)
                assert report["status"] == "passed", report
                hits = await retrieve_chunks("Synthetic", store, vector, gateway, gateway_settings)
                assert len(hits) == 4
                second = await index_chunks(store, vector, gateway, gateway_settings, prepared)
                assert second["status"] == "passed" and second["calls_attempted"] == 0
        finally:
            await store.close()
            await backing.close()
        assert all(path.startswith("/collections/") for _, path in requests)
        assert not any(method == "DELETE" for method, _ in requests)
    asyncio.run(run())


def test_ready_checks_document_coverage_even_with_correct_total(tmp_path, prepared):
    vector, _ = settings_pair(tmp_path)

    async def run():
        store = create_vector_client(vector)
        try:
            await ensure_collection(store, vector, build_manifest(prepared))
            await upsert_chunks(store, vector, prepared, [[1.0, 1.0]] * len(prepared))
            await check_ready(store, vector)
            await store.set_payload(vector.collection, {"document_hash": "corrupted"}, [prepared[0]["chunk_id"]])
            with pytest.raises(BaseUnavailable, match="collection_document_incomplete"):
                await check_ready(store, vector)
        finally:
            await store.close()
    asyncio.run(run())


def test_malformed_embedding_response_does_not_write_any_points(tmp_path, prepared):
    vector, gateway_settings = settings_pair(tmp_path)

    async def run():
        store = create_vector_client(vector)
        try:
            async with create_gateway_client(gateway_settings, transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json={"data": [{"index": i, "embedding": [1.0, 2.0, 3.0]} for i in range(16)]}),
            )) as gateway:
                report = await index_chunks(store, vector, gateway, gateway_settings, prepared)
                assert report["status"] == "failed" and report["calls_attempted"] == 1
                assert report["failures"][0]["code"] == "embedding_dimension_mismatch"
                assert (await store.count(vector.collection, exact=True)).count == 0
        finally:
            await store.close()
    asyncio.run(run())
