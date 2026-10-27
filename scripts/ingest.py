"""Execute da raiz: python -m scripts.ingest --dry-run."""

import argparse
import json
from pathlib import Path

from pypdf.errors import PyPdfError

from app.config import (
    CHUNK_OVERLAP,
    CHUNK_SIZE,
    EXPECTED_DOCUMENTS,
    RAW_PDF_DIR,
    SHORT_PAGE_CHARS,
)
from app.ingestion import DocumentReport, inspect_document


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inspeção local dos quatro PDFs do PRD.")
    parser.add_argument("--dry-run", action="store_true", help="Extrair e dividir sem indexar.")
    parser.add_argument("--input-dir", type=Path, default=RAW_PDF_DIR)
    args = parser.parse_args(argv)
    if not args.dry_run:
        parser.error("Nesta etapa, somente --dry-run está disponível; não há indexação.")

    documents: list[DocumentReport] = []
    failures: list[dict[str, str]] = []
    for name in EXPECTED_DOCUMENTS:
        path = args.input_dir / name
        if not path.is_file():
            failures.append({"document_name": name, "code": "missing_file"})
            continue
        try:
            report = inspect_document(path)
        except (OSError, PyPdfError, ValueError):
            # Não publicar mensagens brutas do parser nem conteúdo do documento.
            failures.append({"document_name": name, "code": "pdf_extraction_failed"})
            continue
        documents.append(report)
        if report["total_pages"] == 0:
            failures.append({"document_name": name, "code": "pdf_without_pages"})

    print(json.dumps({
        "mode": "dry-run",
        "chunk_size": CHUNK_SIZE,
        "chunk_overlap": CHUNK_OVERLAP,
        "short_page_chars": SHORT_PAGE_CHARS,
        "expected_documents": len(EXPECTED_DOCUMENTS),
        "processed_documents": len(documents),
        "total_chunks": sum(doc["total_chunks"] for doc in documents),
        "documents": documents,
        "failures": failures,
        "manual_review_required": True,
    }, ensure_ascii=False, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
