"""Candidato de staging: um NormalizedTransaction + metadados de revisão.

Cada candidato carrega o resultado da classificação (categoria sugerida) e da
detecção de duplicidade (confiança, possível duplicação), antes de virar uma
linha `StagedTransaction`.
"""

from dataclasses import dataclass, field
from typing import Optional

from .normalized import NormalizedTransaction

CONFIDENCE_HIGH = "high"
CONFIDENCE_REVIEW = "review"
CONFIDENCE_DUPLICATE = "duplicate"

ROW_READY = "ready"
ROW_IGNORED = "ignored"


@dataclass
class Candidate:
    date: object
    description: str
    amount_cents: int
    direction: str
    source_id: str = ""
    original_description: str = ""
    balance_cents: Optional[int] = None
    metadata: dict = field(default_factory=dict)
    external_id: str = ""
    category: object = None                  # Categoria sugerida (ou None)
    category_name: str = ""                  # nome sugerido p/ criar, se necessário
    confidence: str = CONFIDENCE_HIGH
    row_status: str = ROW_READY
    duplicate_of: object = None
    skip_reason: str = ""
    matched_transaction_id: Optional[int] = None
    # Identidade de estabelecimento (Ordem 18 / FASE 4).
    merchant: object = None             # Merchant identificado (ou None)
    normalized_description: str = ""
    merchant_method: str = ""           # origem da identificação (ex.: 'user_alias')
    merchant_confidence: float = 0.0

    @classmethod
    def from_normalized(cls, nt: NormalizedTransaction) -> "Candidate":
        return cls(
            date=nt.date,
            description=nt.description,
            amount_cents=nt.amount_cents,
            direction=nt.direction,
            source_id=nt.source_id,
            original_description=nt.original_description or nt.description,
            balance_cents=nt.balance_cents,
            metadata=nt.metadata,
            external_id=nt.source_id,
        )
