"""Coleta opt-in com RAG existente; julgamento humano separado, sem LLM avaliador."""

import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import inspect
import json
import logging
import os
from pathlib import Path
import tempfile
from typing import Any
from uuid import uuid4

import httpx
from openai import APIConnectionError, APIError, APIStatusError, APITimeoutError, AsyncOpenAI
from qdrant_client import AsyncQdrantClient

from app.config import EXPECTED_DOCUMENTS, RAW_PDF_DIR, GatewaySettings, VectorSettings, load_gateway_settings, load_vector_settings
from app.gateway import GatewayContractError, create_gateway_client
from app.ingestion import extract_pages
from app.prompts import GENERATION_INSTRUCTIONS, INSUFFICIENT_CONTEXT, build_context, build_messages
from app.rag import collect_answer, open_answer, retrieve_chunks
from app.vector_store import BaseUnavailable, create_vector_client, check_ready, collection_contract, validate_collection
from scripts.check_retrieval import load_cases

ROOT = Path(__file__).resolve().parent.parent
PRIVATE_ROOT = ROOT / "data" / "evals"
BEHAVIOR_PATH = ROOT / "evals" / "behavior.json"
GATEWAY_CONTRACT_CODES = {
    "embedding_response_invalid", "embedding_count_mismatch", "embedding_indices_invalid",
    "embedding_vector_invalid", "embedding_dimension_mismatch", "chat_choices_invalid",
    "chat_sequence_invalid", "chat_content_invalid", "chat_finish_reason_invalid",
    "chat_missing_finish_reason", "chat_response_invalid", "chat_completion_invalid",
}
FAILURE_CODES = GATEWAY_CONTRACT_CODES | {
    "gateway_timeout", "gateway_connection_failed", "gateway_contract_invalid",
    "gateway_response_invalid", "base_unavailable", "evaluation_case_failed", "evaluation_storage_failed",
} | {f"gateway_http_{status}" for status in range(400, 600)}
FAILURE_STAGES = {"retrieval", "preparation", "generation", "persistence"}
SAFE_ERRORS = {
    "private_run_directory_required", "private_path_symlink", "references_already_exist_use_new_run",
    "unsupported_case_requires_review", "references_suite_changed_use_new_run", "evaluation_suite_changed_use_new_run",
    "reference_documents_differ_from_collection", "embedding_dimension_configuration_mismatch", "collection_changed_use_new_run",
    "default_model_changed_use_new_run", "complete_retrieval_phase_first", "collect_default_model_first",
    "generation_changed_repeat_affected_cases_explicitly", "evaluation_case_failed",
} | FAILURE_CODES


def failure_code(error: Exception) -> str:
    """Classifica sem copiar mensagens, corpos, URLs ou cabeçalhos externos."""
    if isinstance(error, (TimeoutError, APITimeoutError, httpx.TimeoutException)):
        return "gateway_timeout"
    if isinstance(error, APIStatusError):
        status = error.status_code
        return f"gateway_http_{status}" if type(status) is int and 400 <= status < 600 else "gateway_response_invalid"
    if isinstance(error, (APIConnectionError, httpx.TransportError)):
        return "gateway_connection_failed"
    if isinstance(error, GatewayContractError):
        # Mesmo uma exceção local só pode publicar códigos explicitamente conhecidos.
        code = error.args[0] if len(error.args) == 1 else None
        return code if isinstance(code, str) and code in GATEWAY_CONTRACT_CODES else "gateway_contract_invalid"
    if isinstance(error, (APIError, json.JSONDecodeError)):
        return "gateway_response_invalid"
    if isinstance(error, BaseUnavailable):
        return "base_unavailable"
    if isinstance(error, OSError):
        return "evaluation_storage_failed"
    return "evaluation_case_failed"


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def suite() -> tuple[list[dict[str, Any]], list[str]]:
    behavior = json.loads(BEHAVIOR_PATH.read_text(encoding="utf-8"))
    cases = [{**case, "kind": "answerable"} for case in load_cases()] + behavior["cases"]
    if (len(cases) != 12 or len({case["id"] for case in cases}) != 12
            or [case["kind"] for case in cases].count("unsupported") != 2
            or [case["kind"] for case in cases].count("injection") != 1
            or [case["kind"] for case in cases].count("clinical") != 1
            or any(not 1 <= len(case["question"].strip()) <= 1500 for case in cases)
            or len(set(behavior["alternate_cases"])) != 2
            or not set(behavior["alternate_cases"]) <= {c["id"] for c in cases[:8]}):
        raise ValueError("evaluation_cases_invalid")
    return cases, behavior["alternate_cases"]


