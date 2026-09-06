"""Registro de parsers por tipo de arquivo (CSV / OFX / XLSX)."""

from typing import List

from .csv_parser import parse_csv
from .ofx_parser import parse_ofx
from .xlsx_parser import parse_xlsx
from .normalized import NormalizedTransaction


def parse(file_type: str, content: bytes) -> List[NormalizedTransaction]:
    """Despacha para o parser do tipo indicado."""
    if file_type == "csv":
        return parse_csv(content)
    if file_type == "ofx":
        return parse_ofx(content)
    if file_type == "xlsx":
        return parse_xlsx(content)
    raise ValueError(f"Tipo de arquivo não suportado: {file_type}")
