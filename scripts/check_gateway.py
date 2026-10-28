"""Plano sem rede por padrão: python -m scripts.check_gateway. Opt-in: --execute."""

import argparse
import asyncio
import json
import logging
import time
from typing import TypedDict

import httpx
from openai import APIConnectionError, APIError, APIStatusError, APITimeoutError, AsyncOpenAI
from pydantic import ValidationError

from app.config import CHAT_MODELS, EMBEDDING_MODEL, GatewaySettings, load_gateway_settings
from app.gateway import InputType, GatewayContractError, create_gateway_client, embed_texts, open_chat_stream

MAX_CALLS = 4
CHECK_MAX_OUTPUT_TOKENS = 600


class CheckResult(TypedDict, total=False):
    kind: str
    model: str
    input_type: str
    dimension: int
    text_fragments: int
    characters: int
    first_text_seconds: float
    total_seconds: float
    finish_reason: str


class CheckReport(TypedDict):
    status: str
    calls_attempted: int
    max_calls: int
    output_limit: int
    checks: list[CheckResult]
    error: str | None


def planned_calls() -> list[dict[str, str]]:
    return [
        {"method": "POST", "route": "embeddings", "model": EMBEDDING_MODEL, "input_type": "search_document"},
        {"method": "POST", "route": "embeddings", "model": EMBEDDING_MODEL, "input_type": "search_query"},
        *[{"method": "POST", "route": "chat/completions", "model": model, "stream": "true"} for model in CHAT_MODELS],
    ]


async def check_gateway(client: AsyncOpenAI, settings: GatewaySettings) -> CheckReport:
    """Executa sequencialmente e interrompe na primeira falha, sem retentativas."""
    report: CheckReport = {
        "status": "failed", "calls_attempted": 0, "max_calls": MAX_CALLS,
        "output_limit": min(settings.max_output_tokens, CHECK_MAX_OUTPUT_TOKENS),
        "checks": [], "error": None,
    }
    try:
        dimension: int | None = None
        embedding_cases: tuple[tuple[InputType, str], ...] = (
            ("search_document", "Material sintético para verificar a integração de embeddings."),
            ("search_query", "Como verificar a integração de embeddings?"),
        )
        for input_type, text in embedding_cases:
            report["calls_attempted"] += 1
            # Prazo da chamada inteira, inclusive se o stream continuar enviando dados.
            async with asyncio.timeout(settings.request_timeout_seconds):
                vectors = await embed_texts(client, settings, [text], input_type)
            observed = len(vectors[0])
            report["checks"].append({
                "kind": "embedding", "model": settings.embedding_model,
                "input_type": input_type, "dimension": observed,
            })
            if dimension is not None and observed != dimension:
                raise GatewayContractError("embedding_dimension_mismatch_between_input_types")
            dimension = observed

        for model in settings.chat_models:
            report["calls_attempted"] += 1
            started = time.monotonic()
            result: CheckResult = {"kind": "chat_stream", "model": model, "text_fragments": 0, "characters": 0}
            async with asyncio.timeout(settings.request_timeout_seconds):
                async with open_chat_stream(
                    client, settings, model,
                    [{"role": "user", "content": "Responda em português com uma frase curta confirmando que recebeu esta mensagem de teste."}],
                    max_output_tokens=report["output_limit"],
                ) as parts:
                    async for part in parts:
                        if part["text"]:
                            if result["text_fragments"] == 0:
                                result["first_text_seconds"] = round(time.monotonic() - started, 4)
                            result["text_fragments"] += 1
                            result["characters"] += len(part["text"])
                        if part["finish_reason"] is not None:
                            result["finish_reason"] = part["finish_reason"]
            result["total_seconds"] = round(time.monotonic() - started, 4)
            report["checks"].append(result)
            if not result["characters"]:
                raise GatewayContractError("chat_empty_text")
            if result.get("finish_reason") != "stop":
                raise GatewayContractError("chat_not_completed")
        report["status"] = "passed"
    except GatewayContractError as exc:
        report["error"] = str(exc)
    except (APITimeoutError, TimeoutError, httpx.TimeoutException):
        report["error"] = "gateway_timeout"
    except APIStatusError as exc:
        report["error"] = f"gateway_http_{exc.status_code}"
    except (APIConnectionError, httpx.TransportError):
        report["error"] = "gateway_connection_failed"
    except (APIError, ValidationError, AttributeError, TypeError, ValueError):
        # O SDK pode rejeitar JSON/SSE inválido. Não imprimir a exceção: pode conter dados.
        report["error"] = "gateway_response_invalid"
    return report


async def execute_check(settings: GatewaySettings) -> CheckReport:
    # Um cliente reutilizado nas quatro chamadas e fechado inclusive em falhas.
    async with create_gateway_client(settings) as client:
        return await check_gateway(client, settings)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verificação opt-in do contrato do gateway; até quatro chamadas pequenas.")
    parser.add_argument("--execute", action="store_true", help="Executar chamadas reais; exige autorização prévia do responsável.")
    args = parser.parse_args(argv)
    if not args.execute:
        print(json.dumps({"mode": "plan", "max_calls": MAX_CALLS, "calls": planned_calls(),
                          "note": "Nenhuma conexão. Para executar após autorização: --execute."}, ensure_ascii=False, indent=2))
        return 0
    # Evita que OPENAI_LOG ou configuração de logs exponham corpos ou cabeçalhos.
    for name in ("openai", "httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.CRITICAL)
    try:
        settings = load_gateway_settings()
    except ValidationError as exc:
        names = {
            "base_url": "LLM_BASE_URL", "api_key": "LLM_API_KEY", "chat_models": "CHAT_MODELS",
            "default_chat_model": "DEFAULT_CHAT_MODEL", "embedding_model": "EMBEDDING_MODEL",
            "embedding_dimension": "EMBEDDING_DIMENSION", "max_output_tokens": "MAX_OUTPUT_TOKENS",
            "request_timeout_seconds": "REQUEST_TIMEOUT_SECONDS",
        }
        invalid = sorted({names.get(str(error["loc"][0]), "CHAT_MODELS/DEFAULT_CHAT_MODEL/EMBEDDING_MODEL")
                          if error["loc"] else "CHAT_MODELS/DEFAULT_CHAT_MODEL/EMBEDDING_MODEL"
                          for error in exc.errors(include_input=False, include_context=False)})
        print(json.dumps({"status": "invalid_config", "calls_attempted": 0,
                          "invalid_variables": invalid,
                          "error": "Revise as variáveis indicadas; valores omitidos por segurança."}))
        return 2
    report = asyncio.run(execute_check(settings))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
