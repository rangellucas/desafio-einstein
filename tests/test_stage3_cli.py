import json
from unittest.mock import AsyncMock

import pytest

from app.config import EXPECTED_DOCUMENTS
from scripts import check_retrieval, ingest


def test_dry_run_call_budget_and_no_configuration_read(tmp_path, make_pdf, monkeypatch, capsys):
    for name in EXPECTED_DOCUMENTS:
        make_pdf(tmp_path / name, ["Synthetic " + "abc " * 1200])
    monkeypatch.setattr(ingest, "load_gateway_settings", lambda: pytest.fail("Não deve ler credenciais"))
    monkeypatch.setattr(ingest, "load_vector_settings", lambda: pytest.fail("Não deve abrir a base"))
    assert ingest.main(["--dry-run", "--input-dir", str(tmp_path)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["total_chunks"] == 20
    assert report["max_embedding_calls"] == 2
    assert not (tmp_path / "vectors").exists()


@pytest.mark.parametrize("argv", [
    ["--execute"], ["--execute", "--gateway-verified"],
    ["--execute", "--gateway-verified", "--extraction-reviewed"],
    ["--execute", "--gateway-verified", "--extraction-reviewed", "--max-embedding-calls", "0"],
])
def test_ingestion_requires_preconditions(argv, monkeypatch):
    monkeypatch.setattr(ingest, "load_gateway_settings", lambda: pytest.fail("Não deve ler credenciais"))
    with pytest.raises(SystemExit) as exc:
        ingest.main(argv)
    assert exc.value.code == 2


def test_ingestion_budget_checked_before_clients(tmp_path, make_pdf, monkeypatch, capsys):
    for name in EXPECTED_DOCUMENTS:
        make_pdf(tmp_path / name, ["Synthetic " + "abc " * 1200])
    execute = AsyncMock()
    monkeypatch.setattr(ingest, "execute_ingestion", execute)
    args = ["--execute", "--gateway-verified", "--extraction-reviewed", "--max-embedding-calls", "1", "--input-dir", str(tmp_path)]
    assert ingest.main(args) == 1
    execute.assert_not_awaited()
    assert json.loads(capsys.readouterr().out)["failures"] == [{"code": "embedding_call_budget_exceeded"}]


def test_ingestion_cli_complete_and_partial_reports(tmp_path, make_pdf, monkeypatch, capsys):
    for name in EXPECTED_DOCUMENTS:
        make_pdf(tmp_path / name, ["Synthetic"])
    execute = AsyncMock(return_value={"status": "passed", "failures": []})
    monkeypatch.setattr(ingest, "execute_ingestion", execute)
    args = ["--execute", "--gateway-verified", "--extraction-reviewed", "--max-embedding-calls", "1", "--input-dir", str(tmp_path)]
    assert ingest.main(args) == 0
    assert json.loads(capsys.readouterr().out)["indexing"]["status"] == "passed"
    execute.return_value = {"status": "failed", "failures": [{"code": "simulated"}]}
    assert ingest.main(args) == 1
    assert json.loads(capsys.readouterr().out)["failures"] == [{"code": "simulated"}]
    execute.side_effect = RuntimeError("PRIVATE VALUE")
    assert ingest.main(args) == 1
    assert "PRIVATE VALUE" not in capsys.readouterr().out


def test_retrieval_default_is_plan_without_configuration(monkeypatch, capsys):
    monkeypatch.setattr(check_retrieval, "load_gateway_settings", lambda: pytest.fail("Não deve ler credenciais"))
    monkeypatch.setattr(check_retrieval, "load_vector_settings", lambda: pytest.fail("Não deve abrir a base"))
    assert check_retrieval.main([]) == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["max_embedding_calls"] == 8
    assert plan["generation_calls"] == 0
    with pytest.raises(SystemExit):
        check_retrieval.main(["--execute"])


def test_reference_cases_two_per_document():
    cases = check_retrieval.load_cases()
    assert len(cases) == 8
    assert all(case["question"].strip() and case["minimum_elements"] for case in cases)
    assert all(s["page"] > 0 for case in cases for s in case["expected_sources"])


def test_retrieval_cli_omits_external_errors(monkeypatch, capsys):
    execute = AsyncMock(side_effect=RuntimeError("PRIVATE VALUE"))
    monkeypatch.setattr(check_retrieval, "execute_check", execute)
    assert check_retrieval.main(["--execute", "--gateway-verified"]) == 1
    assert "PRIVATE VALUE" not in capsys.readouterr().out


def test_commands_name_invalid_variables_without_values(monkeypatch, capsys):
    import asyncio
    from app.config import load_gateway_settings, load_vector_settings

    def invalid_gateway():
        return load_gateway_settings({"LLM_BASE_URL": "PRIVATE INVALID URL", "LLM_API_KEY": "synthetic"})

    def invalid_vector():
        return load_vector_settings({"QDRANT_COLLECTION": "PRIVATE INVALID NAME", "EMBEDDING_DIMENSION": "2"})

    monkeypatch.setattr(ingest, "load_gateway_settings", invalid_gateway)
    result = asyncio.run(ingest.execute_ingestion([]))
    assert result["failures"][0]["variables"] == ["LLM_BASE_URL"]
    monkeypatch.setattr(check_retrieval, "load_vector_settings", invalid_vector)
    assert check_retrieval.main(["--execute", "--gateway-verified"]) == 1
    output = capsys.readouterr().out
    assert json.loads(output)["invalid_variables"] == ["QDRANT_COLLECTION"]
    assert "PRIVATE" not in output and "PRIVATE" not in json.dumps(result)
