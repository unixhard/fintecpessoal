"""Detecção de compras parceladas em extratos/faturas de cartão.

Reconhece o padrão brasileiro comum de descrição de compras no cartão:

    "COMPRA 123456 10X 150,90"          -> 10 parcelas de R$ 150,90
    "PAGAMENTO 3x 99,99 LOJA X"         -> 3 parcelas de R$ 99,99
    "AMAZON 12x R$ 59,90"               -> 12 parcelas de R$ 59,90
    "00/10 12x 49,90 COMPRA"            -> 10ª de 12 parcelas

Alguns bancos (Nubank, C6, Inter) também emitem faturas estruturadas (OFX)
onde o número da parcela atual pode aparecer como "PARCELA 1/12".
"""

import re
from dataclasses import dataclass
from typing import Optional


@dataclass
class InstallmentInfo:
    total_count: int
    current: Optional[int] = None  # None quando a descrição não diz qual parcela atual
    installment_value_cents: Optional[int] = None
    matched_text: str = ""
    as_text: str = ""


# Padrão: N(º)? X(x) [R$] valor[,.]cc  — ex: "10X 150,90", "3x 99,99", "12 X R$ 59,90"
_INSTALLMENT_AMOUNT_RE = re.compile(
    r"(?P<count>\d{1,3})\s*[xX]\s*(?:R\$\s*)?(?P<value>\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{1,2})?)",
    re.I,
)

# Padrão: N(º)? X(x) — sem valor, ex: "10X", "12x"
_INSTALLMENT_ONLY_RE = re.compile(r"(?P<count>\d{1,3})\s*[xX]\b", re.I)

# Padrão "parcela 1/12" (OFX estruturado): "PARCELA 3/12" | "PARCELA N"
_CURRENT_RE = re.compile(r"(?:PARCELA|PARC\.?)\s*(?P<current>\d{1,3})\s*(?:/\s*(?P<total>\d{1,3}))?", re.I)

# Padrão "NN/NN" no início de descrições de fatura (ex: "05/12 58,90 ...")
_LEADING_RATIO_RE = re.compile(r"^\s*(?P<current>\d{1,2})\s*/\s*(?P<total>\d{1,2})\b", re.I)


def _parse_cents(value_str: str) -> int:
    """Converte '150,90' ou '1.234,56' ou '59.9' em centavos (int)."""
    s = value_str.strip()
    if "," in s and "." in s:
        # formato com milhar: "1.234,56"
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")
    parts = s.split(".")
    if len(parts) == 2:
        cents = int(parts[0]) * 100 + int(parts[1][:2].ljust(2, "0"))
    else:
        cents = int(float(s) * 100)
    return cents


def detect_installment(description: str) -> Optional[InstallmentInfo]:
    """Detecta parcelamento em uma descrição de fatura de cartão.

    Retorna ``InstallmentInfo`` se reconhecer pontuação de parcela, ou ``None``.
    ``current`` (parcela atual) é preenchido quando a descrição informa
    (ex: "PARCELA 3/12" ou "05/12").
    """
    if not description:
        return None
    text = description

    # 1) "NN/NN" no início — fatura estruturada.
    m = _LEADING_RATIO_RE.match(text)
    if m:
        total = int(m.group("total"))
        if total > 1:
            current = int(m.group("current")) or None
            amt = _INSTALLMENT_AMOUNT_RE.search(text)
            val_cents = _parse_cents(amt.group("value")) if amt else None
            return InstallmentInfo(
                total_count=total,
                current=current,
                installment_value_cents=val_cents,
                matched_text=m.group(0),
                as_text=f"{current}/{total}x" if current else f"{total}x",
            )

    # 2) "PARCELA N/N" — OFX estruturado.
    m = _CURRENT_RE.search(text)
    if m and m.group("current"):
        total = int(m.group("total")) if m.group("total") else None
        current = int(m.group("current"))
        if total and total > 1:
            amt = _INSTALLMENT_AMOUNT_RE.search(text)
            val_cents = _parse_cents(amt.group("value")) if amt else None
            return InstallmentInfo(
                total_count=total,
                current=current,
                installment_value_cents=val_cents,
                matched_text=m.group(0),
                as_text=f"{current}/{total}x",
            )

    # 3) "10X 150,90" — quantidade + valor.
    m = _INSTALLMENT_AMOUNT_RE.search(text)
    if m:
        count = int(m.group("count"))
        if count > 1:
            val_cents = _parse_cents(m.group("value"))
            return InstallmentInfo(
                total_count=count,
                current=None,
                installment_value_cents=val_cents,
                matched_text=m.group(0),
                as_text=f"{count}x",
            )

    # 4) "10X" — apenas quantidade.
    m = _INSTALLMENT_ONLY_RE.search(text)
    if m:
        count = int(m.group("count"))
        if count > 1:
            return InstallmentInfo(
                total_count=count,
                current=None,
                installment_value_cents=None,
                matched_text=m.group(0),
                as_text=f"{count}x",
            )

    return None
