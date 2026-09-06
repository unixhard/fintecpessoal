"""Parser de OFX → lista de NormalizedTransaction.

OFX é tratado como fonte ESTRUTURADA (decisão da Ordem 17): não usamos IA para
interpretar OFX. Os identificadores únicos (FITID) são preservados em
``source_id`` para deduplicação futura.
"""

import io
from datetime import datetime, date
from decimal import Decimal
from typing import List

from .normalise import NormaliseError
from .normalized import DIRECTION_EXPENSE, DIRECTION_INCOME, NormalizedTransaction


def _to_date(value) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    # ofxparse pode devolver strings quando a tag é fraca
    raw = str(value).strip()
    for fmt in ("%Y%m%d", "%Y-%m-%d", "%Y%m%d%H%M%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    raise NormaliseError(f"Data OFX inválida: {value!r}")


def _amount_to_cents(value) -> int:
    """Converte o valor do OFX (Decimal, sinal -> direção) em centavos positivos."""
    if isinstance(value, str):
        dec = Decimal(value)
    else:
        dec = Decimal(value)
    cents = int((dec * 100).to_integral_value())
    if cents == 0:
        raise NormaliseError("Valor OFX zero.")
    if cents < 0:
        return -cents, DIRECTION_EXPENSE
    return cents, DIRECTION_INCOME


def parse_ofx(content: bytes) -> List[NormalizedTransaction]:
    """Parseia bytes de um arquivo OFX/QFX e devolve movimentações normalizadas."""
    try:
        from ofxparse import OfxParser
    except ImportError as exc:  # pragma: no cover
        raise NormaliseError("Suporte a OFX indisponível (instale ofxparse).") from exc

    ofx = OfxParser.parse(io.BytesIO(content))
    result: List[NormalizedTransaction] = []
    account = getattr(ofx, "account", None)
    if account is None:
        raise NormaliseError("OFX sem bloco de conta.")

    institution = getattr(getattr(account, "institution", None), "organization", "") or ""
    statement = getattr(account, "statement", None)
    if statement is None:
        return []

    for txn in getattr(statement, "transactions", []):
        try:
            cents, direction = _amount_to_cents(getattr(txn, "amount", 0))
        except (NormaliseError, ValueError):
            continue
        memo = getattr(txn, "memo", "") or ""
        txn_type = getattr(txn, "type", "") or ""
        fitid = getattr(txn, "id", "") or getattr(txn, "unique_id", "") or ""
        try:
            txn_date = _to_date(getattr(txn, "date", None))
        except NormaliseError:
            continue

        result.append(
            NormalizedTransaction(
                date=txn_date,
                description=memo,
                original_description=memo,
                amount_cents=cents,
                direction=direction,
                source_id=fitid,
                metadata={"file_type": "ofx", "type": txn_type, "institution": institution},
            )
        )
    return result
