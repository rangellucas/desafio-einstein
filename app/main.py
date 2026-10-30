"""API JSON/SSE; clientes e capacidade compartilhados, sem ingestão."""

from contextlib import AsyncExitStack, asynccontextmanager
from collections.abc import AsyncIterator
import asyncio
import logging
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import ValidationError

from app.config import load_api_settings, load_gateway_settings, load_vector_settings
from app.gateway import create_gateway_client
from app.routes import router
from app.vector_store import check_ready, create_vector_client


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    try:
        application.state.api_settings = load_api_settings()
    except (ValidationError, ValueError):
        raise ValueError("Configuração inválida: confira modelos, API_ACCESS_TOKEN, REQUEST_TIMEOUT_SECONDS e MAX_CONCURRENT_REQUESTS.") from None
    application.state.query_slots = asyncio.BoundedSemaphore(application.state.api_settings.max_concurrent_requests)
    application.state.vector_client = None
    application.state.vector_settings = None
    application.state.gateway_client = None
    application.state.gateway_settings = None
    async with AsyncExitStack() as resources:
        try:
            settings = load_vector_settings()
            if settings.url or settings.path.is_dir():
                client = create_vector_client(settings)
                resources.push_async_callback(client.close)
                application.state.vector_client = client
                application.state.vector_settings = settings
        except Exception:
            # /health permanece útil mesmo se configuração, disco ou lock falharem.
            logging.getLogger(__name__).warning("vector_initialization_unavailable")
        try:
            gateway_settings = load_gateway_settings()
            gateway = await resources.enter_async_context(create_gateway_client(gateway_settings))
            application.state.gateway_client = gateway
            application.state.gateway_settings = gateway_settings
        except Exception:
            logging.getLogger(__name__).warning("gateway_initialization_unavailable")
        yield

app = FastAPI(
    title="Consulta educacional sobre Saúde Mental",
    description="Consulta educacional independente com respostas JSON/SSE e fontes por página física. Não realiza diagnóstico ou prescrição.",
    version="0.5.0", lifespan=lifespan,
)
app.include_router(router)


@app.get("/teste", include_in_schema=False)
def demo() -> FileResponse:
    """Demonstração pública; abrir o HTML não executa uma consulta."""
    return FileResponse(Path(__file__).resolve().parent / "static" / "demo.html", media_type="text/html")


@app.get("/health", summary="Verificar se o processo responde")
def health() -> dict[str, str]:
    """Não verifica a base nem consome serviços externos."""
    return {"status": "ok"}


@app.get("/ready", summary="Verificar a coleção sem consumir modelos", responses={503: {"description": "Base indisponível"}})
async def ready(request: Request) -> JSONResponse:
    try:
        client = request.app.state.vector_client
        if client is None:
            raise ValueError("base_not_configured")
        await check_ready(client, request.app.state.vector_settings)
    except Exception:
        return JSONResponse(status_code=503, content={"detail": {
            "code": "base_unavailable", "message": "Base indisponível para consulta.",
            "request_id": str(uuid4()),
        }})
    return JSONResponse(content={"status": "ready"})
