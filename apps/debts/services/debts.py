"""Serviços de dívidas (Debt) e seus pagamentos.

Cada pagamento de dívida é um lançamento financeiro real (Transaction.EXPENSE
na conta do usuário) — a rastreabilidade vem do sistema de contas já existente,
sem criar segunda contabilidade paralela nem modelo adicional de pagamento.
``Debt.paid_amount`` acumula os pagamentos; regras duras impedem pagamento
acima do saldo restante, saldo negativo, duplicação e acesso não autorizado.
"""

from django.db import transaction as db_transaction
from django.utils import timezone

from apps.finance.models import Account, Transaction
from apps.finance.services import transactions as transactions_svc
from apps.finance.services.base import require_owned
from apps.finance.services.errors import InvalidAmountError, InvalidStateError

from ..models import Debt


def _require_debt(user, debt):
    require_owned(
        Debt.objects, user, model_label="Dívida",
        object_id=getattr(debt, "pk", None),
    )
    return debt


def _require_account(user, account):
    require_owned(
        Account.objects, user, model_label="Conta",
        object_id=getattr(account, "pk", None),
    )
    return account


def _validate_amount(amount, *, field="valor", allow_zero=False):
    if isinstance(amount, bool) or not isinstance(amount, int):
        raise InvalidAmountError(f"{field} deve ser um inteiro em centavos.")
    if allow_zero:
        if amount < 0:
            raise InvalidAmountError(f"{field} não pode ser negativo.")
    elif amount <= 0:
        raise InvalidAmountError(f"{field} deve ser maior que zero.")
    return amount


def create_debt(
    *,
    user,
    name,
    total_amount,
    type=Debt.Type.LOAN,
    paid_amount=0,
    interest_rate=None,
    start_date=None,
    end_date=None,
    creditor="",
):
    """Cria uma dívida pertencente ao usuário.

    - total_amount deve ser > 0;
    - paid_amount inicial >= 0 e nunca maior que total_amount;
    - status inicial: ACTIVE, ou PAID_OFF se já quitação integral.
    """
    name = (name or "").strip()
    if not name:
        raise ValueError("nome da dívida é obrigatório.")
    total_amount = _validate_amount(total_amount, field="valor total")
    paid_amount = _validate_amount(paid_amount or 0, field="valor pago", allow_zero=True)
    if paid_amount > total_amount:
        raise InvalidAmountError("valor pago não pode exceder o valor total.")
    status = Debt.Status.PAID_OFF if paid_amount >= total_amount else Debt.Status.ACTIVE
    return Debt.objects.create(
        owner=user,
        type=type,
        name=name,
        total_amount=total_amount,
        paid_amount=paid_amount,
        interest_rate=interest_rate,
        start_date=start_date,
        end_date=end_date,
        creditor=creditor or "",
        status=status,
    )


def update_debt(
    *,
    user,
    debt,
    name=None,
    total_amount=None,
    type=None,
    interest_rate=None,
    start_date=None,
    end_date=None,
    creditor=None,
):
    """Atualiza campos editáveis de uma dívida (ownership validado).

    Se o valor total aumentar, o saldo restante cresce; se cair abaixo do já
    pago, o pagamento acumulado é limitado ao novo total (não cria negativo).
    """
    _require_debt(user, debt)
    if name is not None:
        name = (name or "").strip()
        if not name:
            raise ValueError("nome da dívida é obrigatório.")
        debt.name = name
    if total_amount is not None:
        debt.total_amount = _validate_amount(total_amount, field="valor total")
    if type is not None:
        debt.type = type
    if interest_rate is not None:
        debt.interest_rate = interest_rate
    if start_date is not None:
        debt.start_date = start_date
    if end_date is not None:
        debt.end_date = end_date
    if creditor is not None:
        debt.creditor = creditor or ""
    if debt.paid_amount > debt.total_amount:
        debt.paid_amount = debt.total_amount
    if debt.paid_amount >= debt.total_amount:
        debt.status = Debt.Status.PAID_OFF
    elif debt.status == Debt.Status.PAID_OFF:
        debt.status = Debt.Status.ACTIVE
    debt.save()
    return debt


def delete_debt(*, user, debt):
    """Exclui uma dívida (ownership validado). Não apaga histórico de transações."""
    _require_debt(user, debt)
    debt.delete()


def get_debt(*, user, debt_id):
    """Retorna a dívida do usuário ou sobe ForbiddenResourceError."""
    return require_owned(Debt.objects, user, model_label="Dívida", object_id=debt_id)


def get_debts(*, user, statuses=None):
    """Lista dívidas do usuário (ativas/inadimplentes por padrão)."""
    qs = Debt.objects.for_user(user)
    if statuses is not None:
        qs = qs.filter(status__in=statuses)
    else:
        qs = qs.filter(
            status__in=[Debt.Status.ACTIVE, Debt.Status.DEFAULTED]
        )
    return qs.order_by("name")


