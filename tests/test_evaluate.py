import asyncio
import copy
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from openai import APIConnectionError, APIError, APIStatusError, APITimeoutError

from app.config import EXPECTED_DOCUMENTS, GatewaySettings, VectorSettings
from app.gateway import GatewayContractError, create_gateway_client
from app.vector_store import BaseUnavailable
from scripts import evaluate
from test_chat import event, hit


@pytest.fixture
def evaluation(tmp_path, monkeypatch):
    monkeypatch.setattr(evaluate, "PRIVATE_ROOT", tmp_path / "private")
    run = evaluate.private_dir(tmp_path / "private" / "run")
    cases, alternate = evaluate.suite()
    hashes = {name: "a" * 64 for name in EXPECTED_DOCUMENTS}
    evaluate.save(run / "references.json", {"suite_hash": evaluate.digest(cases), "document_hashes": hashes})
    manifest = [{"document_name": name, "document_hash": value, "chunks": 1} for name, value in hashes.items()]
    monkeypatch.setattr(evaluate, "check_ready", AsyncMock())
    monkeypatch.setattr(evaluate, "validate_collection", AsyncMock(return_value=manifest))

    async def retrieve(question, *args):
        case = next(c for c in cases if c["question"] == question)
        source = case["expected_sources"][0] if case["expected_sources"] else {"document": EXPECTED_DOCUMENTS[0], "page": 12}
        item = hit("PRIVATE SYNTHETIC EVIDENCE", source["page"])
        item["chunk"]["document_name"] = source["document"]
        return [item]

    retrieval = AsyncMock(side_effect=retrieve)
    monkeypatch.setattr(evaluate, "retrieve_chunks", retrieval)
    settings = GatewaySettings(base_url="https://synthetic.test/v1", api_key="synthetic", embedding_dimension=2)
    vector = VectorSettings(path=tmp_path / "vectors", collection="synthetic", dimension=2)
    requests, responses = [], []
    fail = []

    async def handle(request):
        body = json.loads(request.content)
        requests.append(body)
        if fail and isinstance(fail[0], Exception):
            raise fail[0]
        if fail and isinstance(fail[0], httpx.Response):
            response = fail[0]
        elif fail:
            raise RuntimeError("PRIVATE PROVIDER DETAIL")
        else:
            response = httpx.Response(200, headers={"content-type": "text/event-stream"},
                                     content=event("PRIVATE SYNTHETIC ANSWER [S1]", "stop"))
        responses.append(response)
        return response

    def collect(phase, model="default", selected=None, repeat=False, override=None):
        async def execute():
            async with create_gateway_client(override or settings, transport=httpx.MockTransport(handle)) as gateway:
                return await evaluate.collect(run, cases, alternate, phase, model, selected, repeat,
                                              AsyncMock(), vector, gateway, override or settings)
        return asyncio.run(execute())

    yield run, cases, alternate, collect, retrieval, requests, fail, settings
    assert all(response.is_closed for response in responses)


def test_full_collection_reuses_contexts_and_requires_human_review(evaluation):
    run, cases, alternate, collect, retrieval, requests, *_ = evaluation
    report = collect("retrieval")
    assert report["retrieval"]["hits_at_4"] == 8
    assert retrieval.await_count == 8 and not requests
    assert report["quality_status"] == "pending"
    collect("retrieval")
    assert retrieval.await_count == 8
    report = collect("answers")
    assert retrieval.await_count == 12 and len(requests) == 12
    report = collect("answers", "alternate")
    assert retrieval.await_count == 12 and len(requests) == 14
    assert all(r["model"] == "azure/gpt-6-luna" for r in requests[-2:])
    assert [r["messages"] for r in requests[-2:]] == [requests[0]["messages"], requests[6]["messages"]]
    assert report["quality_status"] == "pending"
    assert "PRIVATE" not in json.dumps(report)
    state = evaluate.read(run / "state.json")
    assert state["answers"][0]["messages"] == requests[0]["messages"]
    assert "PRIVATE SYNTHETIC EVIDENCE" in state["contexts"]["R1"]["context"]
    assert "PRIVATE SYNTHETIC ANSWER" in state["answers"][0]["answer"]
    assert (run / "state.json").stat().st_mode & 0o777 == 0o600
    assert run.stat().st_mode & 0o777 == 0o700
    collect("answers")
    collect("answers", "alternate")
    assert len(requests) == 14


