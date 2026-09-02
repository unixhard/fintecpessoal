"""Serviço de compra no cartão (à vista / parcelada).

Usa a lógica de domínio já existente em ``InstallmentPurchase.generate_installments()``
para o parcelamento e arredondamento (soma exata na última parcela), orquestrando
a criação da compra, das parcelas e da associação às faturas.
"""

from datetime import date

from django.db import transaction as db_transaction

from apps.finance.services.base import (
    ensure_owned_integer_amount,
    require_owned,
)
from apps.finance.services.errors import InvalidAmountError

from ..models import CreditCard, InstallmentPurchase
from .invoices import get_or_create_invoice


def create_card_purchase(
    *,
    user,
    card,
    description,
    total_amount,
    installment_count,
    first_due_date,
    status=InstallmentPurchase.Status.ONGOING,
):
    """Cria uma compra no cartão.

    - ``installment_count == 1``  -> compra à vista (uma única parcela).
    - ``installment_count > 1``   -> compra parcelada.

    Garantias:
    - ownership do cartão;
    - valores inteiros em centavos > 0;
    - atomicidade;
    - NÃO debita a conta bancária (a saída só ocorre no pagamento da fatura).
    """
    total_amount = ensure_owned_integer_amount(total_amount, field="valor total")
    if isinstance(installment_count, bool) or not isinstance(installment_count, int):
        raise InvalidAmountError("Quantidade de parcelas inválida.")
    if installment_count < 1:
        raise InvalidAmountError("Quantidade de parcelas deve ser >= 1.")

    if not card or card.owner_id != user.id:
        require_owned(
            CreditCard.objects, user, model_label="Cartão", object_id=getattr(card, "pk", None)
        )

    # Parcela-base (piso). O resíduo do arredondamento é absorvido pela última
    # parcela em generate_installments(), garantindo soma exata.
    base_installment = total_amount // installment_count

    with db_transaction.atomic():
        purchase = InstallmentPurchase.objects.create(
            owner=user,
            card=card,
            description=description,
            total_amount=total_amount,
            installment_count=installment_count,
            installment_amount=base_installment,
            first_due_date=first_due_date,
            status=status,
        )
        installments = list(purchase.generate_installments())
        for installment in installments:
            invoice = get_or_create_invoice(user, card, installment.due_date)
            installment.invoice = invoice
            installment.save()

    return purchase