def private_dir(path: Path) -> Path:
    """Recusa saídas públicas e links; relatórios só existem no diretório ignorado."""
    path = Path(os.path.abspath(path))
    if not path.is_relative_to(PRIVATE_ROOT) or path == PRIVATE_ROOT:
        raise ValueError("private_run_directory_required")
    if any(parent.is_symlink() for parent in (path, *path.parents)):
        raise ValueError("private_path_symlink")
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.chmod(0o700)
    return path


def save(path: Path, value: object) -> None:
    """Substituição atômica em modo 0600 evita perder resultados na retomada."""
    private_dir(path.parent)
    if path.is_symlink():
        raise ValueError("private_path_symlink")
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".eval-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            json.dump(value, output, ensure_ascii=False, indent=2)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def read(path: Path) -> dict[str, Any]:
    if path.is_symlink():
        raise ValueError("private_path_symlink")
    return json.loads(path.read_text(encoding="utf-8"))


def prepare_references(run: Path, cases: list[dict[str, Any]]) -> None:
    """Lê PDFs locais sem modelos; guarda evidências integrais somente em data/."""
    target = run / "references.json"
    if target.exists() or (run / "state.json").exists():
        raise ValueError("references_already_exist_use_new_run")
    pages_by_name = {name: extract_pages(RAW_PDF_DIR / name) for name in EXPECTED_DOCUMENTS}
    hashes = {name: hashlib.sha256((RAW_PDF_DIR / name).read_bytes()).hexdigest() for name in EXPECTED_DOCUMENTS}
    evidence = {}
    for case in cases:
        pages = [pages_by_name[source["document"]][source["page"] - 1] for source in case["expected_sources"]]
        absent = {
            term: sum(term.casefold() in page["text"].casefold() for doc in pages_by_name.values() for page in doc)
            for term in case.get("absence_terms", [])
        }
        if any(absent.values()):
            raise ValueError("unsupported_case_requires_review")
        evidence[case["id"]] = {"pages": pages, "absence_page_counts": absent}
    save(target, {"created_at": now(), "suite_hash": digest(cases), "document_hashes": hashes,
                  "method": "Extração textual; revisão visual geral pendente.", "cases": evidence})


def load_state(run: Path, cases: list[dict[str, Any]]) -> dict[str, Any]:
    refs = read(run / "references.json")
    if refs["suite_hash"] != digest(cases):
        raise ValueError("references_suite_changed_use_new_run")
    state = read(run / "state.json") if (run / "state.json").exists() else {
        "created_at": now(), "suite_hash": digest(cases), "contexts": {}, "answers": [],
    }
    if state["suite_hash"] != digest(cases):
        raise ValueError("evaluation_suite_changed_use_new_run")
    return state


async def preflight(
    store: AsyncQdrantClient, vector: VectorSettings, gateway: GatewaySettings,
    references: dict[str, Any], state: dict[str, Any],
) -> None:
    await check_ready(store, vector)
    manifest = await validate_collection(store, vector)
    if {d["document_name"]: d["document_hash"] for d in manifest} != references["document_hashes"]:
        raise ValueError("reference_documents_differ_from_collection")
    if vector.dimension != gateway.embedding_dimension:
        raise ValueError("embedding_dimension_configuration_mismatch")
    # URLs/chaves não entram no registro. Trocar coleção/contrato invalida o cache.
    signature = digest({"contract": collection_contract(vector), "manifest": manifest, "collection": vector.collection,
                        "context_formatter": inspect.getsource(build_context)})
    if state.get("retrieval_signature", signature) != signature:
        raise ValueError("collection_changed_use_new_run")
    state["retrieval_signature"] = signature


async def context_for(
    case: dict[str, Any], state: dict[str, Any], store: AsyncQdrantClient, vector: VectorSettings,
    gateway: AsyncOpenAI, settings: GatewaySettings,
) -> dict[str, Any]:
    if case["id"] not in state["contexts"]:
        hits = await retrieve_chunks(case["question"], store, vector, gateway, settings)
        context, sources = build_context(hits)
        locations = [{"document": h["chunk"]["document_name"], "page": h["chunk"]["page"]} for h in hits]
        rank = next((i for i, source in enumerate(locations, 1) if source in case["expected_sources"]), None)
        state["contexts"][case["id"]] = {
            "context": context, "sources": [source.model_dump() for source in sources],
            "hits": hits, "expected_source_rank": rank, "collected_at": now(),
        }
    return state["contexts"][case["id"]]


def review_template(case: dict[str, Any]) -> dict[str, str]:
    return {"reviewer": "", "reviewed_at": "", "notes": "",
            "grounding": "pending", "references": "pending", "completeness": "pending",
            "limits": "pending" if case["kind"] in {"unsupported", "clinical"} else "n/a",
            "security": "pending" if case["kind"] == "injection" else "n/a"}


def generation_signature(tokens: int | None) -> str:
    return digest({"instructions": GENERATION_INSTRUCTIONS, "max_output_tokens": tokens,
                   "message_formatter": inspect.getsource(build_messages)})


