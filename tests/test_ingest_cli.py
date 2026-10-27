import json
from collections.abc import Callable
from pathlib import Path

import pytest

from app.config import EXPECTED_DOCUMENTS
from scripts.ingest import main


def test_dry_run_counts_four_pdfs_without_writing_or_printing_text(
    tmp_path: Path, make_pdf: Callable[[Path, list[str]], Path], capsys: pytest.CaptureFixture[str],
) -> None:
    for name in EXPECTED_DOCUMENTS:
        make_pdf(tmp_path / name, ["CONTEUDO_SINTETICO_NAO_EXPORTAR", ""])
    before = {path: path.read_bytes() for path in tmp_path.iterdir()}
    assert main(["--dry-run", "--input-dir", str(tmp_path)]) == 0
    output = capsys.readouterr().out
    report = json.loads(output)
    assert report["processed_documents"] == 4
    assert report["total_chunks"] == 4
    assert report["failures"] == []
    assert report["manual_review_required"] is True
    assert all(doc["empty_pages"] == [2] for doc in report["documents"])
    assert "CONTEUDO_SINTETICO_NAO_EXPORTAR" not in output
    assert {path: path.read_bytes() for path in tmp_path.iterdir()} == before


def test_missing_pdfs_are_failures(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--dry-run", "--input-dir", str(tmp_path)]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["processed_documents"] == 0
    assert len(report["failures"]) == 4
    assert {item["code"] for item in report["failures"]} == {"missing_file"}


def test_bad_pdf_does_not_hide_other_results(
    tmp_path: Path, make_pdf: Callable[[Path, list[str]], Path], capsys: pytest.CaptureFixture[str],
) -> None:
    for name in EXPECTED_DOCUMENTS[1:]:
        make_pdf(tmp_path / name, ["Texto."])
    (tmp_path / EXPECTED_DOCUMENTS[0]).write_bytes(b"not a PDF")
    assert main(["--dry-run", "--input-dir", str(tmp_path)]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["processed_documents"] == 3
    assert report["failures"] == [{
        "document_name": EXPECTED_DOCUMENTS[0], "code": "pdf_extraction_failed",
    }]


def test_normal_ingestion_is_unavailable(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as error:
        main([])
    assert error.value.code == 2
    assert "somente --dry-run" in capsys.readouterr().err
