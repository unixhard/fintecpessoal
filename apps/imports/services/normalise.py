"""Normalização de valores e datas de um arquivo para a representação interna.

Regra D10: dinheiro é SEMPRE inteiro em centavos, nunca float.
Esta camada converte textos brasileiros/internacionais em centavos inteiros e
decide a direção (income/expense) a partir do sinal — respeitando a convenção
de que o VALOR é positivo e o sinal vem do tipo.
"""

import re
from datetime import date, datetime, timedelta

_CENTS_RE = re.compile(r"^[+]?(\d[\d.]*)(?:[.,](\d{1,2}))?$")
_SIGN_AFTER_RE = re.compile(r"^(.+?)\s*([-+])?\s*$")


class NormaliseError(ValueError):
    """Erro de normalização (valor/data inválidos)."""


def _strip_currency(value: str) -> str:
    """Remove símbolos de moeda e espaços ('R$ 1.234,56' -> '1.234,56')."""
    return re.sub(r"[^\d.,+\-]", "", value.strip())


def to_cents(value) -> int:
    """Converte texto de moeda em centavos inteiros.

    Suporta formatos:
      '1.234,56'   -> 123456
      '1234.56'    -> 123456
      'R$ 1.234,56'-> 123456
      '-50,00'     -> -5000
      '50.00'      -> 5000
      '1.234'      -> 123400
      '1234'       -> 123400
      '-45.9'      -> -4590
    Devolve SEMPRE um inteiro (positivo, negativo ou zero).
    """
    if isinstance(value, bool):
        raise NormaliseError("Valor inválido.")
    if isinstance(value, (int, float)):
        return _from_number(value)
    if not isinstance(value, str):
        raise NormaliseError("Valor inválido.")

    raw = _strip_currency(value)
    if not raw or raw in ("-", "+"):
        raise NormaliseError("Valor inválido.")

    negative = raw.startswith("-")
    if negative:
        raw = raw[1:]

    # 1) Ambos separadores: vírgula (decimal) e ponto (milhar) => formato BR.
    if "," in raw and "." in raw:
        intp = raw.split(",")[0].replace(".", "")
        fracp = raw.split(",")[1]
        return _build_cents(intp, fracp, negative)

    # 2) Só vírgula: é sempre o separador decimal.
    if "," in raw:
        intp, _, fracp = raw.partition(",")
        return _build_cents(intp.replace(".", ""), fracp, negative)

    # 3) Só ponto: decidir se o último é decimal ou milhar.
    if "." in raw:
        last_dot = raw.rfind(".")
        after = raw[last_dot + 1:]
        before = raw[:last_dot]
        # Ponto decimal quando os dígitos após o último ponto são 1-2
        # (ex.: '5.9', '12.56', '50.00').
        if after and len(after) <= 2 and after.isdigit():
            return _build_cents(before.replace(".", ""), after, negative)
        # Senão é milhar (ex.: '1.234' -> 1234 reais).
        return _build_cents(raw.replace(".", ""), "", negative)

    # 4) Sem separador — apenas dígitos.
    if not raw.isdigit():
        raise NormaliseError(f"Valor inválido: {value!r}")
    return int(raw) * 100 * (-1 if negative else 1)


def _from_number(value) -> int:
    if isinstance(value, float):
        cents = round(value * 100)
    else:
        cents = value * 100
    return int(cents)


def _build_cents(intp: str, fracp: str, negative: bool) -> int:
    if not intp:
        intp = "0"
    if not intp.isdigit():
        raise NormaliseError("Valor inválido.")
    # Normaliza fração com 2 casas.
    fracp = (fracp or "").ljust(2, "0")[:2]
    if not fracp.isdigit():
        raise NormaliseError("Valor inválido.")
    cents = int(intp) * 100 + int(fracp)
    return -cents if negative else cents


def direction_from_amount(value) -> tuple[int, str]:
    """Devolve (amount_cents_absoluto, direction) a partir de um valor bruto.

    Recebe o texto (ex.: '-50,00') e retorna (5000, 'expense') respeitando que
    o valor armazenado é positivo e a direção vem do sinal.
    """
    cents = to_cents(value)
    if cents == 0:
        raise NormaliseError("Valor zero não pode ser movimentação.")
    if cents < 0:
        return (-cents, "expense")
    return (cents, "income")


def parse_date(value) -> date:
    """Converte datas nos formatos comuns (BR, ISO e serial do Excel) em date."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    # Data serial do Excel (número de dias desde 1899-12-30) — comum em XLSX
    # com célula de data não tipada ou exportada como número.
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            return _excel_serial_to_date(value)
        except (ValueError, OverflowError):
            pass
    raw = str(value).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d/%m/%y", "%m/%d/%Y", "%d.%m.%Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    raise NormaliseError(f"Data inválida: {value!r}")


def _excel_serial_to_date(value) -> date:
    """Converte um serial do Excel (epoch 1900) em date.

    Excel conta dia 1 como 1899-12-30 (corrigindo o "ano 1900 bissexto" —
    o serial 60 é o falso 1900-02-29). ``value`` é um número ≥ 1.
    """
    serial = int(round(float(value)))
    if serial < 1:
        raise ValueError("serial negativo")
    return date(1899, 12, 30) + timedelta(days=serial)