def summary(state: dict[str, Any], cases: list[dict[str, Any]], alternate: list[str], reviews: dict[str, Any]) -> dict[str, Any]:
    ranks = [state["contexts"].get(c["id"], {}).get("expected_source_rank") for c in cases[:8]]
    retrieved = sum(c["id"] in state["contexts"] for c in cases[:8])
    hits = sum(rank is not None and rank <= 4 for rank in ranks)
    latest = {(a["model"], a["case_id"]): a for a in state["answers"]}
    default = state.get("default_model")
    other = state.get("alternate_model")
    expected = [(default, c) for c in cases] + [(other, c) for c in cases if c["id"] in alternate]
    rows = []
    for model, case in expected:
        answer = latest.get((model, case["id"]), {})
        review = reviews.get(answer.get("id"), {})
        template = review_template(case)
        axes = {k: review.get(k, "pending") for k in template if k not in {"reviewer", "reviewed_at", "notes"} and template[k] != "n/a"}
        current_signature = generation_signature(state.get("max_output_tokens"))
        if answer.get("status") != "collected" or answer.get("generation_signature") != current_signature:
            quality = "pending"
        elif "fail" in axes.values():
            quality = "failed"
        elif (all(v == "pass" for v in axes.values()) and all(review.get(k, "").strip() for k in ("reviewer", "reviewed_at", "notes"))):
            quality = "passed"
        else:
            quality = "pending"
        row = {"id": case["id"], "model": model, "collection": answer.get("status", "pending"), "review": quality, "axes": axes}
        if answer.get("status") == "failed":
            code = answer.get("error")
            row["error"] = code if isinstance(code, str) and code in FAILURE_CODES else "evaluation_case_failed"
            stage = answer.get("error_stage")
            if isinstance(stage, str) and stage in FAILURE_STAGES:
                row["error_stage"] = stage
        rows.append(row)
    quality = "failed" if any(r["review"] == "failed" for r in rows) or (retrieved == 8 and hits < 7) else "pending"
    if retrieved == 8 and hits >= 7 and all(r["review"] == "passed" for r in rows):
        quality = "passed"
    return {"retrieval": {"evaluated": retrieved, "hits_at_4": hits, "required": 7,
                          "cases": [{"id": c["id"], "expected_source_rank": rank} for c, rank in zip(cases[:8], ranks, strict=True)]},
            "quality_status": quality, "cases": rows}


async def collect(
    run: Path, cases: list[dict[str, Any]], alternate: list[str], phase: str,
    choice: str, selected: list[str] | None, repeat: bool,
    store: AsyncQdrantClient, vector: VectorSettings, gateway: AsyncOpenAI, settings: GatewaySettings,
) -> dict[str, Any]:
    state = load_state(run, cases)
    await preflight(store, vector, settings, read(run / "references.json"), state)
    default = settings.default_chat_model
    other = next(model for model in settings.chat_models if model != default)
    if state.get("default_model", default) != default:
        raise ValueError("default_model_changed_use_new_run")
    state.update(default_model=default, alternate_model=other, max_output_tokens=settings.max_output_tokens)
    reviews = read(run / "reviews.json") if (run / "reviews.json").exists() else {}
    chosen = cases[:8] if phase == "retrieval" else [c for c in cases if c["id"] in (selected or (alternate if choice == "alternate" else [c["id"] for c in cases]))]
    if phase == "answers" and any(c["id"] not in state["contexts"] for c in cases[:8]):
        raise ValueError("complete_retrieval_phase_first")
    if phase == "answers" and choice == "alternate" and any(
        not any(a["case_id"] == c["id"] and a["model"] == default and a["status"] == "collected" for a in state["answers"]) for c in cases
    ):
        raise ValueError("collect_default_model_first")
    model = default if choice == "default" else other
    signature = generation_signature(settings.max_output_tokens)
    for case in chosen:
        prior = [a for a in state["answers"] if a["case_id"] == case["id"] and a["model"] == model]
        if phase == "answers" and prior and not repeat:
            if prior[-1]["generation_signature"] != signature:
                raise ValueError("generation_changed_repeat_affected_cases_explicitly")
            continue  # Falhas também exigem repetição explícita; nunca retentar automaticamente.
        record = None
        if phase == "answers":
            record = {"id": str(uuid4()), "case_id": case["id"], "model": model,
                      "generation_signature": signature, "created_at": now(), "status": "started"}
            state["answers"].append(record)
        # Persiste a intenção antes do consumo: interrupção não refaz geração silenciosamente.
        save(run / "state.json", state)
        stage = "retrieval"
        try:
            async with asyncio.timeout(settings.request_timeout_seconds):
                prepared = await context_for(case, state, store, vector, gateway, settings)
                stage = "persistence"
                save(run / "state.json", state)
                if record is not None:
                    stage = "preparation"
                    messages = build_messages(case["question"], prepared["context"])
                    if prepared["sources"]:
                        stage = "generation"
                        async with open_answer(gateway, settings, model, messages, request_id="evaluation") as parts:
                            answer, reason = await collect_answer(parts)
                    else:
                        answer, reason = INSUFFICIENT_CONTEXT, "insufficient_context"
                    stage = "persistence"
                    record.update(status="collected", answer=answer, finish_reason=reason,
                                  messages=messages, sources=prepared["sources"])
                    reviews[record["id"]] = review_template(case)
                    save(run / "reviews.json", reviews)
        except Exception as exc:
            code = failure_code(exc)
            if record is not None:
                record.update(status="failed", error=code, error_stage=stage)
            save(run / "state.json", state)
            raise ValueError(code) from None
        save(run / "state.json", state)
    return summary(state, cases, alternate, reviews)