def test_human_reviews_separate_axes_and_failures(evaluation):
    run, cases, alternate, collect, *_ = evaluation
    collect("retrieval")
    collect("answers")
    collect("answers", "alternate")
    state = evaluate.read(run / "state.json")
    reviews = evaluate.read(run / "reviews.json")
    for review in reviews.values():
        review.update({key: "pass" for key, value in review.items() if value == "pending"})
        review.update(reviewer="Synthetic reviewer", reviewed_at="2026-10-28", notes="Synthetic evidence checked")
    assert evaluate.summary(state, cases, alternate, reviews)["quality_status"] == "passed"
    injection = next(a for a in state["answers"] if a["case_id"] == "I1")
    reviews[injection["id"]]["security"] = "fail"
    assert evaluate.summary(state, cases, alternate, reviews)["quality_status"] == "failed"
    reviews[injection["id"]]["security"] = "pass"
    reviews[injection["id"]]["reviewer"] = ""
    assert evaluate.summary(state, cases, alternate, reviews)["quality_status"] == "pending"


def test_no_generation_before_retrieval_and_alternate_after_default(evaluation):
    *_, collect, retrieval, requests, fail, settings = evaluation
    with pytest.raises(ValueError, match="complete_retrieval_phase_first"):
        collect("answers")
    assert retrieval.await_count == 0 and not requests
    collect("retrieval")
    with pytest.raises(ValueError, match="collect_default_model_first"):
        collect("answers", "alternate")
    assert not requests


def test_failed_generation_never_retries_implicitly_and_preserves_attempts(evaluation):
    run, _, _, collect, retrieval, requests, fail, _ = evaluation
    collect("retrieval")
    fail.append(True)
    with pytest.raises(ValueError, match="gateway_connection_failed"):
        collect("answers", selected=["R1"])
    state = evaluate.read(run / "state.json")
    assert state["answers"][0]["status"] == "failed"
    assert state["answers"][0]["error"] == "gateway_connection_failed"
    assert state["answers"][0]["error_stage"] == "generation"
    assert "PRIVATE PROVIDER DETAIL" not in json.dumps(state)
    collect("answers", selected=["R1"])
    assert len(requests) == 1
    fail.clear()
    collect("answers", selected=["R1"], repeat=True)
    state = evaluate.read(run / "state.json")
    assert [a["status"] for a in state["answers"]] == ["failed", "collected"]
    assert retrieval.await_count == 8 and len(requests) == 2


def test_empty_context_uses_application_explanation_without_generation(evaluation, monkeypatch):
    _, _, _, collect, _, requests, *_ = evaluation
    monkeypatch.setattr(evaluate, "retrieve_chunks", AsyncMock(return_value=[]))
    collect("retrieval")
    report = collect("answers")
    assert not requests
    assert report["retrieval"]["hits_at_4"] == 0
    assert report["quality_status"] == "failed"


@pytest.mark.parametrize("reason", ["not_ready", "document_hash", "dimension", "contract"])
def test_incompatible_base_blocks_model_calls(evaluation, monkeypatch, reason):
    run, _, _, collect, retrieval, requests, *_ = evaluation
    if reason == "not_ready":
        monkeypatch.setattr(evaluate, "check_ready", AsyncMock(side_effect=ValueError("unavailable")))
    elif reason == "document_hash":
        monkeypatch.setattr(evaluate, "validate_collection", AsyncMock(return_value=[]))
    elif reason == "dimension":
        monkeypatch.setattr(evaluate, "collection_contract", lambda v: pytest.fail("Before signature"))
    else:
        state = evaluate.load_state(run, evaluation[1])
        state["retrieval_signature"] = "different"
        evaluate.save(run / "state.json", state)
    override = evaluation[-1].model_copy(update={"embedding_dimension": 3}) if reason == "dimension" else None
    with pytest.raises(ValueError):
        collect("retrieval", override=override)
    assert not requests and retrieval.await_count == 0


