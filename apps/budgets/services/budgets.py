"""Serviços de orçamentos (Budget).

Regras financeiras permanecem nesta camada (nunca duplicadas em views/forms).
O valor "realizado" NÃO é armazenado — é calculado a partir dos lançamentos de
despesa (Transaction.EXPENSE) do usuário na categoria/período, seguindo a mesma
definição já usada pela camada de leitura do dashboard.
"""

from datetime import date

from django.db.models import Sum
from django.utils.timezone import localdate as tz_localdate

from apps.finance.models import Transaction
from apps.finance.services.base import require_owned
from apps.finance.services.errors import InvalidAmountError, InvalidStateError

from ..models import Budget

# Percentuais que classificam a "situação" (mesmos limiares do dashboard).
ATTENTION_PCT = 80
EXCEEDED_PCT = 100


def _require_budget(user, budget):
    require_owned(
        Budget.objects, user, model_label="Orçamento",
        object_id=getattr(budget, "pk", None),
    )
    return budget


def _validate_limit(limit_amount):
    if isinstance(limit_amount, bool) or not isinstance(limit_amount, int):
        raise InvalidAmountError("limite deve ser um inteiro em centavos.")
    if limit_amount < 0:
        raise InvalidAmountError("limite não pode ser negativo.")
    return limit_amount


def create_budget(
    *,
    user,
    kind,
    limit_amount,
    period=Budget.Period.MONTHLY,
    category=None,
    start_date=None,
    end_date=None,
    is_active=True,
):
    """Cria um orçamento pertencente ao usuário.

    - kind=category exige `category` do mesmo usuário;
    - kind=global não aceita categoria.
    """
    limit_amount = _validate_limit(limit_amount)
    if kind == Budget.Kind.CATEGORY:
        if category is None:
            raise InvalidStateError(
                "Orçamento por categoria exige uma categoria."
            )
        if category.owner_id != user.id:
            require_owned(
                category._meta.model.objects, user,
                model_label="Categoria", object_id=category.pk,
            )
    else:
        category = None
    budget = Budget.objects.create(
        owner=user,
        kind=kind,
        category=category,
        period=period,
        limit_amount=limit_amount,
        start_date=start_date,
        end_date=end_date,
        is_active=is_active,
    )
    return budget


def update_budget(
    *,
    user,
    budget,
    kind=None,
    limit_amount=None,
    period=None,
    category=None,
    start_date=None,
    end_date=None,
    is_active=None,
):
    """Atualiza um orçamento (ownership validado)."""
    _require_budget(user, budget)
    if kind is not None and kind != budget.kind:
        budget.kind = kind
    if limit_amount is not None:
        budget.limit_amount = _validate_limit(limit_amount)
    if period is not None:
        budget.period = period
    if category is not None:
        if budget.kind == Budget.Kind.CATEGORY:
            if category.owner_id != user.id:
                require_owned(
                    category._meta.model.objects, user,
                    model_label="Categoria", object_id=category.pk,
                )
        else:
            category = None
        budget.category = category
    if start_date is not None:
        budget.start_date = start_date
    if end_date is not None:
        budget.end_date = end_date
    if is_active is not None:
        budget.is_active = bool(is_active)
    if budget.kind == Budget.Kind.GLOBAL:
        budget.category = None
    budget.save()
    return budget


def delete_budget(*, user, budget):
    """Exclui um orçamento (ownership validado)."""
    _require_budget(user, budget)
    budget.delete()


def get_budget(*, user, budget_id):
    """Retorna um orçamento do usuário ou sobe ForbiddenResourceError."""
    return require_owned(
        Budget.objects, user, model_label="Orçamento", object_id=budget_id
    )


def get_budgets(*, user, include_inactive=False):
    """Lista os orçamentos do usuário (ativos por padrão)."""
    qs = Budget.objects.for_user(user)
    if not include_inactive:
        qs = qs.filter(is_active=True)
    return qs.select_related("category").order_by("kind", "id")