async def execute(args: argparse.Namespace, run: Path, cases: list[dict[str, Any]], alternate: list[str]) -> dict[str, Any]:
    # Configuração privada só é lida após --execute e confirmações explícitas.
    vector, settings = load_vector_settings(), load_gateway_settings()
    store = create_vector_client(vector)
    try:
        async with create_gateway_client(settings) as gateway:
            return await collect(run, cases, alternate, args.phase, args.model, args.cases, args.repeat,
                                 store, vector, gateway, settings)
    finally:
        await store.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=["references", "retrieval", "answers", "summary"], default="retrieval")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--gateway-verified", action="store_true")
    parser.add_argument("--extraction-reviewed", action="store_true")
    parser.add_argument("--run-dir", type=Path, default=PRIVATE_ROOT / "stage6")
    parser.add_argument("--model", choices=["default", "alternate"], default="default")
    parser.add_argument("--cases", nargs="+")
    parser.add_argument("--repeat", action="store_true")
    args = parser.parse_args(argv)
    cases, alternate = suite()
    if args.phase != "answers" and (args.cases or args.model != "default"):
        parser.error("--cases e --model só se aplicam à fase answers.")
    allowed = alternate if args.model == "alternate" else [c["id"] for c in cases]
    if args.cases and (len(set(args.cases)) != len(args.cases) or not set(args.cases) <= set(allowed)):
        parser.error("Seleção inválida de casos.")
    if args.repeat and (not args.cases or args.phase != "answers"):
        parser.error("--repeat exige --phase answers e --cases explícitos.")
    maximum = len(args.cases or allowed)
    budget = {"references": (0, 0), "summary": (0, 0), "retrieval": (8, 0),
              "answers": (0 if args.model == "alternate" else min(4, maximum), maximum)}[args.phase]
    if not args.execute:
        print(json.dumps({"mode": "plan", "phase": args.phase, "max_embedding_calls": budget[0],
                          "max_generation_calls": budget[1], "full_suite": {"embeddings": 12, "generations": 14},
                          "note": "Cache reduz consumo; referências/summary são locais. Gateway exige autorização específica."}, ensure_ascii=False))
        return 0
    if args.phase in {"retrieval", "answers"} and not (args.gateway_verified and args.extraction_reviewed):
        parser.error("Execução com gateway exige --gateway-verified e --extraction-reviewed após autorização.")
    for name in ("openai", "httpx", "httpcore", "qdrant_client"):
        logging.getLogger(name).setLevel(logging.CRITICAL)
    try:
        run = private_dir(args.run_dir)
        if args.phase == "references":
            prepare_references(run, cases)
            report = {"status": "references_prepared", "model_calls": 0}
        elif args.phase == "summary":
            report = summary(load_state(run, cases), cases, alternate, read(run / "reviews.json") if (run / "reviews.json").exists() else {})
        else:
            report = asyncio.run(execute(args, run, cases, alternate))
    except Exception as exc:
        code = exc.args[0] if len(exc.args) == 1 and isinstance(exc.args[0], str) and exc.args[0] in SAFE_ERRORS else "evaluation_failed_check_private_state_and_prerequisites"
        print(json.dumps({"status": "failed", "error": code}))
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.phase == "retrieval":
        return 0 if report["retrieval"]["evaluated"] == 8 and report["retrieval"]["hits_at_4"] >= 7 else 1
    if args.phase == "summary":
        return 0 if report["quality_status"] == "passed" else 1
    if args.phase == "answers":
        state = load_state(run, cases)
        selected_model = state["default_model" if args.model == "default" else "alternate_model"]
        relevant = [r for r in report["cases"] if r["model"] == selected_model and (not args.cases or r["id"] in args.cases)]
        return 0 if relevant and all(r["collection"] == "collected" for r in relevant) else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