def test_prompt_change_requires_explicit_repeat_and_invalidates_old_review(evaluation, monkeypatch):
    run, cases, alternate, collect, retrieval, requests, *_ = evaluation
    collect("retrieval")
    collect("answers", selected=["R1"])
    monkeypatch.setattr(evaluate, "GENERATION_INSTRUCTIONS", evaluate.GENERATION_INSTRUCTIONS + "synthetic change")
    with pytest.raises(ValueError, match="generation_changed"):
        collect("answers", selected=["R1"])
    collect("answers", selected=["R1"], repeat=True)
    assert len(requests) == 2 and retrieval.await_count == 8
    assert len(evaluate.read(run / "state.json")["answers"]) == 2


def test_references_generated_from_synthetic_pdfs_only(tmp_path, make_pdf, monkeypatch):
    monkeypatch.setattr(evaluate, "PRIVATE_ROOT", tmp_path / "private")
    raw = tmp_path / "raw"
    raw.mkdir()
    monkeypatch.setattr(evaluate, "RAW_PDF_DIR", raw)
    for name in EXPECTED_DOCUMENTS:
        make_pdf(raw / name, ["Synthetic source"] * 60)
    run = evaluate.private_dir(tmp_path / "private" / "run")
    cases, _ = evaluate.suite()
    evaluate.prepare_references(run, cases)
    refs = evaluate.read(run / "references.json")
    assert len(refs["document_hashes"]) == 4
    assert refs["cases"]["R2"]["pages"][0]["page"] == 43
    assert refs["cases"]["R2"]["pages"][0]["text"] == "Synthetic source"
    assert refs["cases"]["N1"]["absence_page_counts"] == {"PostgreSQL": 0, "B-tree": 0}
    with pytest.raises(ValueError, match="already_exist"):
        evaluate.prepare_references(run, cases)
    changed = copy.deepcopy(cases)
    changed[0]["question"] = "Changed"
    with pytest.raises(ValueError, match="suite_changed"):
        evaluate.load_state(run, changed)


@pytest.mark.parametrize("phase,model,embeddings,generations", [
    ("references", "default", 0, 0), ("retrieval", "default", 8, 0),
    ("answers", "default", 4, 12), ("answers", "alternate", 0, 2), ("summary", "default", 0, 0),
])
def test_plan_never_reads_configuration_or_files(phase, model, embeddings, generations, monkeypatch, capsys):
    monkeypatch.setattr(evaluate, "load_gateway_settings", lambda: pytest.fail("credentials"))
    monkeypatch.setattr(evaluate, "private_dir", lambda p: pytest.fail("private files"))
    args = ["--phase", phase] + (["--model", model] if model != "default" else [])
    assert evaluate.main(args) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["max_embedding_calls"] == embeddings
    assert report["max_generation_calls"] == generations


@pytest.mark.parametrize("args", [
    ["--execute"], ["--execute", "--gateway-verified"],
    ["--repeat"], ["--phase", "answers", "--repeat"],
    ["--phase", "answers", "--model", "alternate", "--cases", "N1"],
    ["--phase", "retrieval", "--cases", "R1"],
    ["--phase", "answers", "--cases", "R1", "R1"],
])
def test_cli_preconditions(args, monkeypatch):
    monkeypatch.setattr(evaluate, "execute", lambda *a: pytest.fail("execution"))
    with pytest.raises(SystemExit) as error:
        evaluate.main(args)
    assert error.value.code == 2


def test_public_cli_errors_hide_external_details(evaluation, monkeypatch, capsys):
    monkeypatch.setattr(evaluate, "execute", AsyncMock(side_effect=RuntimeError("PRIVATE SECRET")))
    assert evaluate.main(["--execute", "--gateway-verified", "--extraction-reviewed", "--run-dir", str(evaluation[0])]) == 1
    assert "PRIVATE" not in capsys.readouterr().out


def test_private_paths_reject_escape_and_symlink(tmp_path, monkeypatch):
    private = tmp_path / "private"
    private.mkdir()
    monkeypatch.setattr(evaluate, "PRIVATE_ROOT", private)
    for path in [tmp_path / "public", private / ".." / "escaped", private]:
        with pytest.raises(ValueError):
            evaluate.private_dir(path)
    (private / "link").symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        evaluate.private_dir(private / "link" / "run")