def record_debt_payment(
    *,
    user,
    debt,
    account,
    amount,
    date=None,
    source=Transaction.Source.MANUAL,
    notes="",
):
    """Registra um pagamento de dívida (atômico, com rastreabilidade).

    - A conta e a dívida devem pertencer ao usuário.
    - Pagamento acima do saldo restante é recusado (saldo nunca fica negativo).
    - Cria UMA Transaction.EXPENSE na conta (rastreabilidade real).
    - Acumula em ``paid_amount``; ao quitar, a dívida passa a PAID_OFF.
    """
    _require_debt(user, debt)
    _require_account(user, account)
    if debt.status == Debt.Status.PAID_OFF:
        raise InvalidStateError("A dívida já foi quitada.")
    amount = _validate_amount(amount, field="valor do pagamento")
    remaining = debt.total_amount - debt.paid_amount
    if remaining <= 0:
        raise InvalidStateError("A dívida já está quitada.")
    if amount > remaining:
        raise InvalidAmountError(
            "Pagamento acima do saldo restante não é permitido."
        )

    payment_date = date or timezone.localdate()
    with db_transaction.atomic():
        transaction = transactions_svc.record_expense(
            user=user,
            account=account,
            amount=amount,
            date=payment_date,
            description=f"Pagamento de dívida — {debt.name}",
            source=source,
            notes=notes,
        )
        # FASE 8: marca como movimentação neutra (não vira consumo comum),
        # sem alterar a contabilização.
        from apps.finance.services.classifier import record_movement_analysis
        record_movement_analysis(user=user, transaction=transaction)
        debt.paid_amount = debt.paid_amount + amount
        if debt.paid_amount >= debt.total_amount:
            debt.paid_amount = debt.total_amount
            debt.status = Debt.Status.PAID_OFF
        debt.save()
    return transaction


def set_debt_status(*, user, debt, status):
    """Altera o status de uma dívida (ownership validado).

    Transições administrativas: marcar inadimplente, reabrir e arquivar.
    Não permite arquivar/quitar de forma inconsistente:
    - reabrir uma dívida requer status ACTIVE;
    - não é possível marcar PAID_OFF manualmente (deduzido por pagamentos);
    - arquivar exige active/inadimplente.
    """
    _require_debt(user, debt)
    allowed = {Debt.Status.ACTIVE, Debt.Status.DEFAULTED, Debt.Status.ARCHIVED}
    if status not in allowed:
        raise InvalidStateError("Status inválido para esta operação.")
    if status == Debt.Status.ACTIVE and debt.status in (
        Debt.Status.ARCHIVED, Debt.Status.DEFAULTED,
    ):
        debt.status = Debt.Status.ACTIVE
        debt.save()
        return debt
    if debt.status == Debt.Status.PAID_OFF:
        raise InvalidStateError(
            "Uma dívida quitada não pode ser reclassificada manualmente."
        )
    debt.status = status
    debt.save()
    return debt


def get_debt_progress(*, user, debt, ref_date=None):
    """Progresso de uma dívida: pago, restante, percentual, vencimento e status."""
    _require_debt(user, debt)
    total = debt.total_amount
    paid = debt.paid_amount
    remaining = debt.remaining_amount
    percent = int(round(paid / total * 100)) if total else 0
    return {
        "debt": debt,
        "total_amount": total,
        "paid_amount": paid,
        "remaining_amount": remaining,
        "percent": percent,
        "end_date": debt.end_date,
        "status": debt.status,
    }


def get_debt_summary(*, user, ref_date=None):
    """Resumo das dívidas ativas/inadimplentes do usuário.

    - total_remaining, total_amount, paid_amount, overall_percent;
    - overdue: dívidas inadimplentes ou com vencimento <= hoje ainda ativas;
    - next_due: dívidas ativas ordenadas por vencimento (mais próximas primeiro).
    """
    debts = list(
        get_debts(user=user, statuses=[Debt.Status.ACTIVE, Debt.Status.DEFAULTED])
    )
    if not debts:
        return {
            "debts": [], "rows": [],
            "total_amount": 0, "paid_amount": 0,
            "total_remaining": 0, "overall_percent": 0,
            "overdue": [], "next_due": [],
        }
    rows = [
        get_debt_progress(user=user, debt=d, ref_date=ref_date) for d in debts
    ]
    total_amount = sum(d.total_amount for d in debts)
    paid_amount = sum(d.paid_amount for d in debts)
    total_remaining = sum(d.remaining_amount for d in debts)
    overall = int(round(paid_amount / total_amount * 100)) if total_amount else 0
    from django.utils.timezone import localdate as tz_localdate

    today = tz_localdate()
    overdue = [
        r for r in rows
        if r["status"] == Debt.Status.DEFAULTED
        or (r["status"] == Debt.Status.ACTIVE and r["end_date"] and r["end_date"] < today)
    ]
    next_due = sorted(
        [r for r in rows if r["status"] == Debt.Status.ACTIVE and r["end_date"]],
        key=lambda r: r["end_date"],
    )
    return {
        "debts": debts,
        "rows": rows,
        "total_amount": total_amount,
        "paid_amount": paid_amount,
        "total_remaining": total_remaining,
        "overall_percent": overall,
        "overdue": overdue,
        "next_due": next_due,
    }
