"""Contratos públicos da consulta independente e da lista de modelos."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    question: str = Field(description="Pergunta independente, de 1 a 1.500 caracteres após strip.")
    model: str | None = Field(default=None, description="Identificador permitido; omitido usa o padrão.")

    @field_validator("question")
    @classmethod
    def validate_question(cls, value: str) -> str:
        value = value.strip()
        if not 1 <= len(value) <= 1500:
            raise ValueError("A pergunta deve conter de 1 a 1.500 caracteres após remover espaços nas extremidades.")
        return value


class Source(BaseModel):
    id: str
    document: str
    page: int = Field(ge=1, description="Posição física no PDF, começando em 1.")
    excerpt: str = Field(max_length=600)


class ChatResponse(BaseModel):
    request_id: str
    model: str
    answer: str
    sources: list[Source]
    finish_reason: Literal["stop", "length", "insufficient_context"]


class SourcesEvent(BaseModel):
    request_id: str
    model: str
    sources: list[Source]


class DeltaEvent(BaseModel):
    text: str


class DoneEvent(BaseModel):
    finish_reason: Literal["stop", "length", "insufficient_context"]


class ModelsResponse(BaseModel):
    models: list[str]
    default_model: str


class ErrorDetail(BaseModel):
    code: str
    message: str
    request_id: str


class ErrorResponse(BaseModel):
    detail: ErrorDetail