def test_cli_collection_success_does_not_imply_quality_pass(evaluation, monkeypatch, capsys):
    run, _, _, collect, *_ = evaluation
    collect("retrieval")
    report = collect("answers")
    monkeypatch.setattr(evaluate, "execute", AsyncMock(return_value=report))
    assert evaluate.main(["--phase", "answers", "--execute", "--gateway-verified", "--extraction-reviewed", "--run-dir", str(run)]) == 0
    assert json.loads(capsys.readouterr().out)["quality_status"] == "pending"
    assert evaluate.main(["--phase", "summary", "--execute", "--run-dir", str(run)]) == 1
    assert json.loads(capsys.readouterr().out)["quality_status"] == "pending"


@pytest.mark.parametrize("error,expected", [
    (TimeoutError("PRIVATE DETAIL"), "gateway_timeout"),
    (APITimeoutError(request=httpx.Request("POST", "https://synthetic.test")), "gateway_timeout"),
    (httpx.ReadTimeout("PRIVATE DETAIL"), "gateway_timeout"),
    (APIConnectionError(message="PRIVATE DETAIL", request=httpx.Request("POST", "https://synthetic.test")), "gateway_connection_failed"),
    (httpx.ConnectError("PRIVATE DETAIL"), "gateway_connection_failed"),
    (GatewayContractError("chat_completion_invalid"), "chat_completion_invalid"),
    (GatewayContractError("chat_missing_finish_reason"), "chat_missing_finish_reason"),
    (GatewayContractError("PRIVATE DETAIL"), "gateway_contract_invalid"),
    (GatewayContractError(["PRIVATE DETAIL"]), "gateway_contract_invalid"),
    (APIError("PRIVATE DETAIL", httpx.Request("POST", "https://synthetic.test"), body={"private": "PRIVATE BODY"}), "gateway_response_invalid"),
    (json.JSONDecodeError("PRIVATE DETAIL", "PRIVATE BODY", 0), "gateway_response_invalid"),
    (BaseUnavailable("PRIVATE DETAIL"), "base_unavailable"),
    (OSError("PRIVATE FILE PATH"), "evaluation_storage_failed"),
    (ValueError("PRIVATE DETAIL"), "evaluation_case_failed"),
])
def test_failure_codes_never_copy_exception_details(error, expected):
    assert evaluate.failure_code(error) == expected
    assert expected in evaluate.FAILURE_CODES


@pytest.mark.parametrize("status", [400, 401, 403, 408, 422, 429, 500, 502, 503, 504])
def test_http_error_code_only_contains_validated_status(status):
    response = httpx.Response(status, request=httpx.Request("POST", "https://synthetic.test"))
    error = APIStatusError("PRIVATE DETAIL", response=response, body={"private": "PRIVATE BODY"})
    assert evaluate.failure_code(error) == f"gateway_http_{status}"
    error.status_code = "PRIVATE STATUS"
    assert evaluate.failure_code(error) == "gateway_response_invalid"


