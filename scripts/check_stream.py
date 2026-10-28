"""Cliente POST/SSE opt-in; relata tempos e metadados, sem imprimir conteúdo."""

import argparse
from collections.abc import Callable
from datetime import datetime, timezone
import json
import os
from time import perf_counter
from urllib.parse import urlsplit

import httpx
from pydantic import ValidationError

from app.config import CHAT_MODELS
from app.schemas import DeltaEvent, DoneEvent, ErrorDetail, SourcesEvent


class StreamCheckError(ValueError):
    """Erro público fixo; não contém corpo HTTP, pergunta ou credenciais."""


def check_stream(
    client: httpx.Client, url: str, question: str, model: str | None = None,
    *, token: str | None = None, report: Callable[[str], None] = print,
) -> dict[str, object]:
    started = perf_counter()
    first_delta = None
    terminal = None
    event_name = ""
    data: list[str] = []
    names: list[str] = []
    headers = {"Accept": "text/event-stream"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = {"question": question}
    if model is not None:
        body["model"] = model
    with client.stream("POST", url.rstrip("/") + "/chat/stream", json=body, headers=headers) as response:
        if response.status_code != 200:
            raise StreamCheckError(f"http_status_{response.status_code}")
        if response.headers.get("content-type", "").split(";")[0] != "text/event-stream":
            raise StreamCheckError("invalid_content_type")
        for line in response.iter_lines():
            if line.startswith(":"):
                continue
            if line.startswith("event:"):
                event_name = line[6:].strip()
            elif line.startswith("data:"):
                data.append(line[5:].lstrip(" "))
            elif line == "" and data:
                now = perf_counter() - started
                if terminal is not None:
                    raise StreamCheckError("event_after_terminal")
                try:
                    payload = json.loads("\n".join(data))
                    if event_name == "sources" and not names:
                        SourcesEvent.model_validate(payload)
                    elif event_name == "delta" and names:
                        delta = DeltaEvent.model_validate(payload)
                        if not delta.text:
                            raise StreamCheckError("empty_delta")
                        if first_delta is None:
                            first_delta = now
                    elif event_name == "done" and names and first_delta is not None:
                        DoneEvent.model_validate(payload)
                        terminal = now
                    elif event_name == "error":
                        ErrorDetail.model_validate(payload)
                    else:
                        raise StreamCheckError("invalid_event_order")
                except (ValidationError, json.JSONDecodeError):
                    raise StreamCheckError("invalid_event_payload") from None
                names.append(event_name)
                instant = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
                report(f"{instant} +{now:.3f}s event={event_name}")
                if event_name == "error":
                    raise StreamCheckError("sse_error")
                data, event_name = [], ""
        if data or terminal is None or first_delta is None:
            raise StreamCheckError("incomplete_stream")
    result = {
        "events": names, "first_delta_seconds": first_delta, "terminal_seconds": terminal,
        "delta_before_done": first_delta < terminal,
    }
    report(json.dumps(result))
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="Autoriza uma consulta HTTP; sem esta opção só mostra o plano.")
    parser.add_argument("--url", default="http://127.0.0.1:8000", help="URL base da API, sem credenciais/query.")
    parser.add_argument("--question", default="Como a atenção primária participa do cuidado em saúde mental?")
    parser.add_argument("--model", choices=CHAT_MODELS)
    parser.add_argument("--timeout", type=float, default=100, help="Timeout de leitura HTTP em segundos.")
    args = parser.parse_args(argv)
    url = urlsplit(args.url)
    if url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password or url.query or url.fragment:
        parser.error("Use uma URL HTTP(S) base sem credenciais, query ou fragmento.")
    if not args.execute:
        print("Plano: 1 POST /chat/stream; até 1 embedding de pergunta e 1 geração limitada pela API. Nenhuma chamada executada.")
        return 0
    print("Execução: 1 consulta HTTP; até 2 chamadas de modelos (1 embedding e 1 geração), sem repetição.")
    try:
        with httpx.Client(timeout=args.timeout, follow_redirects=False, trust_env=False) as client:
            result = check_stream(client, args.url, args.question, args.model, token=os.environ.get("API_ACCESS_TOKEN"))
        return 0 if result["delta_before_done"] else 1
    except (StreamCheckError, httpx.HTTPError, ValueError) as error:
        # Nunca exibir URLs, headers, corpos ou mensagens internas de transporte.
        code = str(error) if isinstance(error, StreamCheckError) else "http_stream_failed"
        print(f"Verificação falhou: {code}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
