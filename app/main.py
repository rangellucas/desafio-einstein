"""API mínima; importar ou iniciar a aplicação não processa documentos."""

from fastapi import FastAPI

app = FastAPI(
    title="Consulta educacional sobre Saúde Mental",
    description="Etapa 1: verificação do processo. Consultas RAG ainda não disponíveis.",
    version="0.1.0",
)


@app.get("/health", summary="Verificar se o processo responde")
def health() -> dict[str, str]:
    """Não verifica a base nem consome serviços externos."""
    return {"status": "ok"}
