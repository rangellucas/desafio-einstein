"""Parâmetros do PRD e configuração explícita do gateway, sem efeitos na importação."""

from collections.abc import Mapping
import os
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator

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
