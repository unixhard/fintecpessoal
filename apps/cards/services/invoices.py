"""Serviço de faturas de cartão: determinação, criação e pagamento.

Distingue GASTO de LIQUIDAÇÃO:
- GASTO (obrigação): a compra vira InstallmentPurchase + Installments, sem
  movimentar o banco. Não é uma Transaction.
- LIQUIDAÇÃO (pagamento): ao pagar a fatura, cria UMA Transaction do tipo
  EXPENSE sobre a conta de pagamento, representando a saída de dinheiro.

A modelagem atual JÁ permite essa distinção: `CreditCardInvoice.payment_transaction`
aponta para a transação de liquidação, e o valor da fatura é derivado (soma das
parcelas do período). Assim o gasto aparece uma única vez (no pagamento) e o
pagamento NÃO duplica as compras como novas despesas.
"""

from datetime import date

from django.db import transaction as db_transaction
from django.utils import timezone

from apps.finance.models import Account, Transaction
from apps.finance.services.base import (
    ensure_owned_integer_amount,
    require_owned,
)
from apps.finance.services.errors import InvalidAmountError, InvalidStateError

from ..models import CreditCard, CreditCardInvoice, Installment
from ..models import add_months


def _clamp_day(year, month, day):
    from calendar import monthrange

    return min(day, monthrange(year, month)[1])


def invoice_period(card, purchase_date):
    """Dados do ciclo de fatura que contém ``purchase_date``.

    Regra (baseada em ``closing_day``):
    - se ``purchase_date.day <= closing_day`` -> fecha no mesmo mês;
    - senão -> fecha no mês seguinte (compra entra no próximo ciclo).

    Exemplo (fechamento dia 10):
      compra dia 09 -> ciclo que fecha dia 10 (mesmo mês)
      compra dia 11 -> próximo ciclo (fecha dia 10 do mês seguinte)
    """
    closing_day = card.closing_day or 1
    due_day = card.due_day or 1

    if purchase_date.day <= closing_day:
        close_year, close_month = purchase_date.year, purchase_date.month
    else:
        close_month = purchase_date.month + 1
        close_year = purchase_date.year
        if close_month > 12:
            close_month = 1
            close_year += 1

    closing_date = date(
        close_year, close_month, _clamp_day(close_year, close_month, closing_day)
    )
    previous_closing = add_months(closing_date, -1)
    period_start = date.fromordinal(previous_closing.toordinal() + 1)
    period_end = closing_date

    due_month = close_month + 1
    due_year = close_year
    if due_month > 12:
        due_month = 1
        due_year += 1
    due_date = date(
        due_year, due_month, _clamp_day(due_year, due_month, due_day)
    )

    return {
        "period_start": period_start,
        "period_end": period_end,
        "closing_date": closing_date,
        "due_date": due_date,
    }


def determine_invoice(card, purchase_date):
    """Determina a fatura correspondente a uma compra/parcela.

    Retorna o período do ciclo (period_start, period_end, closing_date,
    due_date) — NÃO materializa nada. Use ``get_or_create_invoice`` para
    criar/obter a fatura de fato (idempotente).
    """
    return invoice_period(card, purchase_date)


def get_or_create_invoice(user, card, purchase_date):
    """Obtém (ou cria) a fatura do ciclo que contém ``purchase_date``.

    Idempotente: há restrição única em (card, period_start, period_end) e a
    consulta primeiro ao invés de criar duplicadas.
    """
    if not card or card.owner_id != user.id:
        require_owned(
            CreditCard.objects, user, model_label="Cartão", object_id=getattr(card, "pk", None)
        )
    period = invoice_period(card, purchase_date)

    invoice = (
        CreditCardInvoice.objects.for_user(user)
        .filter(
            card=card,
            period_start=period["period_start"],
            period_end=period["period_end"],
        )
        .first()
    )
    if invoice is not None:
        return invoice

    return CreditCardInvoice.objects.create(
        owner=user,
        card=card,
        period_start=period["period_start"],
        period_end=period["period_end"],
        closing_date=period["closing_date"],
        due_date=period["due_date"],
        status=CreditCardInvoice.Status.OPEN,
    )


