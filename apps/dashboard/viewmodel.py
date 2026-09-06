"""ViewModel do dashboard: monta ``DashboardData`` a partir da camada de leitura.

Separa a orquestração (esta camada) do cálculo bruto (queries.py) e das regras
(insights.py). O template recebe um contexto estruturado, não um dicionário
gigantesco com lógica embutida.
"""

from __future__ import annotations

from datetime import date, timedelta
from calendar import monthrange

from django.db.models import Sum

from apps.cards.models import CreditCard
from apps.finance.models import Account, Category, Transaction

from . import queries
from .insights import analyze
from .queries import (
    RecentTransaction,
    account_balances,
    account_summary,
    budgets,
    cash_flow,
    committed,
    committed_by_card,
    debts,
    goals,
    installment_obligations,
    monthly_evolution,
    net_balance,
    recent_transactions,
    resolve_period,
    spending_by_category,
    upcoming_events,
    upcoming_invoices,
)

# Valor abaixo do qual a margem pós-compromissos é considerada "apertada".
_LOW_MARGIN_CENTS = 50_000  # R$ 500,00
# Amostra mínima para calcular a despesa "típica" (média).
_AVG_EXPENSE_MIN_SAMPLE = 5


class DashboardFilter:
    """Filtros aplicados ao dashboard (todos validados por ownership)."""

    def __init__(self, *, period="30d", account_id=None, card_id=None, user=None):
        self.period = period
        self.account_ids = []
        self.card_ids = []
        if user is not None:
            self._resolve_owned(user, account_id, card_id)

    def _resolve_owned(self, user, account_id, card_id):
        if account_id:
            acc = Account.objects.filter(pk=account_id).first()
            if acc and acc.owner_id == user.id:
                self.account_ids = [acc.pk]
        if card_id:
            card = CreditCard.objects.filter(pk=card_id).first()
            if card and card.owner_id == user.id:
                self.card_ids = [card.pk]


