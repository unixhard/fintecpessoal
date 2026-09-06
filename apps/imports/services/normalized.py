"""Representação normalizada (DTO) de uma movimentação detectada.

Independente do formato de origem (CSV, OFX, XLSX, e futuramente PDF), todos os
parsers produzem a MESMA estrutura `NormalizedTransaction`. Isso garante que a
camada de staging/classificação/revisão não dependa do formato de arquivo.
"""

from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from dataclasses import fields

DIRECTION_INCOME = "income"
DIRECTION_EXPENSE = "expense"


@dataclass
class NormalizedTransaction:
    """Uma movimentação já extraída e normalizada do arquivo de origem."""

    date: date
    description: str
    amount_cents: int                      # SEMPRE inteiro, sempre > 0 (D10)
    direction: str                         # 'income' | 'expense'
    source_id: str = ""                    # id único da origem (ex.: FITID OFX)
    original_description: str = ""
    balance_cents: Optional[int] = None    # saldo quando disponível
    metadata: dict = field(default_factory=dict)

    @classmethod
    def names(cls):
        return [f.name for f in fields(cls)]
