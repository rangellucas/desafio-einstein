"""Preparação local por página. Sem gateway, embeddings ou armazenamento vetorial."""

import re
from pathlib import Path
from typing import TypedDict

from pypdf import PdfReader

from app.config import CHUNK_OVERLAP, CHUNK_SIZE, SHORT_PAGE_CHARS


class Page(TypedDict):
    document_name: str
    page: int
    text: str


class Chunk(Page):
    chunk_index: int
    start: int
    end: int


class PageStats(TypedDict):
    page: int
    characters: int
    chunks: int
    suspicious_characters: int


class DocumentReport(TypedDict):
    document_name: str
    total_pages: int
    total_chunks: int
    empty_pages: list[int]
    short_pages: list[int]
    suspicious_pages: list[int]
    sample_pages: list[int]
    pages: list[PageStats]


def clean_text(text: str) -> str:
    """Normaliza apenas espaços; preserva pontuação, acentos e negações."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[^\S\n]+", " ", text)
    text = "\n".join(line.strip() for line in text.split("\n"))
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def extract_pages(path: Path) -> list[Page]:
    """Lê um PDF e fecha o arquivo; páginas vazias mantêm sua posição física."""
    with path.open("rb") as source:
        reader = PdfReader(source)
        if reader.is_encrypted:
            raise ValueError("PDF criptografado exige revisão manual.")
        return [
            Page(
                document_name=path.name,
                page=number,
                text=clean_text(page.extract_text() or ""),
            )
            for number, page in enumerate(reader.pages, start=1)
        ]


def split_page(
    page: Page,
    max_chars: int = CHUNK_SIZE,
    overlap: int = CHUNK_OVERLAP,
) -> list[Chunk]:
    """Recorta a página sem perder caracteres; offsets referem-se ao texto limpo."""
    if max_chars <= 0 or not 0 <= overlap < max_chars:
        raise ValueError("Exige max_chars > 0 e 0 <= overlap < max_chars.")
    text = page["text"]
    chunks: list[Chunk] = []
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        if end < len(text):
            # Só aceita limites que garantem avanço após aplicar a sobreposição.
            lower = max(start + overlap + 1, start + max_chars // 2)
            paragraph = text.rfind("\n\n", lower, end)
            if paragraph != -1:
                end = paragraph + 2
            else:
                sentences = list(re.finditer(r"[.!?](?:\s+)", text[lower:end]))
                if sentences:
                    end = lower + sentences[-1].end()
        chunks.append(
            Chunk(
                document_name=page["document_name"],
                page=page["page"],
                text=text[start:end],
                chunk_index=len(chunks),
                start=start,
                end=end,
            )
        )
        if end == len(text):
            break
        start = end - overlap
    return chunks


def inspect_document(path: Path) -> DocumentReport:
    """Resume a extração sem exportar o conteúdo privado para o relatório."""
    pages = extract_pages(path)
    stats = [
        PageStats(
            page=page["page"],
            characters=len(page["text"]),
            chunks=len(split_page(page)),
            suspicious_characters=sum(page["text"].count(char) for char in ("\x00", "\ufffd")),
        )
        for page in pages
    ]
    count = len(pages)
    return DocumentReport(
        document_name=path.name,
        total_pages=count,
        total_chunks=sum(page["chunks"] for page in stats),
        empty_pages=[page["page"] for page in stats if page["characters"] == 0],
        short_pages=[
            page["page"] for page in stats if 0 < page["characters"] < SHORT_PAGE_CHARS
        ],
        suspicious_pages=[page["page"] for page in stats if page["suspicious_characters"]],
        sample_pages=sorted({1, (count + 1) // 2, count}) if count else [],
        pages=stats,
    )
