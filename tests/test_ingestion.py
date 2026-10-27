from collections.abc import Callable
from pathlib import Path

import pytest
from pypdf import PdfWriter

from app.ingestion import Page, clean_text, extract_pages, inspect_document, split_page


def test_cleaning_preserves_meaning_and_paragraphs() -> None:
    raw = " \tNão  é diagnóstico!\r\n Cuidado: atenção à saúde.\r\n\r\n\r\n Não prescrever. "
    assert clean_text(raw) == "Não é diagnóstico!\nCuidado: atenção à saúde.\n\nNão prescrever."
    assert clean_text(clean_text(raw)) == clean_text(raw)


@pytest.mark.parametrize("text", [
    "",
    "Não é diagnóstico.",
    "x" * 4501,
    "Não é diagnóstico. Atenção à saúde!\n\nOutro parágrafo. " * 100,
])
@pytest.mark.parametrize("max_chars,overlap", [(1200, 200), (11, 0), (11, 10), (1, 0)])
def test_splitting_preserves_all_text_and_references(text: str, max_chars: int, overlap: int) -> None:
    page = Page(document_name="sintético.pdf", page=7, text=clean_text(text))
    chunks = split_page(page, max_chars=max_chars, overlap=overlap)
    rebuilt = ""
    previous_end = 0
    for index, chunk in enumerate(chunks):
        assert chunk["document_name"] == "sintético.pdf"
        assert chunk["page"] == 7
        assert chunk["chunk_index"] == index
        assert 0 < len(chunk["text"]) <= max_chars
        assert chunk["text"] == page["text"][chunk["start"]:chunk["end"]]
        if index:
            assert chunk["start"] == previous_end - overlap
            assert chunk["start"] > chunks[index - 1]["start"]
            if overlap:
                assert chunk["text"][:overlap] == chunks[index - 1]["text"][-overlap:]
        rebuilt += chunk["text"][previous_end - chunk["start"]:]
        previous_end = chunk["end"]
    assert rebuilt == page["text"]


@pytest.mark.parametrize("max_chars,overlap", [(0, 0), (-1, 0), (10, -1), (10, 10), (10, 11)])
def test_invalid_split_parameters_fail(max_chars: int, overlap: int) -> None:
    with pytest.raises(ValueError, match="max_chars"):
        split_page(Page(document_name="teste.pdf", page=1, text=""), max_chars, overlap)


@pytest.mark.parametrize("separator", ["\n\n", ". "])
def test_prefers_paragraph_or_sentence_boundary(separator: str) -> None:
    text = "a" * 25 + separator + "b" * 40
    chunks = split_page(Page(document_name="teste.pdf", page=1, text=text), 40, 5)
    assert chunks[0]["end"] == 25 + len(separator)


def test_pdf_extraction_keeps_physical_pages_including_blank(
    tmp_path: Path, make_pdf: Callable[[Path, list[str]], Path],
) -> None:
    path = make_pdf(tmp_path / "sintetico.pdf", ["Primeira pagina.", "", "Terceira pagina."])
    pages = extract_pages(path)
    assert [page["page"] for page in pages] == [1, 2, 3]
    assert [page["text"] for page in pages] == ["Primeira pagina.", "", "Terceira pagina."]
    chunks = [chunk for page in pages for chunk in split_page(page)]
    assert [chunk["page"] for chunk in chunks] == [1, 3]
    assert all(chunk["document_name"] == path.name for chunk in chunks)
    report = inspect_document(path)
    assert report["empty_pages"] == [2]
    assert report["short_pages"] == [1, 3]
    assert report["sample_pages"] == [1, 2, 3]
    assert report["total_chunks"] == 2


def test_report_flags_broken_glyphs_without_rewriting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = Page(document_name="teste.pdf", page=1, text="N\x00o apagar \ufffd.")
    monkeypatch.setattr("app.ingestion.extract_pages", lambda path: [page])
    report = inspect_document(Path("teste.pdf"))
    assert report["suspicious_pages"] == [1]
    assert report["pages"][0]["suspicious_characters"] == 2
    assert split_page(page)[0]["text"] == page["text"]


def test_encrypted_pdf_requires_manual_review(tmp_path: Path) -> None:
    path = tmp_path / "encrypted.pdf"
    with PdfWriter() as writer:
        writer.add_blank_page(width=100, height=100)
        writer.encrypt("synthetic-test-password")
        writer.write(path)
    with pytest.raises(ValueError, match="criptografado"):
        extract_pages(path)
