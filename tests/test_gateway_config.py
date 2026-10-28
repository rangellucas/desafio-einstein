import pytest
from pydantic import ValidationError

from app.config import load_gateway_settings


@pytest.mark.parametrize(("name", "value"), [
    ("LLM_BASE_URL", ""), ("LLM_BASE_URL", "not-a-url"),
    ("LLM_BASE_URL", "https://user:password@gateway.test/v1"),
    ("LLM_BASE_URL", "https://gateway.test/v1?secret=invalid"),
    ("LLM_BASE_URL", "https://gateway.test:invalid/v1"),
    ("LLM_API_KEY", ""), ("LLM_API_KEY", "   "),
    ("CHAT_MODELS", "azure/gpt-5-mini"),
    ("CHAT_MODELS", "azure/gpt-5-mini,azure/gpt-5-mini"),
    ("DEFAULT_CHAT_MODEL", "unknown"), ("EMBEDDING_MODEL", "unknown"),
    ("EMBEDDING_DIMENSION", "0"), ("EMBEDDING_DIMENSION", "x"),
    ("MAX_OUTPUT_TOKENS", "0"), ("REQUEST_TIMEOUT_SECONDS", "-1"),
    ("REQUEST_TIMEOUT_SECONDS", "nan"), ("REQUEST_TIMEOUT_SECONDS", "inf"),
])
def test_invalid_config(name: str, value: str) -> None:
    env = {"LLM_BASE_URL": "https://gateway.test/v1", "LLM_API_KEY": "synthetic-test-only", name: value}
    with pytest.raises(ValidationError) as error:
        load_gateway_settings(env)
    assert "synthetic-test-only" not in str(error.value)


def test_explicit_environment_and_secret_representation() -> None:
    settings = load_gateway_settings({
        "LLM_BASE_URL": "https://gateway.test/v1", "LLM_API_KEY": "synthetic-test-only",
        "EMBEDDING_DIMENSION": "3", "MAX_OUTPUT_TOKENS": "40", "REQUEST_TIMEOUT_SECONDS": "2.5",
    })
    assert settings.base_url == "https://gateway.test/v1/"
    assert settings.embedding_dimension == 3
    assert settings.max_output_tokens == 40
    assert settings.request_timeout_seconds == 2.5
    assert "synthetic-test-only" not in repr(settings)
    assert "synthetic-test-only" not in settings.model_dump_json()


def test_defaults_do_not_assume_embedding_dimension() -> None:
    settings = load_gateway_settings({"LLM_BASE_URL": "https://gateway.test/v1", "LLM_API_KEY": "synthetic-test-only"})
    assert settings.embedding_dimension is None
    assert settings.max_output_tokens == 600
    assert settings.request_timeout_seconds == 90