def _period_range(budget, ref_date):
    """Intervalo de apuração do orçamento para a data de referência."""
    if budget.start_date and budget.end_date:
        return budget.start_date, budget.end_date
    if budget.period == Budget.Period.YEARLY:
        start = date(ref_date.year, 1, 1)
        return start, date(ref_date.year, 12, 31)
    if budget.period == Budget.Period.CUSTOM:
        start = budget.start_date or ref_date
        return start, budget.end_date or ref_date
    # monthly (padrão) e sem intervalo explícito
    start = date(ref_date.year, ref_date.month, 1)
    from calendar import monthrange

    return start, date(ref_date.year, ref_date.month, monthrange(ref_date.year, ref_date.month)[1])


def budget_spent(*, user, budget, ref_date=None):
    """Valor realizado (centavos) de uma despesa no período do orçamento.

    Para orçamento por categoria, inclui subcategorias (mesma definição do
    dashboard). Não duplica contabilidade: só Transaction.EXPENSE conta.
    """
    _require_budget(user, budget)
    ref_date = ref_date or tz_localdate()
    start, end = _period_range(budget, ref_date)
    qs = Transaction.objects.for_user(user).filter(
        type=Transaction.Type.EXPENSE, date__gte=start, date__lte=end
    )
    if budget.kind == Budget.Kind.CATEGORY and budget.category:
        ids = [budget.category_id] + list(
            budget.category.subcategories.values_list("pk", flat=True)
        )
        qs = qs.filter(category_id__in=ids)
    return qs.aggregate(total=Sum("amount"))["total"] or 0


def get_budget_progress(*, user, budget, ref_date=None):
    """Progresso de um orçamento: planejado, realizado, restante, consumo, situação.

    `situacao`: healthy | attention | exceeded (mesmos limiares do dashboard).
    """
    _require_budget(user, budget)
    ref_date = ref_date or tz_localdate()
    planned = budget.limit_amount
    realized = budget_spent(user=user, budget=budget, ref_date=ref_date)
    remaining = max(planned - realized, 0)
    percent = int(round(realized / planned * 100)) if planned else 0
    status = "healthy"
    if planned and percent >= EXCEEDED_PCT:
        status = "exceeded"
    elif planned and percent >= ATTENTION_PCT:
        status = "attention"
    return {
        "planned": planned,
        "realized": realized,
        "remaining": remaining,
        "percent": percent,
        "status": status,
        "budget": budget,
        "ref_date": ref_date,
    }


def get_budget_summary(*, user, ref_date=None, include_inactive=False):
    """Resumo agregado dos orçamentos do usuário.

    - total_planned: soma dos limites;
    - total_realized: soma do realizado (compartilha categorias, sem dupla soma);
    - total_remaining, total_percent;
    - exceeded/attention: listas de orçamentos nas respectivas situações;
    - larger_deviations: orçamentos ordenados por desvio absoluto (maior primeiro).
    """
    budgets = list(get_budgets(user=user, include_inactive=include_inactive))
    if not budgets:
        return {
            "budgets": [],
            "rows": [],
            "total_planned": 0,
            "total_realized": 0,
            "total_remaining": 0,
            "total_percent": 0,
            "exceeded": [],
            "attention": [],
            "larger_deviations": [],
        }

    rows = [
        get_budget_progress(user=user, budget=b, ref_date=ref_date) for b in budgets
    ]
    active_rows = [r for r in rows if r["budget"].is_active]
    total_planned = sum(r["planned"] for r in active_rows)
    total_realized = sum(r["realized"] for r in active_rows)
    total_percent = (
        int(round(total_realized / total_planned * 100)) if total_planned else 0
    )
    exceeded = [r for r in active_rows if r["status"] == "exceeded"]
    attention = [r for r in active_rows if r["status"] == "attention"]
    deviations = sorted(
        active_rows,
        key=lambda r: (r["realized"] - r["planned"]),
        reverse=True,
    )
    return {
        "budgets": budgets,
        "rows": rows,
        "total_planned": total_planned,
        "total_realized": total_realized,
        "total_remaining": max(total_planned - total_realized, 0),
        "total_percent": total_percent,
        "exceeded": exceeded,
        "attention": attention,
        "larger_deviations": deviations,
    }
