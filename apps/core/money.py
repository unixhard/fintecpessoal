"""Conversão robusta de valores monetários digitados em centavos (int).

O usuário digita valores livremente e nem sempre no formato brasileiro
(ex.: '200', '3000', '2.000', '200.00', '1.234,56'). Esta heurística
determinística normaliza qualquer um desses formatos para centavos inteiros
sem depender de locale.

Regras:
- Inteiro puro ("200", "3000") é interpretado como REAIS inteiros
  (R$ 200,00 / R$ 3.000,00) — nunca como centavos. "3000" é 3 mil reais.
- "2.000" / "1.234" (pontos sem vírgula) são separadores de milhar.
- "1.234,56" e "1234,56" → 1.234 reais e 56 centavos.
- "1234.56" (estilo US) → 1.234 reais e 56 centavos.
- "1,5" / "200,5" → 1,50 / 200,50 (1 dígito decimal é completado com zero).
- Sinal +/- no início preserva o sinal (retorna centavos com sinal).
- Prefixo "R$ " opcional é ignorado.

Retorna None para textos que não parecem valor monetário.
"""

import re
from decimal import Decimal

_AMOUNT_RE = re.compile(r"^\s*(?P<sign>[+-]?)\s*(?P<amount>[\d.,]+)\s*$")
_CENTS_LIMIT = 12  # proteção contra números absurdos (1 trilhão de centavos)


def _int_from_digits(parts):
    try:
        return int("".join(parts))
    except ValueError:
        return None


def parse_money_to_cents(value):
    """Converte ``value`` (str/int) em centavos inteiros ou None se inválido."""
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip().replace("\u00a0", " ").strip()
    if not text:
        return None
    if text.lower().startswith("r$"):
        text = text[2:].strip()
    m = _AMOUNT_RE.match(text)
    if not m:
        return None
    sign = -1 if m.group("sign") == "-" else 1
    raw = m.group("amount")

    if "," in raw and "." in raw:
        int_part, _, dec_part = raw.partition(",")
        reais = _int_from_digits(int_part.split("."))
        cents = _cents(dec_part)
        if reais is None or cents is None or len(raw) > _CENTS_LIMIT:
            return None
        return sign * (reais * 100 + cents)

    if "," in raw:
        int_part, _, dec_part = raw.partition(",")
        if not dec_part or not dec_part.isdigit() or len(dec_part) > 2:
            return None
        reais = _int_from_digits(int_part.split("."))
        if reais is None or len(raw) > _CENTS_LIMIT:
            return None
        return sign * (reais * 100 + int(dec_part.ljust(2, "0")))

    if "." in raw:
        parts = raw.split(".")
        if len(parts) == 2 and parts[1].isdigit() and 0 < len(parts[1]) <= 2:
            reais = _int_from_digits([parts[0] or "0"])
            if reais is None:
                return None
            return sign * (reais * 100 + int(parts[1].ljust(2, "0")))
        # De outra forma, pontos são apenas separadores de milhar.
        if all(p.isdigit() and len(p) <= 3 for p in parts):
            reais = _int_from_digits(parts)
            if reais is None or len(raw) > _CENTS_LIMIT:
                return None
            return sign * reais * 100
        return None

    if raw.isdigit():
        if len(raw) > _CENTS_LIMIT:
            return None
        return sign * int(raw) * 100
    return None


def _cents(dec_part):
    if not dec_part.isdigit() or len(dec_part) > 2:
        return None
    return int(dec_part.ljust(2, "0"))


def format_cents(cents):
    """Formata centavos (int) como '1.234,56' (sem símbolo R$)."""
    try:
        cents = int(cents)
    except (TypeError, ValueError):
        return None
    sign = "-" if cents < 0 else ""
    cents = abs(cents)
    reais, cent = divmod(cents, 100)
    return f"{sign}{reais:,}".replace(",", ".") + f",{cent:02d}"


def decimal_cents(amount):
    """Converte um Decimal de reais (ex.: Decimal('1500.00')) em centavos."""
    if amount is None:
        return None
    return int(Decimal(amount).quantize(Decimal("0.01")) * 100)