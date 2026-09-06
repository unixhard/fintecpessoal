"""Parser de CSV → lista de NormalizedTransaction.

- Detecta o delimitador (; , tab).
- Detecta linha de cabeçalho por heurística e permite mapeamento manual.
- Interpreta datas e valores brasileiros/internacionais.
- Suporta as convenções de coluna:
    data, descrição, valor (com sinal), e/ou colunas separadas débito/crédito.
- Nunca usa IA; é um parser estruturado.
"""

import csv
import io
from dataclasses import dataclass
from typing import List, Optional

from .normalise import NormaliseError, direction_from_amount, parse_date, to_cents
from .normalized import DIRECTION_EXPENSE, DIRECTION_INCOME, NormalizedTransaction

_DELIMITERS = [",", ";", "\t"]
_DATE_HEADERS = ("data", "date", "lançamento", "lancamento", "dt", "vencimento")
_DESC_HEADERS = ("descricao", "descrição", "descri", "historico", "histórico", "memorando",
                 "nome", "favor", "identificacao", "identificação", "desc")
_AMOUNT_HEADERS = ("valor", "value", "amount", "importancia", "importância", "val", "v")
_DEBIT_HEADERS = ("debito", "débito", "debit", "saida", "saída", "pagamento", "saiu")
_CREDIT_HEADERS = ("credito", "crédito", "credit", "entrada", "deposito", "depósito", "recebimento")
_BALANCE_HEADERS = ("saldo", "balance")
_SIGNED_HEADERS = _AMOUNT_HEADERS
_TYPE_HEADERS = ("tipo", "type", "transacao", "transação")
_TYPE_INCOME = ("receita", "entrada", "credito", "crédito", "deposito", "depósito", "income", "c")
_TYPE_EXPENSE = ("despesa", "saida", "saída", "debito", "débito", "pagamento", "expense", "d")


@dataclass
class CsvConfig:
    """Mapeamento das colunas. Se deixado vazio, é tentada a auto-detecção."""
    date: int = -1
    description: int = -1
    amount: int = -1        # coluna de valor com sinal
    debit: int = -1         # coluna de débito (expense)
    credit: int = -1        # coluna de crédito (income)
    type: int = -1          # coluna de tipo (recurso opcional)
    category: int = -1      # coluna de categoria sugerida (recurso opcional)
    balance: int = -1
    has_header: bool = True


def _detect_delimiter(text: str) -> str:
    lines = [l for l in text.splitlines() if l.strip()]
    sample = "\n".join(lines[:10])
    best, best_count = ",", 0
    for d in _DELIMITERS:
        count = sample.count(d)
        if count > best_count:
            best, best_count = d, count
    return best


def _clean(value) -> str:
    """Limpa um valor de célula para comparação (aceita tipos do XLSX)."""
    from datetime import date, datetime

    if value is None:
        return ""
    if isinstance(value, (datetime, date)):
        # preserva para parse_date (que entende datetime/date/serial)
        return value
    return (str(value) or "").strip().strip('"').strip("'")


def _looks_like_header(row: List[str]) -> bool:
    # Usa o normalizador universal: reconhece variações multi-banco
    # ("Data Lançamento", "Valor (R$)", "Categoria Sugerida", "Histórico").
    from .column_normalizer import detect_role

    for raw in row:
        role = detect_role(raw)
        if role in ("date", "description", "amount", "debit", "credit", "category"):
            return True
    return False


def _reshape_header(row: List[str]) -> "CsvConfig":
    from .column_normalizer import detect_and_map_columns

    return detect_and_map_columns(row)


def infer_config(data: List[List[str]]) -> CsvConfig:
    """Infere o mapeamento de colunas a partir das linhas (com ou sem header).

    Usa o Normalizador Universal de Colunas (detecção por sinônimo/regex,
    agnóstica de banco). Se não houver cabeçalho reconhecível, faz fallback
    posicional (data=0, descrição=1, valor=2).
    """
    header_row = None
    start = 0
    if data and _looks_like_header(data[0]):
        header_row = data[0]
        start = 1

    if header_row is not None:
        from .column_normalizer import detect_and_map_columns

        cfg = detect_and_map_columns(header_row)
        cfg.has_header = True
        return cfg

    cfg = CsvConfig()
    cfg.has_header = False
    cfg.date, cfg.description, cfg.amount = 0, 1, 2
    return cfg


