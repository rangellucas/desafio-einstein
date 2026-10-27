"""Parâmetros iniciais do PRD, ainda sem calibração pela recuperação."""

from pathlib import Path

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