def build_dashboard(user, *, period="30d", account_id=None, card_id=None, today=None, month=None) -> dict:
    """Constrói o contexto completo do dashboard para o usuário."""
    today = today or queries._today()

    # Navegação por mês: quando ``month`` é fornecido (ex: "2024-01"),
    # sobrescreve o período para aquele mês civil completo.
    if month:
        try:
            from datetime import date as _date
            parts = month.split("-")
            m_year, m_month = int(parts[0]), int(parts[1])
            month_start = _date(m_year, m_month, 1)
            from calendar import monthrange
            month_end = _date(m_year, m_month, monthrange(m_year, m_month)[1])
            period_data = {
                "key": f"{m_year}-{m_month:02d}",
                "label": f"{month_start.strftime('%B de %Y').title()}",
                "start": month_start,
                "end": month_end,
            }
        except (ValueError, IndexError):
            month = None

    if not month:
        period_data = resolve_period(period, today=today)

    filt = DashboardFilter(
        period=period, account_id=account_id, card_id=card_id, user=user
    )
    accounts_filter = filt.account_ids or None
    cards_filter = filt.card_ids or None

    disponivel = net_balance(user)
    comprometido = committed(user)

    cf = cash_flow(
        user, start=period_data["start"], end=period_data["end"],
        accounts=accounts_filter, cards=cards_filter,
    )
    categories = spending_by_category(
        user, start=period_data["start"], end=period_data["end"],
        accounts=accounts_filter, cards=cards_filter,
    )
    buckets = monthly_evolution(
        user, start=period_data["start"], end=period_data["end"],
        accounts=accounts_filter, cards=cards_filter,
    )
    card_rows = committed_by_card(user)
    invoices = upcoming_invoices(user)
    installments = installment_obligations(user)
    budget_rows = budgets(user, today=today)
    goal_rows = goals(user)
    debt_rows = debts(user)
    account_rows = account_summary(user)
    events = upcoming_events(user, days=30)
    recent = _filter_recent_by_period(
        recent_transactions(user, limit=12, accounts=accounts_filter, cards=cards_filter),
        period_data["start"], period_data["end"],
    )
    history = _period_history(user, today, accounts_filter, cards_filter)

    has_data = any(
        v
        for v in (
            cf.receitas,
            cf.despesas,
            cf.transfer_in,
            cf.transfer_out,
            disponivel,
            comprometido,
            len(card_rows),
            len(budget_rows),
            len(goal_rows),
            len(debt_rows),
            len(account_rows),
        )
    )

    data = {
        "today": today,
        "period": period_data["key"],
        "period_label": period_data["label"],
        "period_start": period_data["start"],
        "period_end": period_data["end"],
        "month": month,
        "month_nav": _month_nav(period_data["start"]) if month else None,
        "filters": {
            "period": period_data["key"],
            "account_id": filt.account_ids[0] if filt.account_ids else None,
            "card_id": filt.card_ids[0] if filt.card_ids else None,
            "accounts": account_balances(user),
            "cards_filter": card_rows,
        },
        # Herói / liquidez
        "disponivel": disponivel,
        "comprometido": comprometido,
        "disponivel_apos": disponivel - comprometido,
        "liquidity_items": [
            {"label": "Saldo atual (contas ativas)", "amount": disponivel},
            {"label": "Obrigações de cartão", "amount": -comprometido},
        ],
        # Fluxo de caixa
        "cash_flow": cf,
        "spending_rows": categories,
        "spending_total": sum(c.amount for c in categories),
        "spending_max": max((c.amount for c in categories), default=0),
        "has_spending": bool(categories),
        "evolution": buckets,
        "evolution_max": max(
            (max(b.receitas, b.despesas, max(b.saldo, 0)) for b in buckets),
            default=0,
        ),
        "has_evolution": any((b.receitas or b.despesas) for b in buckets),
        # Cartão / faturas / parcelas
        "cards": card_rows,
        "invoices": invoices,
        "installments": installments,
        "invoice_events": [
            {"date": i.date, "amount": i.amount, "label": i.label}
            for i in events
            if i.kind == "invoice"
        ],
        "upcoming_events": events,
        # Meta / orçamento / dívidas / contas
        "budgets": budget_rows,
        "goals": goal_rows,
        "debts": debt_rows,
        "accounts": account_rows,
        "recent_transactions": recent,
        # Suporte a insights
        "month_category_spend": history["current_cat"],
        "category_pattern": history["pattern"],
        "category_names": history["names"],
        "average_expense": history["avg_expense"],
        "recent_expenses": history["recent_expenses"],
        # Helpers
        "money": _fmt,
        "money_floor_low": _LOW_MARGIN_CENTS,
        "has_data": has_data,
    }

    alert_list = analyze(user=user, data=data)
    data["insights"] = alert_list
    data["alerts_critical"] = [i for i in alert_list if i.severity == "critical"]
    data["alerts_attention"] = [i for i in alert_list if i.severity == "attention"]
    data["alerts_info"] = [i for i in alert_list if i.severity == "info"]
    data["has_alerts"] = bool(alert_list)
    return data


def _filter_recent_by_period(rows, start: date, end: date) -> list[RecentTransaction]:
    return [r for r in rows if start <= r.date <= end]


