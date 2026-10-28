"""Parâmetros do PRD e configuração explícita do gateway, sem efeitos na importação."""

from collections.abc import Mapping
import os
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError, field_validator, model_validator

CHAT_MODELS = ("azure/gpt-5-mini", "azure/gpt-6-luna")
EMBEDDING_MODEL = "cohere/embed-v4.0"


class GatewaySettings(BaseModel):
    """Validação local; instanciar não abre conexões nem carrega arquivos .env."""

    model_config = ConfigDict(frozen=True, hide_input_in_errors=True)

    base_url: str
    api_key: SecretStr = Field(repr=False)
    chat_models: tuple[str, ...] = CHAT_MODELS
    default_chat_model: str = CHAT_MODELS[0]
    embedding_model: str = EMBEDDING_MODEL
    embedding_dimension: int | None = Field(default=None, gt=0)
    max_output_tokens: int = Field(default=600, gt=0)
    request_timeout_seconds: float = Field(default=90, gt=0, allow_inf_nan=False)

    @field_validator("base_url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        parts = urlsplit(value)
        if (parts.scheme not in {"https", "http"} or not parts.hostname
                or parts.username or parts.password or parts.query or parts.fragment):
            raise ValueError("LLM_BASE_URL deve ser uma URL HTTP(S) base sem credenciais, query ou fragmento.")
        # Também valida a porta antes de criar o cliente HTTP.
        _ = parts.port
        return value.rstrip("/") + "/"

    @field_validator("api_key")
    @classmethod
    def validate_key(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().strip():
            raise ValueError("LLM_API_KEY é obrigatória.")
        return value

    @model_validator(mode="after")
    def validate_models(self) -> "GatewaySettings":
        if len(self.chat_models) != 2 or set(self.chat_models) != set(CHAT_MODELS):
            raise ValueError("CHAT_MODELS deve conter os dois identificadores do PRD, sem duplicatas.")
        if self.default_chat_model not in self.chat_models:
            raise ValueError("DEFAULT_CHAT_MODEL deve pertencer a CHAT_MODELS.")
        if self.embedding_model != EMBEDDING_MODEL:
            raise ValueError("EMBEDDING_MODEL deve usar o identificador do PRD.")
        return self


def load_gateway_settings(environ: Mapping[str, str] | None = None) -> GatewaySettings:
    """Lê o ambiente somente quando solicitado pelo comando explícito."""
    env = os.environ if environ is None else environ
    return GatewaySettings.model_validate({
        "base_url": env.get("LLM_BASE_URL", ""),
        "api_key": SecretStr(env.get("LLM_API_KEY", "")),
        "chat_models": tuple(item.strip() for item in env.get("CHAT_MODELS", ",".join(CHAT_MODELS)).split(",")),
        "default_chat_model": env.get("DEFAULT_CHAT_MODEL", CHAT_MODELS[0]),
        "embedding_model": env.get("EMBEDDING_MODEL", EMBEDDING_MODEL),
        "embedding_dimension": env.get("EMBEDDING_DIMENSION") or None,
        "max_output_tokens": env.get("MAX_OUTPUT_TOKENS", "600"),
        "request_timeout_seconds": env.get("REQUEST_TIMEOUT_SECONDS", "90"),
    })

RAW_PDF_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"
CHUNK_SIZE = 1200
CHUNK_OVERLAP = 200
# Heurística de triagem: sinaliza para leitura humana, nunca exclui texto curto.
SHORT_PAGE_CHARS = 80

EXPECTED_DOCUMENTS = (
    "sma-u-1-ampliando-o-conceito-de-saude-mental-3tFhLD7f_0007.pdf",
    "sma-o-sujeito-a-integralidade-e-saude-mental.pdf",
    "sma-saude-mental-na-atencao-primaria-uTvcWzgG.pdf",
    "sma-desenvolvendo-os-cuidados-de-saude-mental-na-aps-kJpr4dDC 2.pdf",
)

EMBEDDING_BATCH_SIZE = 16
SEARCH_LIMIT = 4
# Alterar ao mudar extração, limpeza ou divisão; usar uma nova coleção.
PIPELINE_VERSION = "pypdf-6.21.3-pages-v1"


class VectorSettings(BaseModel):
    """Uma dimensão medida é obrigatória para abrir a base; sem valor presumido."""

    model_config = ConfigDict(frozen=True, hide_input_in_errors=True)

    url: str | None = None
    api_key: SecretStr | None = Field(default=None, repr=False)
    path: Path = Path("data/qdrant")
    collection: str = Field(min_length=1, pattern=r"^[A-Za-z0-9_-]+$")
    dimension: int = Field(gt=0)

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str | None) -> str | None:
        return GatewaySettings.validate_url(value) if value else None

    @model_validator(mode="after")
    def validate_remote(self) -> "VectorSettings":
        if self.url and (self.api_key is None or not self.api_key.get_secret_value().strip()):
            raise ValueError("QDRANT_API_KEY é obrigatória no modo remoto.")
        return self


def load_vector_settings(environ: Mapping[str, str] | None = None) -> VectorSettings:
    env = os.environ if environ is None else environ
    return VectorSettings.model_validate({
        "url": env.get("QDRANT_URL") or None,
        "api_key": SecretStr(env["QDRANT_API_KEY"]) if env.get("QDRANT_API_KEY") else None,
        "path": env.get("QDRANT_PATH") or "data/qdrant",
        "collection": env.get("QDRANT_COLLECTION", ""),
        "dimension": env.get("EMBEDDING_DIMENSION") or None,
    })


def invalid_variable_names(error: ValidationError, scope: Literal["gateway", "vector"]) -> list[str]:
    """Extrai só nomes de campos; nunca inclui inputs, contextos ou mensagens brutas."""
    names = {
        "gateway": {
            "base_url": "LLM_BASE_URL", "api_key": "LLM_API_KEY", "chat_models": "CHAT_MODELS",
            "default_chat_model": "DEFAULT_CHAT_MODEL", "embedding_model": "EMBEDDING_MODEL",
            "embedding_dimension": "EMBEDDING_DIMENSION", "max_output_tokens": "MAX_OUTPUT_TOKENS",
            "request_timeout_seconds": "REQUEST_TIMEOUT_SECONDS",
        },
        "vector": {
            "url": "QDRANT_URL", "api_key": "QDRANT_API_KEY", "path": "QDRANT_PATH",
            "collection": "QDRANT_COLLECTION", "dimension": "EMBEDDING_DIMENSION",
        },
    }[scope]
    fallback = "QDRANT_URL/QDRANT_API_KEY" if scope == "vector" else "CHAT_MODELS/DEFAULT_CHAT_MODEL/EMBEDDING_MODEL"
    return sorted({names.get(str(item["loc"][0]), fallback) if item["loc"] else fallback
                   for item in error.errors(include_input=False, include_context=False)})
