"""Serviço de leitura do cartão de crédito.

Base correta (não um sistema de crédito complexo): limite total, valor
utilizado, limite disponível e obrigações (faturas aberta/futuras e valor
parcelado futuro).
"""

from django.db.models import Sum

from ..models import CreditCard, CreditCardInvoice, Installment


def card_usage(card):
    """Resumo de utilização do limite do cartão (valores em centavos).

    ``used`` considera o total comprometido (parcelas pendentes + inseridas em
    faturas) — a obrigação total ainda não liquidada.
    """
    used = 0
    for installment in Installment.objects.filter(
        purchase__card=card,
        status__in=[Installment.Status.PENDING, Installment.Status.OVERDUE],
    ):
        used += installment.amount
    available = max(card.limit - used, 0)
    return {
        "limit": card.limit,
        "used": used,
        "available": available,
    }


def card_summary(user, card):
    """Leituras completas do cartão para o usuário.

    - limite total;
    - valor utilizado;
    - limite disponível;
    - fatura aberta (mais recente não paga);
    - faturas futuras (abertas, não pagas, ordenadas por vencimento);
    - valor parcelado futuro (soma das parcelas pendentes).
    """
    if not card or card.owner_id != user.id:
        from ..models import CreditCard
        from apps.finance.services.base import require_owned

        require_owned(
            CreditCard.objects, user, model_label="Cartão", object_id=getattr(card, "pk", None)
        )

    usage = card_usage(card)

    invoices = list(
        card.invoices.order_by("due_date").filter(
            status__in=[
                CreditCardInvoice.Status.OPEN,
                CreditCardInvoice.Status.OVERDUE,
            ]
        )
    )

    future_installments = (
        Installment.objects.filter(
            purchase__card=card,
            status__in=[Installment.Status.PENDING, Installment.Status.OVERDUE],
        ).aggregate(total=Sum("amount"))["total"]
        or 0
    )

    open_invoice = invoices[0] if invoices else None

    return {
        "limit": usage["limit"],
        "used": usage["used"],
        "available": usage["available"],
        "open_invoice": open_invoice,
        "future_invoices": invoices,
        "future_installment_total": future_installments,
    }
