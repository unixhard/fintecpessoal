"""Serviço de edição de cartão de crédito (CreditCard).

Coordenado aqui para manter ownership e validação fora das views (regra 16).
Valores derivados (limite utilizado etc.) nunca são armazenados — são calculados
por ``apps.cards.services.reads``.
"""

from apps.finance.services.base import require_owned
from apps.finance.services.errors import InvalidAmountError, InvalidStateError

from ..models import CreditCard

_UNSET = object()


def update_card(
    *,
    user,
    card,
    name=None,
    institution=None,
    limit=None,
    closing_day=None,
    due_day=None,
    payment_account=_UNSET,
    status=None,
):
    """Atualiza campos editáveis de um cartão (ownership validado).

    - ``limit`` é inteiro em centavos >= 0.
    - ``closing_day``/``due_day`` entre 1 e 31.
    - ``payment_account``: instância de conta do usuário, ou ``None`` para
      desvincular a conta de pagamento.
    """
    require_owned(
        CreditCard.objects, user, model_label="Cartão",
        object_id=getattr(card, "pk", None),
    )
    if name is not None:
        name = (name or "").strip()
        if not name:
            raise ValueError("nome do cartão é obrigatório.")
        card.name = name
    if institution is not None:
        card.institution = institution or ""
    if limit is not None:
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 0:
            raise InvalidAmountError("Limite deve ser um inteiro em centavos >= 0.")
        card.limit = limit
    if closing_day is not None:
        card.closing_day = _validate_day(closing_day, "dia de fechamento")
    if due_day is not None:
        card.due_day = _validate_day(due_day, "dia de vencimento")
    if payment_account is not _UNSET:
        if payment_account is not None:
            from apps.finance.models import Account

            require_owned(
                Account.objects, user, model_label="Conta",
                object_id=payment_account.pk,
            )
        card.payment_account = payment_account
    if status is not None:
        card.status = status
    card.save()
    return card


def set_card_status(*, user, card, status):
    """Bloqueia, encerra ou reativa um cartão (ownership validado).

    Regras de estado são aplicadas aqui e não na view (isolamento multiusuário
    e validação fora da camada de apresentação).
    """
    require_owned(
        CreditCard.objects, user, model_label="Cartão",
        object_id=getattr(card, "pk", None),
    )
    if status not in (
        CreditCard.Status.ACTIVE,
        CreditCard.Status.BLOCKED,
        CreditCard.Status.CLOSED,
    ):
        raise InvalidStateError("Status inválido para o cartão.")
    card.status = status
    card.save()
    return card


def delete_card(*, user, card):
    """Exclui um cartão do usuário junto com tudo que o referencia.

    - Estorna faturas pagas (apagando a Transaction de pagamento);
    - desvincula a conta de pagamento (PROTECT) das faturas;
    - apaga faturas e compras (as parcelas são apagadas em cascata).

    Retorna a quantidade de lançamentos de pagamento removidos.
    """
    from django.db import transaction as db_transaction
    from django.utils import timezone

    from apps.finance.models import Transaction

    from ..models import CreditCardInvoice, Installment, InstallmentPurchase
    from .invoices import reverse_invoice_payment

    require_owned(
        CreditCard.objects, user, model_label="Cartão",
        object_id=getattr(card, "pk", None),
    )

    from apps.finance.models import RecurringRule

    deleted_payments = 0
    with db_transaction.atomic():
        # Recorrências que usam este cartão (PROTECT): sem o cartão, regras de
        # despesa ficariam sem conta/cartão (regras do model) — são excluídas.
        for rule in list(
            RecurringRule.objects.for_user(user).filter(card=card)
        ):
            rule.delete()
        invoices_paid = list(
            CreditCardInvoice.objects.for_user(user)
            .filter(card=card, status=CreditCardInvoice.Status.PAID)
            .select_related("payment_transaction")
        )
        for invoice in invoices_paid:
            if invoice.payment_transaction_id:
                try:
                    reverse_invoice_payment(user=user, invoice=invoice)
                    deleted_payments += 1
                except Exception:
                    # Se o pagamento já foi removido, garante a limpeza.
                    invoice.payment_transaction = None
                    invoice.payment_account = None
                    invoice.save()
            else:
                invoice.payment_account = None
                invoice.save()

        # Faturas não pagas: desvincula conta de pagamento (PROTECT) e apaga.
        remaining = (
            CreditCardInvoice.objects.for_user(user)
            .filter(card=card)
            .exclude(status=CreditCardInvoice.Status.PAID)
        )
        for invoice in list(remaining):
            if invoice.payment_account_id:
                invoice.payment_account = None
                invoice.save()
        CreditCardInvoice.objects.for_user(user).filter(card=card).delete()

        # Compras (parcelas em cascata).
        InstallmentPurchase.objects.for_user(user).filter(card=card).delete()

        card.delete()

    return deleted_payments


def _validate_day(value, label):
    if isinstance(value, bool) or not isinstance(value, int):
        raise InvalidAmountError(f"{label} inválido.")
    if not (1 <= value <= 31):
        raise InvalidAmountError(f"{label} deve estar entre 1 e 31.")
    return value
