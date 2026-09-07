"""Camada de LEITURA do dashboard (read layer).

Responsável por transformar os dados do banco em métricas agregadas e
estruturas prontas para o ViewModel. Nenhuma regra financeira de escrita é
duplicada aqui; apenas LEITURA eficiente (agregações no banco, sem N+1).

Todas as consultas são vinculadas ao usuário autenticado via ``for_user`` /
``owner=user`` — nunca aceitam um ``owner_id`` vindo da interface (regra 27).

Definições financeiras (ver docs/DASHBOARD.md):
- disponível        : soma dos saldos das contas ATIVAS.
- comprometido      : obrigações de cartão ainda não liquidadas (parcelas
                      pendentes + atrasadas de todas as faturas).
- disponível_após   : disponível − comprometido.
- receitas/despesas : soma de receitas/despesas (Transaction) no período.
                      Compras no cartão NÃO contam como despesa aqui; só a
                      liquidação da fatura (uma Expense) — sem dupla contabilização.
- resultado        : receitas − despesas.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from django.db.models import (
    Case,
    F,
    IntegerField,
    Q,
    Sum,
    Value,
    When,
)
from django.db.models.functions import TruncMonth

from apps.budgets.models import Budget
from apps.cards.models import CreditCard, CreditCardInvoice, Installment
from apps.debts.models import Debt
from apps.finance.models import Account, Category, RecurringRule, Transaction
from apps.goals.models import Goal

# --------------------------------------------------------------------------- #
# Períodos
# --------------------------------------------------------------------------- #

PERIODS = {
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
    "3m": None,  # tratado como trimestre civil
    "6m": None,
    "12m": None,
}


def resolve_period(period_key: str, today: date | None = None) -> dict:
    """Converte uma chave de período em período concreto (start, end).

    ``today`` é a data de referência (usa timezone local em produção). Os
    períodos de meses usam meses civis completos: "3m" = últimos 3 meses
    completos + o mês atual corrente.
    """
    today = today or _today()
    key = (period_key or "30d").lower()
    if key == "7d":
        return {"key": "7d", "label": "Últimos 7 dias", "start": today - timedelta(days=6), "end": today}
    if key == "3m":
        start = _months(_first_of_month(today), 3)
    elif key == "6m":
        start = _months(_first_of_month(today), 6)
    elif key == "12m":
        start = _months(_first_of_month(today), 12)
    else:  # 30d (padrão)
        return {"key": "30d", "label": "Últimos 30 dias", "start": today - timedelta(days=29), "end": today}
    start = start.replace(day=1)
    return {"key": key, "label": _period_label(key), "start": start, "end": today}


def _period_label(key: str) -> str:
    return {
        "7d": "Últimos 7 dias",
        "30d": "Últimos 30 dias",
        "3m": "Últimos 3 meses",
        "6m": "Últimos 6 meses",
        "12m": "Últimos 12 meses",
    }.get(key, "Período")


def _today() -> date:
    from django.utils import timezone

    return timezone.localdate()


def _first_of_month(d: date) -> date:
    return d.replace(day=1)


def _months(d: date, n: int) -> date:
    """Avança n meses (regra de datas financeiras) — não sai antes do dia 1."""
    return _add_months(d, -n)


def _add_months(source: date, months: int) -> date:
    from calendar import monthrange

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


# --------------------------------------------------------------------------- #
# Dataclasses de saída (agrupadas por domínio)
# --------------------------------------------------------------------------- #


@dataclass
class AccountBalance:
    pk: int
    name: str
    type: str
    institution: str
    balance: int


@dataclass
class CashFlow:
    receitas: int
    despesas: int
    resultado: int
    transfer_in: int
    transfer_out: int
    count: int


@dataclass
class CategorySpend:
    name: str
    amount: int
    share_percent: int
    prev_amount: int | None
    prev_share_percent: int | None
    delta_percent: int | None  # % de variação vs período anterior (vazio se sem base)


@dataclass
class MonthBucket:
    label: str
    receitas: int
    despesas: int
    saldo: int
    receitas_ratio: int = 0
    despesas_ratio: int = 0


@dataclass
class UpcomingEvent:
    date: date
    amount: int
    label: str
    kind: str  # invoice | recurrence
    source: str  # texto do cartão/conta


@dataclass
class AccountSummary:
    pk: int
    name: str
    type: str
    type_label: str
    balance: int
    share_percent: int


@dataclass
class CreditCardSummary:
    pk: int
    name: str
    limit: int
    used: int
    available: int
    used_pct: int
    usage_tone: str
    open_invoice_amount: int | None
    next_invoice_due: date | None
    future_installment_total: int


@dataclass
class InvoiceRow:
    pk: int
    card_name: str
    due_date: date
    closing_date: date
    status: str
    amount: int


@dataclass
class InstallmentRow:
    pk: int
    description: str
    card_name: str
    total_monthly: int
    remaining_count: int
    remaining_total: int


@dataclass
class BudgetRow:
    pk: int
    name: str
    limit: int
    spent: int
    remaining: int
    percent: int
    status: str  # healthy | attention | exceeded


@dataclass
class GoalRow:
    pk: int
    name: str
    target_amount: int
    current_amount: int
    progress_percent: int
    target_date: date | None
    priority: str
    status: str


@dataclass
class DebtRow:
    pk: int
    name: str
    total_amount: int
    paid_amount: int
    remaining_amount: int


@dataclass
class RecentTransaction:
    pk: int
    date: date
    description: str
    category: str | None
    account: str
    amount: int
    type: str


# --------------------------------------------------------------------------- #
# Construção de filtros de base (transações)
# --------------------------------------------------------------------------- #


def _tx_qs(user, *, accounts=None, cards=None):
    """QuerySet base de transações, já isolado por usuário."""
    qs = Transaction.objects.for_user(user)
    if accounts:
        qs = qs.filter(account__in=accounts)
    if cards:
        # Filtro por cartão: considera apenas despesas de pagamento de fatura
        # vinculadas a faturas desse(s) cartão(ões).
        qs = qs.filter(paid_invoices__card__in=cards)
    return qs


def _account_ids(user):
    return list(
        Account.objects.for_user(user)
        .filter(status=Account.Status.ACTIVE)
        .values_list("pk", flat=True)
    )


# --------------------------------------------------------------------------- #
# Saldo das contas (agregado em banco — evita N+1)
# --------------------------------------------------------------------------- #


def account_balances(user) -> dict[int, AccountBalance]:
    """Saldo de cada conta ATIVA, calculado por agregação SQL.

    ``disponível`` = contas ativas; contas encerradas/arquivadas NÃO entram
    no dinheiro disponível (regra de liquidez).
    """
    accounts = list(
        Account.objects.for_user(user)
        .filter(status=Account.Status.ACTIVE)
        .order_by("name")
    )
    ids = [a.pk for a in accounts]
    balances = {a.pk: a.initial_balance for a in accounts}
    if ids:
        agg = (
            Transaction.objects.for_user(user)
            .filter(account_id__in=ids)
            .values("account_id")
            .annotate(
                _income=Sum(
                    Case(
                        When(type=Transaction.Type.INCOME, then=F("amount")),
                        default=Value(0),
                        output_field=IntegerField(),
                    )
                ),
                _outgo=Sum(
                    Case(
                        When(
                            type__in=[
                                Transaction.Type.EXPENSE,
                                Transaction.Type.ADJUSTMENT,
                            ],
                            then=F("amount"),
                        ),
                        default=Value(0),
                        output_field=IntegerField(),
                    )
                ),
                _transfer_effect=Sum(
                    Case(
                        When(
                            type=Transaction.Type.TRANSFER,
                            transfer_out__isnull=False,
                            then=-F("amount"),
                        ),
                        When(
                            type=Transaction.Type.TRANSFER,
                            transfer_in__isnull=False,
                            then=F("amount"),
                        ),
                        default=Value(0),
                        output_field=IntegerField(),
                    )
                ),
            )
        )
        for row in agg:
            balances[row["account_id"]] = (
                balances[row["account_id"]]
                + (row["_income"] or 0)
                - (row["_outgo"] or 0)
                + (row["_transfer_effect"] or 0)
            )
    return {
        a.pk: AccountBalance(
            pk=a.pk,
            name=a.name,
            type=a.type,
            institution=a.institution,
            balance=balances[a.pk],
        )
        for a in accounts
    }


def net_balance(user) -> int:
    """Soma dos saldos das contas ativas (dinheiro disponível)."""
    return sum(ab.balance for ab in account_balances(user).values())


# --------------------------------------------------------------------------- #
# Comprometido (obrigações de cartão)
# --------------------------------------------------------------------------- #


def committed(user) -> int:
    """Total de parcelas pendentes/atrasadas de cartão (obrigação não liquidada)."""
    agg = (
        Installment.objects.filter(
            purchase__owner=user,
            status__in=[Installment.Status.PENDING, Installment.Status.OVERDUE],
        ).aggregate(total=Sum("amount"))
    )
    return agg["total"] or 0


def committed_by_card(user) -> list[CreditCardSummary]:
    """Carteira resumida de cada cartão do usuário."""
    cards = list(
        CreditCard.objects.for_user(user).filter(status=CreditCard.Status.ACTIVE)
    )
    used_by_card = {}
    if cards:
        agg = (
            Installment.objects.filter(
                purchase__owner=user,
                status__in=[Installment.Status.PENDING, Installment.Status.OVERDUE],
            )
            .values("purchase__card_id")
            .annotate(total=Sum("amount"))
        )
        for row in agg:
            used_by_card[row["purchase__card_id"]] = row["total"] or 0

    # Fatura aberta mais próxima por cartão
    open_invoices = {}
    if cards:
        for row in (
            CreditCardInvoice.objects.filter(
                owner=user,
                card__in=cards,
                status__in=[
                    CreditCardInvoice.Status.OPEN,
                    CreditCardInvoice.Status.OVERDUE,
                ],
            )
            .order_by("card_id", "due_date")
            .values("card_id", "id", "due_date")
        ):
            open_invoices.setdefault(row["card_id"], row)

    invoice_ids = [inv["id"] for inv in open_invoices.values()]
    invoice_totals = _invoice_amounts(user, invoice_ids)

    summaries = []
    for card in cards:
        used = used_by_card.get(card.pk, 0)
        available = max(card.limit - used, 0)
        inv = open_invoices.get(card.pk)
        open_amount = None
        next_due = (inv or {}).get("due_date")
        if inv:
            open_amount = invoice_totals.get(inv["id"])
        summaries.append(
            CreditCardSummary(
                pk=card.pk,
                name=card.name,
                limit=card.limit,
                used=used,
                available=available,
                used_pct=int(round(used / card.limit * 100)) if card.limit else 0,
                usage_tone=_usage_tone(used, card.limit),
                open_invoice_amount=open_amount,
                next_invoice_due=next_due,
                future_installment_total=used,
            )
        )
    return summaries


def _usage_tone(used: int, limit: int) -> str:
    if limit <= 0:
        return "healthy"
    pct = used / limit * 100
    if pct >= 90:
        return "exceeded"
    if pct >= 70:
        return "attention"
    return "healthy"


def _invoice_amounts(user, invoice_ids) -> dict[int, int]:
    """Valores totais (derivados) de várias faturas em uma única query."""
    if not invoice_ids:
        return {}
    rows = (
        Installment.objects.filter(
            invoice_id__in=invoice_ids, purchase__owner=user
        )
        .values("invoice_id")
        .annotate(total=Sum("amount"))
    )
    return {r["invoice_id"]: r["total"] or 0 for r in rows}


def _invoice_amount(user, invoice_id, card) -> int:
    """Valor (derivado) de uma fatura = soma das parcelas do período."""
    return _invoice_amounts(user, [invoice_id]).get(invoice_id, 0)


# --------------------------------------------------------------------------- #
# Fluxo de caixa (receitas / despesas / resultado) por período
# --------------------------------------------------------------------------- #


def cash_flow(user, *, start, end, accounts=None, cards=None) -> CashFlow:
    """Receitas/despesas/transferências no intervalo [start, end].

    - Receitas/transferências NÃO são atribuíveis a cartão; o filtro ``cards``
      restringe APENAS as despesas (pagamentos de fatura) desses cartões.
    - Despesas agrupam expense + adjustment.
    """
    inc_qs = (
        Transaction.objects.for_user(user)
        .filter(type=Transaction.Type.INCOME, date__gte=start, date__lte=end)
    )
    if accounts:
        inc_qs = inc_qs.filter(account__in=accounts)
    receitas = inc_qs.aggregate(total=Sum("amount"))["total"] or 0

    exp_qs = (
        Transaction.objects.for_user(user)
        .filter(
            type__in=[Transaction.Type.EXPENSE, Transaction.Type.ADJUSTMENT],
            date__gte=start,
            date__lte=end,
        )
    )
    if accounts:
        exp_qs = exp_qs.filter(account__in=accounts)
    if cards:
        exp_qs = exp_qs.filter(paid_invoices__card__in=cards)
    despesas = exp_qs.aggregate(total=Sum("amount"))["total"] or 0

    transfer_qs = (
        Transaction.objects.for_user(user)
        .filter(type=Transaction.Type.TRANSFER, date__gte=start, date__lte=end)
    )
    if accounts:
        transfer_qs = transfer_qs.filter(account__in=accounts)
    legs = transfer_qs.values("account_id").annotate(
        _in=Sum(
            Case(
                When(transfer_in__isnull=False, then=F("amount")),
                default=Value(0),
                output_field=IntegerField(),
            )
        ),
        _out=Sum(
            Case(
                When(transfer_out__isnull=False, then=F("amount")),
                default=Value(0),
                output_field=IntegerField(),
            )
        ),
    )
    transfer_in = sum((r["_in"] or 0) for r in legs)
    transfer_out = sum((r["_out"] or 0) for r in legs)

    has = any(
        v
        for v in (
            receitas,
            despesas,
            transfer_in,
            transfer_out,
        )
    )
    return CashFlow(
        receitas=receitas,
        despesas=despesas,
        resultado=receitas - despesas,
        transfer_in=transfer_in,
        transfer_out=transfer_out,
        count=1 if has else 0,
    )


# --------------------------------------------------------------------------- #
# Gastos por categoria (com comparação ao período anterior)
# --------------------------------------------------------------------------- #


def spending_by_category(user, *, start, end, accounts=None, cards=None) -> list[CategorySpend]:
    """Despesas por categoria no período, com comparação ao período anterior."""
    current = _category_expense_agg(user, start, end, accounts, cards)
    prev_start, prev_end = _prev_period(start, end)
    previous = _category_expense_agg(user, prev_start, prev_end, accounts, cards)

    total = sum(current.values())
    prev_total = sum(previous.values())

    rows = []
    cat_names = _category_names(user, current.keys() | previous.keys())
    for cat_id, amount in sorted(current.items(), key=lambda x: -x[1]):
        prev = previous.get(cat_id)
        share = int(round((amount / total * 100))) if total else 0
        prev_share = int(round((prev / prev_total * 100))) if (prev_total and prev) else None
        delta = None
        if prev:
            delta = int(round((amount - prev) / prev * 100))
        rows.append(
            CategorySpend(
                name=cat_names.get(cat_id, "Sem categoria"),
                amount=amount,
                share_percent=share,
                prev_amount=prev,
                prev_share_percent=prev_share,
                delta_percent=delta,
            )
        )
    return rows


def _prev_period(start: date, end: date) -> tuple[date, date]:
    span = (end - start).days + 1
    return start - timedelta(days=span), end - timedelta(days=span)


def _category_expense_agg(user, start, end, accounts, cards) -> dict:
    qs = (
        Transaction.objects.for_user(user)
        .filter(
            type=Transaction.Type.EXPENSE,
            date__gte=start,
            date__lte=end,
        )
    )
    if accounts:
        qs = qs.filter(account__in=accounts)
    if cards:
        qs = qs.filter(paid_invoices__card__in=cards)
    rows = qs.values("category_id").annotate(total=Sum("amount"))
    return {r["category_id"]: r["total"] or 0 for r in rows}


def _category_names(user, ids) -> dict:
    names = {}
    for cat in Category.objects.filter(owner=user, pk__in=[i for i in ids if i is not None]):
        names[cat.pk] = cat.name
    return names


# --------------------------------------------------------------------------- #
# Evolução mensal (gráfico de tendência)
# --------------------------------------------------------------------------- #


def monthly_evolution(user, *, start, end, accounts=None, cards=None) -> list[MonthBucket]:
    """Agrega receitas e despesas por mês civil no intervalo."""
    qs = (
        Transaction.objects.for_user(user)
        .filter(date__gte=start, date__lte=end)
        .annotate(month=TruncMonth("date"))
        .values("month")
        .annotate(
            _income=Sum(
                Case(
                    When(type=Transaction.Type.INCOME, then=F("amount")),
                    default=Value(0),
                    output_field=IntegerField(),
                )
            ),
            _expense=Sum(
                Case(
                    When(
                        type__in=[
                            Transaction.Type.EXPENSE,
                            Transaction.Type.ADJUSTMENT,
                        ],
                        then=F("amount"),
                    ),
                    default=Value(0),
                    output_field=IntegerField(),
                )
            ),
        )
    )
    if accounts:
        qs = qs.filter(account__in=accounts)
    if cards:
        qs = qs.filter(paid_invoices__card__in=cards)

    data = {}
    for row in qs:
        data[row["month"]] = (row["_income"] or 0, row["_expense"] or 0)

    buckets = []
    current = start.replace(day=1)
    end_first = end.replace(day=1)
    while current <= end_first:
        income, expense = data.get(current, (0, 0))
        buckets.append(
            MonthBucket(
                label=current.strftime("%b/%y"),
                receitas=income,
                despesas=expense,
                saldo=income - expense,
            )
        )
        current = _add_months(current, 1)

    peak = max((max(b.receitas, b.despesas) for b in buckets), default=0)
    for b in buckets:
        b.receitas_ratio = int(round(b.receitas / peak * 100)) if peak else 0
        b.despesas_ratio = int(round(b.despesas / peak * 100)) if peak else 0
    return buckets


# --------------------------------------------------------------------------- #
# Próximos eventos (timeline 30 dias)
# --------------------------------------------------------------------------- #


def upcoming_events(user, *, days=30) -> list[UpcomingEvent]:
    """Eventos financeiros próximos: faturas abertas + recorrências projetadas."""
    today = _today()
    horizon = today + timedelta(days=days)
    events: list[UpcomingEvent] = []

    # 1) Faturas abertas/atrasadas com vencimento no horizonte.
    invoices = list(
        CreditCardInvoice.objects.filter(
            owner=user,
            status__in=[
                CreditCardInvoice.Status.OPEN,
                CreditCardInvoice.Status.OVERDUE,
            ],
        ).select_related("card")
    )
    invoice_totals = _invoice_amounts(user, [i.pk for i in invoices])
    for inv in invoices:
        if inv.due_date < today and inv.status == CreditCardInvoice.Status.OVERDUE:
            label, kind = f"Fatura em atraso — {inv.card.name}", "invoice"
        elif today <= inv.due_date <= horizon:
            label, kind, = f"Fatura — {inv.card.name}", "invoice"
        else:
            continue
        events.append(
            UpcomingEvent(
                date=inv.due_date,
                amount=invoice_totals.get(inv.pk, 0),
                label=label,
                kind=kind,
                source=inv.card.name,
            )
        )

    # 2) Recorrências ativas: próxima ocorrência dentro do horizonte.
    from apps.finance.services.recurrences import occurrence_date

    rules = list(
        RecurringRule.objects.for_user(user).filter(status=RecurringRule.Status.ACTIVE)
    )
    for rule in rules:
        occ = occurrence_date(rule, today)
        # ajusta para a ocorrência mais próxima >= hoje
        while occ < rule.start_date:
            occ = _next_occurrence(rule, occ)
        if occ < today:
            nxt = _next_occurrence(rule, occ)
            if nxt >= today:
                occ = nxt
        if rule.end_date and occ > rule.end_date:
            continue
        if today <= occ <= horizon:
            events.append(
                UpcomingEvent(
                    date=occ,
                    amount=rule.amount,
                    label=f"Recorrência — {rule.title}",
                    kind="recurrence",
                    source=rule.title,
                )
            )

    events.sort(key=lambda e: (e.date, e.kind))
    return events[:40]


def _next_occurrence(rule, current: date) -> date:
    from apps.finance.services.recurrences import occurrence_date

    # Salta para o período seguinte (semanal: +7 dias; mensal: próximo mês).
    if rule.frequency == RecurringRule.Frequency.WEEKLY:
        from datetime import timedelta as td

        return occurrence_date(rule, current + td(days=7))
    return occurrence_date(rule, _add_months(current, 1))


# --------------------------------------------------------------------------- #
# Faturas e parcelas
# --------------------------------------------------------------------------- #


def upcoming_invoices(user, *, limit=6) -> list[InvoiceRow]:
    today = _today()
    invoices = list(
        CreditCardInvoice.objects.filter(
            owner=user,
            status__in=[
                CreditCardInvoice.Status.OPEN,
                CreditCardInvoice.Status.OVERDUE,
            ],
            due_date__gte=today,
        )
        .select_related("card")
        .order_by("due_date")[:limit]
    )
    invoice_totals = _invoice_amounts(user, [i.pk for i in invoices])
    rows = []
    for inv in invoices:
        rows.append(
            InvoiceRow(
                pk=inv.pk,
                card_name=inv.card.name,
                due_date=inv.due_date,
                closing_date=inv.closing_date,
                status=inv.status,
                amount=invoice_totals.get(inv.pk, 0),
            )
        )
    return rows


def installment_obligations(user, *, limit=8) -> list[InstallmentRow]:
    """Obrigações futuras: compras parceladas pendentes."""
    pending = list(
        Installment.objects.filter(
            purchase__owner=user,
            status__in=[Installment.Status.PENDING, Installment.Status.OVERDUE],
        )
        .select_related("purchase", "purchase__card")
        .order_by("due_date")
    )
    by_purchase: dict[int, list] = {}
    for inst in pending:
        by_purchase.setdefault(inst.purchase_id, []).append(inst)

    rows = []
    for purchase_id, insts in by_purchase.items():
        purchase = insts[0].purchase
        monthly = sum(i.amount for i in insts)
        rows.append(
            InstallmentRow(
                pk=purchase_id,
                description=purchase.description,
                card_name=purchase.card.name,
                total_monthly=monthly,
                remaining_count=len(insts),
                remaining_total=monthly,
            )
        )
    rows.sort(key=lambda r: -r.remaining_total)
    return rows[:limit]


# --------------------------------------------------------------------------- #
# Orçamentos / metas / dívidas
# --------------------------------------------------------------------------- #


def budgets(user, *, today=None) -> list[BudgetRow]:
    today = today or _today()
    active = list(
        Budget.objects.for_user(user).filter(is_active=True).select_related("category")
    )
    period_start = today.replace(day=1)
    rows = []
    if active:
        cat_budgets = [b for b in active if b.kind == Budget.Kind.CATEGORY and b.category]
        global_flag = any(b.kind != Budget.Kind.CATEGORY for b in active)

        # Uma única query: gasto por categoria (e subcategorias) no mês.
        all_cat_ids = set()
        for b in cat_budgets:
            all_cat_ids.add(b.category_id)
            all_cat_ids.update(
                b.category.subcategories.values_list("pk", flat=True)
            )
        spent_by_cat: dict[int, int] = {}
        if all_cat_ids:
            agg = (
                Transaction.objects.for_user(user)
                .filter(
                    type=Transaction.Type.EXPENSE,
                    date__gte=period_start,
                    date__lte=today,
                    category_id__in=all_cat_ids,
                )
                .values("category_id")
                .annotate(total=Sum("amount"))
            )
            for r in agg:
                spent_by_cat[r["category_id"]] = r["total"] or 0
        global_spent = 0
        if global_flag:
            global_spent = (
                Transaction.objects.for_user(user)
                .filter(
                    type=Transaction.Type.EXPENSE,
                    date__gte=period_start,
                    date__lte=today,
                )
                .aggregate(total=Sum("amount"))["total"]
                or 0
            )

        for budget in active:
            cat_budget = budget.kind == Budget.Kind.CATEGORY and budget.category
            if cat_budget:
                ids = [budget.category_id] + list(
                    budget.category.subcategories.values_list("pk", flat=True)
                )
                spent = sum(spent_by_cat.get(cid, 0) for cid in ids)
            else:
                spent = global_spent
            limit = budget.limit_amount
            percent = int(round(spent / limit * 100)) if limit else 0
            status = "healthy"
            if limit and percent >= 100:
                status = "exceeded"
            elif limit and percent >= 80:
                status = "attention"
            rows.append(
                BudgetRow(
                    pk=budget.pk,
                    name=budget.category.name
                    if cat_budget
                    else "Global",
                    limit=limit,
                    spent=spent,
                    remaining=max(limit - spent, 0),
                    percent=percent,
                    status=status,
                )
            )
    return rows


def goals(user) -> list[GoalRow]:
    qs = Goal.objects.for_user(user).filter(
        status__in=[Goal.Status.ACTIVE, Goal.Status.PAUSED]
    )
    return [
        GoalRow(
            pk=g.pk,
            name=g.name,
            target_amount=g.target_amount,
            current_amount=g.current_amount,
            progress_percent=g.progress_percent,
            target_date=g.target_date,
            priority=g.priority,
            status=g.status,
        )
        for g in qs
    ]


def debts(user) -> list[DebtRow]:
    qs = Debt.objects.for_user(user).filter(status=Debt.Status.ACTIVE)
    return [
        DebtRow(
            pk=d.pk,
            name=d.name,
            total_amount=d.total_amount,
            paid_amount=d.paid_amount,
            remaining_amount=d.remaining_amount,
        )
        for d in qs
    ]


# --------------------------------------------------------------------------- #
# Contas / movimentações recentes
# --------------------------------------------------------------------------- #


def account_summary(user, balances=None) -> list[AccountSummary]:
    balances = balances if balances is not None else account_balances(user)
    total = sum(b.balance for b in balances.values())
    account_types = {
        a.pk: (a.type, a.get_type_display())
        for a in Account.objects.for_user(user).filter(status=Account.Status.ACTIVE)
    }
    rows = []
    for ab in sorted(balances.values(), key=lambda b: -b.balance):
        share = int(round((ab.balance / total * 100))) if total else 0
        _type, _label = account_types.get(ab.pk, ("", ""))
        rows.append(
            AccountSummary(
                pk=ab.pk,
                name=ab.name,
                type=_type,
                type_label=_label,
                balance=ab.balance,
                share_percent=share,
            )
        )
    return rows


def recent_transactions(user, *, limit=10, accounts=None, cards=None) -> list[RecentTransaction]:
    qs = (
        Transaction.objects.for_user(user)
        .select_related("account", "category")
        .order_by("-date", "-id")
    )
    if accounts:
        qs = qs.filter(account__in=accounts)
    if cards:
        qs = qs.filter(paid_invoices__card__in=cards)
    rows = []
    for tx in qs[:limit]:
        rows.append(
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
    return rows
