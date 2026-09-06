"""Parser de XLSX → matriz de linhas (preview) + movimentações normalizadas.

Não assumimos que planilhas têm o mesmo formato. O fluxo:
  1. `read_xlsx` produz a matriz de linhas (para preview e mapeamento manual).
  2. O usuário (ou auto-detecção de cabeçalho) define o mapeamento das colunas.
  3. `parse_xlsx` converte linhas+mapeamento em NormalizedTransaction, reutilizando
     a mesma normalização do CSV (valores BR, direção por sinal).
"""

from datetime import date, datetime
from typing import List, Optional

from .csv_parser import CsvConfig, infer_config, parse_mapped_rows
from .normalized import NormalizedTransaction


def read_xlsx_rows(content: bytes) -> List[List[str]]:
    """Lê as células de uma planilha como lista de linhas (str)."""
    try:
        import openpyxl
    except ImportError as exc:  # pragma: no cover
        raise ValueError("Suporte a XLSX indisponível (instale openpyxl).") from exc

    from openpyxl.utils.exceptions import InvalidFileException

    import io
    try:
        wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except (InvalidFileException, Exception) as exc:
        raise ValueError("Arquivo XLSX inválido ou corrompido.") from exc

    rows: List[List[str]] = []
    ws = wb.active
    if ws is None:
        return rows
    for row in ws.iter_rows(values_only=True):
        kept = []
        for v in row:
            if isinstance(v, (datetime, date)):
                # preserva como objeto para parse_date (suporta serial/datetime)
                kept.append(v)
            elif v is None:
                kept.append("")
            else:
                kept.append(str(v).strip())
        rows.append(kept)
    wb.close()
    return rows


def parse_xlsx(content: bytes, config: Optional[CsvConfig] = None) -> List[NormalizedTransaction]:
    """Faz o parsing e normalização do conteúdo XLSX."""
    rows = read_xlsx_rows(content)
    if not rows:
        return []
    if config is None:
        config = infer_config(rows)
    return parse_mapped_rows(rows, config)
