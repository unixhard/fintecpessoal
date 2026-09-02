"""Serviço de transferência entre contas do mesmo usuário (atômico)."""

from django.db import transaction as db_transaction

from ..models import Account, Transaction, Transfer
from .base import ensure_owned_integer_amount, require_owned
from .errors import InvalidAmountError


def transfer_between(
    *,
    user,
    from_account,
    to_account,
    amount,
    date,
    notes="",
    source=Transaction.Source.MANUAL,
):
    """Move dinheiro entre duas contas do mesmo usuário.

    Gera as DUAS pernas de transferência (out/in) de modo que o patrimônio
    total permaneça invariável — NÃO é receita + despesa.

    Atomicidade: toda a operação roda dentro de ``transaction.atomic()``; se
    qualquer passo falhar (inclusive a criação da segunda perna), tudo é
    revertido (rollback real).

    Regras:
    - usuário é dono da origem e do destino;
    - origem != destino;
    - valor > 0 (inteiro em centavos).
    """
    amount = ensure_owned_integer_amount(amount)

    if not from_account or from_account.owner_id != user.id:
        require_owned(
            Account.objects, user,
            model_label="Conta de origem", object_id=getattr(from_account, "pk", None),
        )
    if not to_account or to_account.owner_id != user.id:
        require_owned(
            Account.objects, user,
            model_label="Conta de destino", object_id=getattr(to_account, "pk", None),
        )
    if from_account.pk == to_account.pk:
        raise InvalidAmountError("Origem e destino devem ser contas distintas.")

    with db_transaction.atomic():
        out_leg = Transaction.objects.create(
            owner=user,
            type=Transaction.Type.TRANSFER,
            amount=amount,
            date=date,
            description="Transferência",
            account=from_account,
            source=source,
            notes=notes,
        )
        in_leg = Transaction.objects.create(
            owner=user,
            type=Transaction.Type.TRANSFER,
            amount=amount,
            date=date,
            description="Transferência",
            account=to_account,
            source=source,
            notes=notes,
        )
        transfer = Transfer.objects.create(
            owner=user,
            from_account=from_account,
            to_account=to_account,
            amount=amount,
            date=date,
            out_transaction=out_leg,
            in_transaction=in_leg,
            notes=notes,
        )
        out_leg.transfer = transfer
        in_leg.transfer = transfer
        out_leg.save()
        in_leg.save()

    return transfer