@pytest.mark.parametrize("failure,expected", [
    (httpx.Response(401, json={"error": {"message": "PRIVATE PROVIDER DETAIL"}}), "gateway_http_401"),
    (httpx.Response(429, json={"error": {"message": "PRIVATE PROVIDER DETAIL"}}), "gateway_http_429"),
    (httpx.Response(503, json={"error": {"message": "PRIVATE PROVIDER DETAIL"}}), "gateway_http_503"),
    (httpx.ReadTimeout("PRIVATE PROVIDER DETAIL"), "gateway_timeout"),
    (httpx.Response(200, headers={"content-type": "text/event-stream"}, content=event(None, "stop")), "chat_completion_invalid"),
    (httpx.Response(200, headers={"content-type": "text/event-stream"}, content=event("PRIVATE PARTIAL ANSWER")), "chat_missing_finish_reason"),
    (httpx.Response(200, headers={"content-type": "text/event-stream"}, content=b"data: PRIVATE PROVIDER DETAIL\n\n"), "chat_response_invalid"),
])
def test_failed_case_diagnostic_reaches_cli_and_state_without_retry(evaluation, monkeypatch, capsys, failure, expected):
    run, cases, alternate, collect, retrieval, requests, fail, _ = evaluation
    collect("retrieval")
    fail.append(failure)
    with pytest.raises(ValueError, match=f"^{expected}$"):
        collect("answers", selected=["R1"])
    state = evaluate.read(run / "state.json")
    attempt = state["answers"][-1]
    assert attempt["error"] == expected and attempt["error_stage"] == "generation"
    assert not {"answer", "messages", "sources"} & attempt.keys()
    assert retrieval.await_count == 8 and len(requests) == 1
    report = collect("answers", selected=["R1"])
    assert len(requests) == 1  # Exibir o diagnóstico não repete a chamada que falhou.
    row = next(r for r in report["cases"] if r["id"] == "R1" and r["model"] == "azure/gpt-5-mini")
    assert row["error"] == expected and row["error_stage"] == "generation"
    assert report["quality_status"] == "pending"
    monkeypatch.setattr(evaluate, "execute", AsyncMock(side_effect=ValueError(expected)))
    assert evaluate.main(["--phase", "answers", "--execute", "--gateway-verified", "--extraction-reviewed", "--run-dir", str(run)]) == 1
    output = capsys.readouterr().out
    assert json.loads(output) == {"status": "failed", "error": expected}
    assert "PRIVATE" not in output + json.dumps(report)
    assert "PRIVATE PROVIDER DETAIL" not in json.dumps(state)
    assert "PRIVATE PARTIAL ANSWER" not in json.dumps(state)


def test_preparation_and_retrieval_failures_have_their_own_stage(evaluation, monkeypatch):
    run, _, _, collect, retrieval, requests, *_ = evaluation
    collect("retrieval")
    def fail_preparation(*args):
        raise ValueError("PRIVATE DETAIL")
    monkeypatch.setattr(evaluate, "build_messages", fail_preparation)
    with pytest.raises(ValueError, match="evaluation_case_failed"):
        collect("answers", selected=["R1"])
    assert evaluate.read(run / "state.json")["answers"][-1]["error_stage"] == "preparation"
    retrieval.side_effect = BaseUnavailable("PRIVATE DETAIL")
    with pytest.raises(ValueError, match="base_unavailable"):
        collect("answers", selected=["N1"])
    attempt = evaluate.read(run / "state.json")["answers"][-1]
    assert attempt["error_stage"] == "retrieval" and attempt["error"] == "base_unavailable"
    assert not requests


def test_legacy_failure_does_not_gain_an_invented_cause(evaluation):
    run, cases, alternate, collect, *_ = evaluation
    collect("retrieval")
    state = evaluate.read(run / "state.json")
    state["answers"] = [{"case_id": "R1", "model": "azure/gpt-5-mini", "status": "failed", "error": "evaluation_case_failed"}]
    report = evaluate.summary(state, cases, alternate, {})
    row = next(r for r in report["cases"] if r["id"] == "R1" and r["model"] == "azure/gpt-5-mini")
    assert row["error"] == "evaluation_case_failed"
    assert "error_stage" not in row
    state["answers"][0].update(error="PRIVATE DETAIL", error_stage="PRIVATE STAGE")
    assert "PRIVATE" not in json.dumps(evaluate.summary(state, cases, alternate, {}))


def test_persistence_failure_is_categorized_without_new_generation(evaluation, monkeypatch):
    run, _, _, collect, _, requests, *_ = evaluation
    collect("retrieval")
    original_save = evaluate.save

    def fail_review_save(path, value):
        if path.name == "reviews.json":
            raise OSError("PRIVATE FILE PATH")
        original_save(path, value)

    monkeypatch.setattr(evaluate, "save", fail_review_save)
    with pytest.raises(ValueError, match="evaluation_storage_failed"):
        collect("answers", selected=["R1"])
    attempt = evaluate.read(run / "state.json")["answers"][-1]
    assert attempt["status"] == "failed"
    assert attempt["error"] == "evaluation_storage_failed" and attempt["error_stage"] == "persistence"
    collect("answers", selected=["R1"])
    assert len(requests) == 1
