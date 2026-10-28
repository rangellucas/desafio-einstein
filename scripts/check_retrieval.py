"""Avaliação opt-in: oito embeddings de pergunta, sem geração e sem imprimir texto."""

import argparse
import asyncio
import json
import logging
from pathlib import Path
from typing import TypedDict

from openai import AsyncOpenAI
from pydantic import ValidationError
from qdrant_client import AsyncQdrantClient

from app.config import EXPECTED_DOCUMENTS, GatewaySettings, VectorSettings, invalid_variable_names, load_gateway_settings, load_vector_settings
from app.gateway import create_gateway_client
from app.rag import retrieve_chunks
from app.vector_store import check_ready, create_vector_client

CASES_PATH = Path(__file__).resolve().parent.parent / "evals" / "retrieval.json"


class ExpectedSource(TypedDict):
    document: str
    page: int


class RetrievalCase(TypedDict):
    id: str
    question: str
    expected_sources: list[ExpectedSource]
    minimum_elements: list[str]
    expected_behavior: str


def load_cases() -> list[RetrievalCase]:
    cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))["cases"]
    if (len(cases) != 8 or len({c["id"] for c in cases}) != 8
            or any(sum(any(s["document"] == name for s in c["expected_sources"]) for c in cases) != 2
                   for name in EXPECTED_DOCUMENTS)):
        raise ValueError("retrieval_cases_invalid")
    return cases


async def check_retrieval(
    store: AsyncQdrantClient, settings: VectorSettings, gateway: AsyncOpenAI,
    gateway_settings: GatewaySettings, cases: list[RetrievalCase],
) -> dict[str, object]:
    report: dict[str, object] = {
        "status": "failed", "calls_attempted": 0, "max_calls": len(cases),
        "hits_at_4": 0, "required_hits": 7, "cases": [], "error": None,
    }
    try:
        # Impede qualquer consumo de modelos se a base estiver parcial ou incompatível.
        await check_ready(store, settings)
        for case in cases:
            report["calls_attempted"] += 1
            hits = await retrieve_chunks(case["question"], store, settings, gateway, gateway_settings)
            sources = [{"document": h["chunk"]["document_name"], "page": h["chunk"]["page"]} for h in hits]
            rank = next((i for i, source in enumerate(sources, 1) if source in case["expected_sources"]), None)
            report["hits_at_4"] += rank is not None
            report["cases"].append({"id": case["id"], "expected_source_rank": rank, "sources": sources})
        report["status"] = "passed" if report["hits_at_4"] >= 7 else "below_target"
    except Exception:
        report["error"] = "retrieval_check_failed"
    return report


async def execute_check() -> dict[str, object]:
    try:
        settings = load_vector_settings()
    except ValidationError as exc:
        return {"status": "invalid_config", "invalid_variables": invalid_variable_names(exc, "vector")}
    try:
        gateway_settings = load_gateway_settings()
    except ValidationError as exc:
        return {"status": "invalid_config", "invalid_variables": invalid_variable_names(exc, "gateway")}
    store = create_vector_client(settings)
    try:
        async with create_gateway_client(gateway_settings) as gateway:
            return await check_retrieval(store, settings, gateway, gateway_settings, load_cases())
    finally:
        await store.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Avaliar recuperação das oito perguntas, sem geração.")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--gateway-verified", action="store_true")
    args = parser.parse_args(argv)
    if not args.execute:
        print(json.dumps({
            "mode": "plan", "max_embedding_calls": 8, "generation_calls": 0,
            "max_qdrant_operations": 71, "input_type": "search_query",
            "note": "Após autorização e ingestão completa: --execute --gateway-verified.",
        }, ensure_ascii=False))
        return 0
    if not args.gateway_verified:
        parser.error("--execute exige --gateway-verified; confirme o contrato real primeiro.")
    for name in ("openai", "httpx", "httpcore", "qdrant_client"):
        logging.getLogger(name).setLevel(logging.CRITICAL)
    try:
        report = asyncio.run(execute_check())
    except Exception:
        report = {"status": "failed", "error": "retrieval_configuration_or_connection_failed"}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
