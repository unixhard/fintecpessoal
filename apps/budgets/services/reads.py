"""Read layer de orçamentos.

Queries feitas para leitura (agregação no banco, isolamento por usuário).
Complementa `budgets.py` com visões agregadas usadas por listas e dashboard.
"""

from datetime import date

from apps.finance.models import Transaction
from django.db.models import Sum

from ..models import Budget

# ---------- Categorias com gasto e orçamento --------------------------------- #


def spending_by_category(user, start: date, end: date) -> dict:
    """Gasto (centavos) por categoria de despesa no intervalo [start, end]."""
    qs = (
        Transaction.objects.for_user(user)
        .filter(
            type=Transaction.Type.EXPENSE,
            date__gte=start,
            date__lte=end,
        )
        .values("category_id")
        .annotate(total=Sum("amount"))
    )
    return {r["category_id"]: r["total"] or 0 for r in qs}


def current_budgets(user, ref_date=None) -> list:
    """Orçamentos ativos do usuário (com progresso) para um mês/ano de referência."""
    from .budgets import get_budget_progress
    from ..models import Budget as B

    ref_date = ref_date or date.today()
    budgets = (
        B.objects.for_user(user)
        .filter(is_active=True)
        .select_related("category")
        .order_by("kind", "id")
    )
    return [
        get_budget_progress(user=user, budget=b, ref_date=ref_date) for b in budgets
    ]


def categories_above_or_close(user, *, threshold_pct=80, ref_date=None):
    """Categorias com orçamento em situação 'attention' ou 'exceeded'."""
    rows = current_budgets(user, ref_date=ref_date)
    return [r for r in rows if r["status"] in ("attention", "exceeded")]