def parse_mapped_rows(data: List[List[str]], config: CsvConfig) -> List[NormalizedTransaction]:
    """Normaliza uma matriz de linhas (com ou sem header) usando um CsvConfig."""
    rows = [r for r in data if any(_clean(c) for c in r)]
    if not rows:
        return []
    data_rows = rows[1:] if (config.has_header and rows) else rows
    result: List[NormalizedTransaction] = []
    for row in data_rows:
        try:
            nt = _row_to_normalized(row, config)
        except NormaliseError:
            continue
        if nt is not None:
            result.append(nt)
    return result


def parse_csv(content: bytes, config: Optional[CsvConfig] = None) -> List[NormalizedTransaction]:
    """Faz o parsing e normalização do conteúdo CSV (bytes de texto)."""
    text = content.decode("utf-8-sig", errors="replace")
    delimiter = _detect_delimiter(text)
    rows = list(csv.reader(io.StringIO(text), delimiter=delimiter))
    if not rows:
        return []

    # remove linhas totalmente vazias
    rows = [r for r in rows if any(_clean(c) for c in r)]
    if not rows:
        return []

    if config is None:
        config = infer_config(rows)

    data_rows = rows[1:] if (config.has_header and rows) else rows
    result: List[NormalizedTransaction] = []
    for row in data_rows:
        try:
            nt = _row_to_normalized(row, config)
        except NormaliseError:
            continue  # linhas inválidas são puladas silenciosamente na detecção
        if nt is not None:
            result.append(nt)
    return result


def _row_to_normalized(row: List[str], cfg: CsvConfig) -> Optional[NormalizedTransaction]:
    def col(idx):
        if 0 <= idx < len(row):
            return _clean(row[idx])
        return ""

    date_val = col(cfg.date)
    if not date_val:
        return None
    try:
        parsed_date = parse_date(date_val)
    except NormaliseError:
        # se não houver data, não há como criar a movimentação
        return None

    desc = col(cfg.description)
    orig = desc

    direction = None
    amount_cents = None

    type_val = col(cfg.type).lower()
    if type_val in _TYPE_INCOME or type_val in ("c", "credito", "crédito"):
        direction = DIRECTION_INCOME
    elif type_val in _TYPE_EXPENSE or type_val in ("d", "debito", "débito", "pag"):
        direction = DIRECTION_EXPENSE

    # Valor com sinal (coluna única)
    if cfg.amount >= 0:
        raw = col(cfg.amount)
        if raw:
            try:
                cents, auto_dir = direction_from_amount(raw)
                amount_cents = cents
                if direction is None:
                    direction = auto_dir
            except NormaliseError:
                pass
    # Débito/crédito separados
    if amount_cents is None and (cfg.debit >= 0 or cfg.credit >= 0):
        debit_raw = col(cfg.debit)
        credit_raw = col(cfg.credit)
        if debit_raw:
            try:
                spent = to_cents(debit_raw)
            except NormaliseError:
                spent = None
            if spent:  # débito não-zero => expense
                amount_cents = abs(spent)
                direction = DIRECTION_EXPENSE
        if amount_cents is None and credit_raw:
            try:
                received = to_cents(credit_raw)
            except NormaliseError:
                received = None
            if received:  # crédito não-zero e sem débito => income
                amount_cents = abs(received)
                direction = DIRECTION_INCOME

    if amount_cents is None or amount_cents <= 0 or direction is None:
        return None

    balance = None
    if cfg.balance >= 0 and col(cfg.balance):
        try:
            balance = to_cents(col(cfg.balance))
        except NormaliseError:
            balance = None

    # Categoria sugerida (opcional — coluna presente em planilhas de teste).
    suggested_category = ""
    if cfg.category >= 0:
        suggested_category = col(cfg.category)

    return NormalizedTransaction(
        date=parsed_date,
        description=desc,
        original_description=orig,
        amount_cents=amount_cents,
        direction=direction,
        balance_cents=balance,
        metadata={
            "file_type": "csv",
            "suggested_category": suggested_category or "",
        },
    )