def pay_invoice(
    *,
    user,
    invoice,
    account,
    amount=None,
    date=None,
    source=Transaction.Source.MANUAL,
    notes="",
):
    """Paga (liquida) uma fatura, retirando dinheiro de ``account``.

    - Cria UMA Transaction EXPENSE na conta (a saída real do dinheiro).
    - Marca a fatura como paga e as parcelas como pagas.

    Não duplica as compras: o gasto da compra foi registrado como obrigação no
    cartão (não como despesa no banco); o pagamento é a única saída da conta.

    Pagamento parcial NÃO é suportado nesta modelagem (valor derivado da soma
    das parcelas). Se ``amount`` divergir do devido, a operação é recusada.
    """
    if not invoice or invoice.owner_id != user.id:
        require_owned(
            CreditCardInvoice.objects, user,
            model_label="Fatura", object_id=getattr(invoice, "pk", None),
        )
    if not account or account.owner_id != user.id:
        require_owned(
            Account.objects, user, model_label="Conta", object_id=getattr(account, "pk", None)
        )
    if invoice.status in (CreditCardInvoice.Status.PAID,):
        raise InvalidStateError("A fatura já foi paga.")

    due = invoice.amount
    if due <= 0:
        raise InvalidAmountError("A fatura não possui valor devido.")
    value = amount if amount is not None else due
    value = ensure_owned_integer_amount(value, field="valor do pagamento")
    if value > due:
        raise InvalidAmountError("Pagamento acima do valor devido não é permitido.")
    if value < due:
        raise InvalidStateError(
            "Pagamento parcial não é suportado pela modelagem atual."
        )

    payment_date = date or timezone.localdate()

    with db_transaction.atomic():
        transaction = Transaction.objects.create(
            owner=user,
            type=Transaction.Type.EXPENSE,
            amount=value,
            date=payment_date,
            description=f"Pagamento de fatura — {invoice.card.name}",
            account=account,
            source=source,
            notes=notes,
        )
        # FASE 8: marca como movimentação neutra (não vira consumo comum),
        # sem alterar a contabilização.
        from apps.finance.services.classifier import record_movement_analysis
        record_movement_analysis(user=user, transaction=transaction)
        invoice.payment_transaction = transaction
        invoice.payment_account = account
        invoice.status = CreditCardInvoice.Status.PAID
        invoice.save()
        invoice.installments.update(status=Installment.Status.PAID)

    return transaction


def roll_invoice_statuses(today=None):
    """Avança o status das faturas abertas/fechadas conforme o calendário.

    Fecha o ciclo automaticamente (ciclo de faturas por ``closing_day``/
    ``due_day``) sem depender de trigger do usuário, mas de forma IDEMPOTENTE —
    não há job/cron programado no projeto (Ordem 14, item 3); esta função pode
    ser chamada por um runner/agendador quando disponível.

    Transições (apenas em uma direção, nunca desfaz "paga"/"atrasada"):
    - OPEN   -> CLOSED  quando ``closing_date`` já passou (hoje > fechamento);
    - OPEN/CLOSED -> OVERDUE quando ``due_date`` já passou (hoje > vencimento)
      e a fatura segue não paga;
    - PAID nunca é alterado (pagamento já liquidou a obrigação).

    Idempotência: executar a mesma data várias vezes não altera nada depois da
    primeira passada (as condições só voltam a ser verdadeiras para faturas
    cujo status ainda não foi avançado).

    Retorna ``{"closed": n, "overdue": n}`` com o total de transições, útil
    para testes determinísticos e observabilidade.
    """
    today = today or timezone.localdate()

    closing_qs = CreditCardInvoice.objects.filter(
        status=CreditCardInvoice.Status.OPEN,
        closing_date__lt=today,
        due_date__gte=today,
    )
    overdue_qs = CreditCardInvoice.objects.filter(
        status__in=[CreditCardInvoice.Status.OPEN, CreditCardInvoice.Status.CLOSED],
        due_date__lt=today,
    )

    closed = closing_qs.update(status=CreditCardInvoice.Status.CLOSED)
    overdue = overdue_qs.update(status=CreditCardInvoice.Status.OVERDUE)

    return {"closed": closed, "overdue": overdue}
