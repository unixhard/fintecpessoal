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
from apps.finance.services.errors import InvalidAmountError, InvalidStateError

from ..models import CreditCard, Installment, InstallmentPurchase
from .invoices import get_or_create_invoice
from .reads import card_usage


def _assert_limit_available(*, card, amount_to_commit):
    """Valida que ``amount_to_commit`` cabe no limite disponível do cartão.

    Regra bancária: uma nova compra compromete o limite TOTAL (à vista ou
    parcelada) imediatamente no ato — ``available >= total``. O cartão é
    bloqueado com ``select_for_update`` para evitar corrida entre compras
    simultâneas.

    Se o cartão não tiver limite configurado (``limit == 0`` — campo opcional
    no cadastro), nenhuma margem é validada e o cartão segue operando.
    """
    locked = CreditCard.objects.select_for_update().get(pk=card.pk)
    if locked.limit <= 0:
        return locked
    usage = card_usage(locked)
    available = locked.limit - usage["used"]
    if amount_to_commit > available:
        raise InvalidStateError(
            "Limite insuficiente no cartão. Disponível: "
            f"{max(available, 0)} centavos para {amount_to_commit} centavos."
        )
    return locked


def update_purchase(
    *,
    user,
    purchase,
    description=None,
    total_amount=None,
    installment_count=None,
    first_due_date=None,
):
    """Atualiza uma compra no cartão (ownership validado).

    - ``description`` pode sempre ser editada;
    - ``total_amount``/``installment_count``/``first_due_date`` só podem ser
      alterados enquanto NENHUMA parcela estiver paga (se alguma parcela já foi
      paga, a compra não pode ser redistribuída; o usuário deve estornar o
      pagamento da fatura e refazer).

    Quando os valores mudam, as parcelas existentes são recriadas (a última
    absorve o resíduo de arredondamento, garantindo soma exata).
    """
    require_owned(
        InstallmentPurchase.objects, user, model_label="Compra",
        object_id=getattr(purchase, "pk", None),
    )

    if description is not None:
        description = (description or "").strip()
        if not description:
            raise ValueError("Descrição é obrigatória.")
        purchase.description = description

    if first_due_date is not None:
        purchase.first_due_date = first_due_date

    # Identifica mudança estrutural (valor/parcelas/data inicial).
    base = purchase.installment_amount
    structural = False
    if total_amount is not None and total_amount != purchase.total_amount:
        total_amount = ensure_owned_integer_amount(total_amount, field="valor total")
        structural = True
    if installment_count is not None and installment_count != purchase.installment_count:
        if isinstance(installment_count, bool) or not isinstance(installment_count, int):
            raise InvalidAmountError("Quantidade de parcelas inválida.")
        if installment_count < 1:
            raise InvalidAmountError("Quantidade de parcelas deve ser >= 1.")
        structural = True
    if first_due_date is not None and first_due_date != purchase.first_due_date:
        structural = True

    if structural:
        from django.db import transaction as db_transaction
        from django.db.models import Sum

        if purchase.installments.filter(status=Installment.Status.PAID).exists():
            raise InvalidStateError(
                "Esta compra possui parcelas pagas. Estorne o pagamento da fatura "
                "antes de alterar valor, parcelas ou a primeira data."
            )

        new_total = total_amount if total_amount is not None else purchase.total_amount
        new_count = (
            installment_count
            if installment_count is not None
            else purchase.installment_count
        )
        purchase.total_amount = new_total
        purchase.installment_count = new_count
        purchase.installment_amount = new_total // new_count

        with db_transaction.atomic():
            # Revalida o limite: as parcelas atuais serão removidas e o novo
            # total entrará no lugar — a folga é ``limit - uso_demais_compras``.
            this_pending = (
                purchase.installments.filter(
                    status__in=[
                        Installment.Status.PENDING,
                        Installment.Status.OVERDUE,
                    ]
                ).aggregate(total=Sum("amount"))["total"]
                or 0
            )
            usage_other = card_usage(purchase.card)["used"] - this_pending
            available = purchase.card.limit - usage_other
            if purchase.card.limit > 0 and new_total > available:
                raise InvalidStateError(
                    "Limite insuficiente no cartão para o novo valor da compra. "
                    f"Disponível: {max(available, 0)} centavos."
                )
            purchase.save()

            # Recria as parcelas (limitado à compra; faturas antigas ficam sem
            # parcelas e passam a zerar o valor — normalmente serão apagadas).
            purchase.installments.all().delete()
            installments = list(purchase.generate_installments())
            for installment in installments:
                invoice = get_or_create_invoice(user, purchase.card, installment.due_date)
                installment.invoice = invoice
                installment.save()
    else:
        purchase.save()

    return purchase


def delete_purchase(*, user, purchase):
    """Exclui uma compra no cartão e todas as suas parcelas.

    Se alguma parcela pertencia a uma fatura paga, as parcelas removidas
    reduzem o valor daquela fatura (o pagamento já feito permanece registrado,
    pois a saída da conta foi real) — o usuário pode estornar o pagamento da
    fatura separadamente, se desejar.
    """
    require_owned(
        InstallmentPurchase.objects, user, model_label="Compra",
        object_id=getattr(purchase, "pk", None),
    )
    purchase.delete()
    return purchase


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
    - limite disponível suficiente (validação estrita da margem — a compra
      compromete o limite TOTAL no ato, à vista ou parcelada);
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
        locked_card = _assert_limit_available(card=card, amount_to_commit=total_amount)
        purchase = InstallmentPurchase.objects.create(
            owner=user,
            card=locked_card,
            description=description,
            total_amount=total_amount,
            installment_count=installment_count,
            installment_amount=base_installment,
            first_due_date=first_due_date,
            status=status,
        )
        installments = list(purchase.generate_installments())
        for installment in installments:
            invoice = get_or_create_invoice(user, locked_card, installment.due_date)
            installment.invoice = invoice
            installment.save()

    return purchase
