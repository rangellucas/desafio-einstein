"""API mínima; o ciclo de vida compartilha somente o cliente vetorial."""

from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.config import load_vector_settings
from app.vector_store import check_ready, create_vector_client


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    application.state.vector_client = None
    application.state.vector_settings = None
    try:
        settings = load_vector_settings()
        if settings.url or settings.path.is_dir():
            application.state.vector_client = create_vector_client(settings)
            application.state.vector_settings = settings
    except Exception:
        # /health permanece útil mesmo se configuração, disco ou lock falharem.
        pass
    try:
        yield
    finally:
        if application.state.vector_client is not None:
            await application.state.vector_client.close()

app = FastAPI(
    title="Consulta educacional sobre Saúde Mental",
    description="Consulta educacional: processo e prontidão da base. Chat ainda não disponível.",
    version="0.3.0", lifespan=lifespan,
)


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
