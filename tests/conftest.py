import socket
from collections.abc import Callable
from pathlib import Path

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject


@pytest.fixture(autouse=True)
def isolate_api_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """O lifespan dos testes nunca lê configuração/credenciais do ambiente real."""
    from app.config import ApiSettings
    import app.main as main

    def unavailable():
        raise ValueError("synthetic_unconfigured")

    monkeypatch.setattr(main, "load_api_settings", lambda: ApiSettings())
    monkeypatch.setattr(main, "load_gateway_settings", unavailable)
    monkeypatch.setattr(main, "load_vector_settings", unavailable)


@pytest.fixture(autouse=True)
def block_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Os testes comuns falham se algum caminho tentar abrir uma conexão."""
    def deny(*args: object, **kwargs: object) -> None:
        raise AssertionError("Conexões de rede são proibidas nos testes comuns.")

    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket.socket, "connect_ex", deny)
    monkeypatch.setattr(socket, "create_connection", deny)


@pytest.fixture
def make_pdf() -> Callable[[Path, list[str]], Path]:
    """PDF mínimo gerado em diretório temporário, sem documentos privados."""
    def write(path: Path, texts: list[str]) -> Path:
        writer = PdfWriter()
        for text in texts:
            page = writer.add_blank_page(width=300, height=300)
            if text:
                font = DictionaryObject({
                    NameObject("/Type"): NameObject("/Font"),
                    NameObject("/Subtype"): NameObject("/Type1"),
                    NameObject("/BaseFont"): NameObject("/Helvetica"),
                })
                page[NameObject("/Resources")] = DictionaryObject({
                    NameObject("/Font"): DictionaryObject({NameObject("/F1"): font}),
                })
                escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
                stream = DecodedStreamObject()
                stream.set_data(f"BT /F1 12 Tf 20 250 Td ({escaped}) Tj ET".encode("latin-1"))
                page.replace_contents(stream)
        writer.write(path)
        writer.close()
        return path

    return write