def _period_history(user, today, accounts_filter, cards_filter) -> dict:
    """Histórico para padrão pessoal e anomalia.

    - ``current_cat``    : gasto por categoria no mês corrente (até hoje).
    - ``pattern``        : {cat_id: (média mensal, nº de meses com dado)} dos 3
                           meses anteriores completos.
    - ``avg_expense``    : despesa média nas últimas 30 dias (amostra >= 5).
    - ``recent_expenses``: maiores despesas do mês corrente (para anomalia).
    """
    first_of_month = today.replace(day=1)
    current_cat = _cat_expense(user, first_of_month, today, accounts_filter, cards_filter)

    # Média de despesa (janela 30 dias) + maiores despesas do mês
    start30 = today - timedelta(days=29)
    exp_qs = (
        Transaction.objects.for_user(user)
        .filter(type=Transaction.Type.EXPENSE, date__gte=start30, date__lte=today)
    )
    if accounts_filter:
        exp_qs = exp_qs.filter(account__in=accounts_filter)
    if cards_filter:
        exp_qs = exp_qs.filter(paid_invoices__card__in=cards_filter)
    amounts = list(exp_qs.values_list("amount", flat=True))
    avg_expense = None
    if len(amounts) >= _AVG_EXPENSE_MIN_SAMPLE:
        avg_expense = int(sum(amounts) / len(amounts))

    recent_expenses = []
    month_exp = (
        Transaction.objects.for_user(user)
        .filter(type=Transaction.Type.EXPENSE, date__gte=first_of_month, date__lte=today)
    )
    if accounts_filter:
        month_exp = month_exp.filter(account__in=accounts_filter)
    if cards_filter:
        month_exp = month_exp.filter(paid_invoices__card__in=cards_filter)
    for tx in month_exp.select_related("account", "category").order_by("-amount")[:10]:
        recent_expenses.append(
            RecentTransaction(
                pk=tx.pk,
                date=tx.date,
                description=tx.description or tx.get_type_display(),
                category=tx.category.name if tx.category_id else None,
                account=tx.account.name,
                amount=tx.amount,
                type=tx.type,
            )
        )

    # Padrão pessoal por categoria (3 meses anteriores completos)
    pattern = {}
    prev_months = []
    cursor = first_of_month
    for _ in range(3):
        cursor = _add_months(cursor, -1)
        prev_months.insert(0, cursor)
    per_month = [_cat_expense(user, m, _end_of_month(m), accounts_filter, cards_filter) for m in prev_months]
    all_ids = set(current_cat.keys())
    for cm in per_month:
        all_ids.update(cm.keys())
    for cat_id in all_ids:
        sample = sum(1 for cm in per_month if cm.get(cat_id, 0) > 0)
        total = sum(cm.get(cat_id, 0) for cm in per_month)
        if sample >= 1:
            pattern[cat_id] = (total // 3, sample)

    return {
        "current_cat": current_cat,
        "pattern": pattern,
        "names": _cat_names(user, all_ids),
        "avg_expense": avg_expense,
        "recent_expenses": recent_expenses,
    }


def _cat_expense(user, start, end, accounts_filter, cards_filter) -> dict:
    qs = Transaction.objects.for_user(user).filter(
        type=Transaction.Type.EXPENSE, date__gte=start, date__lte=end
    )
    if accounts_filter:
        qs = qs.filter(account__in=accounts_filter)
    if cards_filter:
        qs = qs.filter(paid_invoices__card__in=cards_filter)
    rows = qs.values("category_id").annotate(total=Sum("amount"))
    return {r["category_id"]: r["total"] or 0 for r in rows}


def _cat_names(user, ids) -> dict:
    names = {}
    queryset = Category.objects.filter(owner=user, pk__in=[i for i in ids if i is not None])
    for cat in queryset:
        names[cat.pk] = cat.name
    return names


def _end_of_month(m: date) -> date:
    return m.replace(day=monthrange(m.year, m.month)[1])


def _add_months(source: date, months: int) -> date:
    year = source.year
    month = source.month + months
    while month > 12:
        month -= 12
        year += 1
    while month < 1:
        month += 12
        year -= 1
    day = min(source.day, monthrange(year, month)[1])
    return source.replace(year=year, month=month, day=day)


def _fmt(cents: int) -> str:
    """Formata centavos como 'R$ 1.234,56' (sem sinal, para textos)."""
    try:
        cents = int(cents)
    except (TypeError, ValueError):
        return "R$ 0,00"
    sign = "-" if cents < 0 else ""
    cents = abs(cents)
    reais, cs = divmod(cents, 100)
    return f"{sign}R$ {reais:,}".replace(",", ".") + f",{cs:02d}"


def _month_nav(month_start) -> dict:
    """Links de navegação entre meses (anterior/próximo) para o dashboard."""
    from datetime import date as _date

    prev = _add_months(month_start, -1)
    nxt = _add_months(month_start, 1)
    return {
        "prev": f"{prev.year}-{prev.month:02d}",
        "next": f"{nxt.year}-{nxt.month:02d}",
        "current": f"{month_start.year}-{month_start.month:02d}",
        "prev_label": prev.strftime("%b/%y"),
        "next_label": nxt.strftime("%b/%y"),
        "current_label": month_start.strftime("%b/%y"),
    }
