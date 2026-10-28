"""Preparação por página e ingestão explícita, fora do ciclo de vida da API."""

import asyncio
import hashlib
import json
import re
from pathlib import Path
from typing import TypedDict
from uuid import NAMESPACE_URL, uuid5

from openai import AsyncOpenAI
from pypdf import PdfReader
from qdrant_client import AsyncQdrantClient

from app.config import (
    CHUNK_OVERLAP, CHUNK_SIZE, SHORT_PAGE_CHARS, EMBEDDING_MODEL,
    PIPELINE_VERSION, EMBEDDING_BATCH_SIZE, GatewaySettings, VectorSettings,
)
from app.gateway import embed_texts


class Page(TypedDict):
    document_name: str
    page: int
    text: str


class Chunk(Page):
    chunk_index: int
    start: int
    end: int


class IndexedChunk(Chunk):
    chunk_id: str
    document_id: str
    document_hash: str
    pipeline_version: str
    embedding_model: str


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


class IndexedDocumentReport(TypedDict):
    document_name: str
    document_hash: str
    chunks: int
    reused: int
    written: int


class IndexReport(TypedDict):
    status: str
    expected_chunks: int
    reused_chunks: int
    written_chunks: int
    calls_attempted: int
    failures: list[dict[str, object]]
    documents: list[IndexedDocumentReport]


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
    return summarize_pages(path.name, extract_pages(path))


def summarize_pages(name: str, pages: list[Page]) -> DocumentReport:
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
        document_name=name,
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


def prepare_document(path: Path) -> tuple[DocumentReport, list[IndexedChunk]]:
    """IDs cobrem conteúdo, página, posição, texto e versão; não publica o texto."""
    with path.open("rb") as source:
        document_hash = hashlib.file_digest(source, "sha256").hexdigest()
    document_id = str(uuid5(NAMESPACE_URL, path.name))
    pages = extract_pages(path)
    chunks: list[IndexedChunk] = []
    for page in pages:
        for chunk in split_page(page):
            identity = json.dumps([
                document_id, document_hash, chunk["page"], chunk["chunk_index"],
                chunk["start"], chunk["end"], PIPELINE_VERSION, CHUNK_SIZE, CHUNK_OVERLAP,
                EMBEDDING_MODEL, hashlib.sha256(chunk["text"].encode()).hexdigest(),
            ])
            chunks.append(IndexedChunk(
                **chunk, chunk_id=str(uuid5(NAMESPACE_URL, identity)),
                document_id=document_id, document_hash=document_hash,
                pipeline_version=PIPELINE_VERSION, embedding_model=EMBEDDING_MODEL,
            ))
    return summarize_pages(path.name, pages), chunks


def build_manifest(chunks: list[IndexedChunk]) -> list[dict[str, str | int]]:
    documents: dict[str, dict[str, str | int]] = {}
    for chunk in chunks:
        name = chunk["document_name"]
        if name not in documents:
            documents[name] = {
                "document_name": name, "document_hash": chunk["document_hash"], "chunks": 0,
            }
        documents[name]["chunks"] = int(documents[name]["chunks"]) + 1
    return [documents[name] for name in sorted(documents)]


async def index_chunks(
    store: AsyncQdrantClient, settings: VectorSettings, gateway: AsyncOpenAI,
    gateway_settings: GatewaySettings, chunks: list[IndexedChunk],
) -> IndexReport:
    """Consulta IDs antes de cada lote e interrompe na primeira falha; retomável."""
    # Importação local evita dependência circular entre os tipos de payload e a base.
    from app.vector_store import BaseUnavailable, ensure_collection, existing_chunks, upsert_chunks, check_ready
    from app.gateway import GatewayContractError

    if gateway_settings.embedding_dimension != settings.dimension:
        raise ValueError("embedding_dimension_configuration_mismatch")
    report: IndexReport = {
        "status": "failed", "expected_chunks": len(chunks), "reused_chunks": 0,
        "written_chunks": 0, "calls_attempted": 0, "failures": [],
        "documents": [{**item, "reused": 0, "written": 0} for item in build_manifest(chunks)],
    }
    current_batch: list[IndexedChunk] = []
    batch_start = 0
    try:
        await ensure_collection(store, settings, build_manifest(chunks))
        documents = {item["document_name"]: item for item in report["documents"]}
        for start in range(0, len(chunks), EMBEDDING_BATCH_SIZE):
            batch_start = start
            batch = chunks[start:start + EMBEDDING_BATCH_SIZE]
            current_batch = batch
            found = await existing_chunks(store, settings, batch)
            missing = [chunk for chunk in batch if chunk["chunk_id"] not in found]
            report["reused_chunks"] += len(found)
            for chunk in batch:
                if chunk["chunk_id"] in found:
                    documents[chunk["document_name"]]["reused"] += 1
            if not missing:
                continue
            report["calls_attempted"] += 1
            async with asyncio.timeout(gateway_settings.request_timeout_seconds):
                vectors = await embed_texts(
                    gateway, gateway_settings, [chunk["text"] for chunk in missing], "search_document",
                )
            await upsert_chunks(store, settings, missing, vectors)
            report["written_chunks"] += len(missing)
            for chunk in missing:
                documents[chunk["document_name"]]["written"] += 1
        await check_ready(store, settings)
        report["status"] = "passed"
    except Exception as exc:
        # Mensagens de SDKs podem conter textos, URLs e segredos. Não as propagar.
        report["failures"] = [{
            "code": str(exc) if isinstance(exc, (BaseUnavailable, GatewayContractError)) else "indexing_failed",
            "batch_start": batch_start,
            "documents": sorted({chunk["document_name"] for chunk in current_batch}),
        }]
    return report
