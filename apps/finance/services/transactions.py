"""Serviços de lançamento financeiro (receita e despesa)."""

from django.db import transaction as db_transaction

from ..models import Account, Category, Merchant, Transaction, Transfer
from .base import ensure_owned_integer_amount, require_owned
from .errors import InvalidStateError


def record_income(
    *,
    user,
    account,
    amount,
    date,
    description="",
    category=None,
    source=Transaction.Source.MANUAL,
    notes="",
    external_id="",
    merchant=None,
    normalized_description="",
):
    """Registra uma receita (entrada de dinheiro) em uma conta do usuário.

    - Valida ownership da conta e (opcionalmente) da categoria.
    - Valida o valor (inteiro > 0, em centavos).
    - Cria um único Transaction do tipo INCOME pertencente ao usuário.

    ``external_id`` é um identificador de origem (ex.: importação) usado para
    conciliação/dedup futura. Por padrão vazio — não altera o comportamento
    do fluxo manual.

    ``merchant``/``normalized_description`` são enriquecimento aditivo (FASE 4);
    por padrão vazio, sem efeito no fluxo manual.
    """
    amount = ensure_owned_integer_amount(amount)
    if not account or account.owner_id != user.id:
        require_owned(
            Account.objects, user, model_label="Conta", object_id=getattr(account, "pk", None)
        )
    category = _resolve_category_owned(user, category)
    merchant = _resolve_merchant_visible(user, merchant)

    transaction = Transaction.objects.create(
        owner=user,
        type=Transaction.Type.INCOME,
        amount=amount,
        date=date,
        description=description,
        account=account,
        category=category,
        merchant=merchant,
        normalized_description=normalized_description or "",
        source=source,
        notes=notes,
        external_id=external_id or "",
    )
    return transaction


def record_expense(
    *,
    user,
    account,
    amount,
    date,
    description="",
    category=None,
    source=Transaction.Source.MANUAL,
    notes="",
    external_id="",
    merchant=None,
    normalized_description="",
):
    """Registra uma despesa (saída de dinheiro) em uma conta do usuário.

    Compras no cartão NÃO passam por aqui — elas são obrigações representadas
    pela camada de cartão (apps.cards.services), e a saída da conta só ocorre
    no pagamento da fatura.

    ``external_id`` identifica a origem (ex.: importação); por padrão vazio.
    ``merchant``/``normalized_description`` são enriquecimento aditivo (FASE 4).
    """
    amount = ensure_owned_integer_amount(amount)
    if not account or account.owner_id != user.id:
        require_owned(
            Account.objects, user, model_label="Conta", object_id=getattr(account, "pk", None)
        )
    category = _resolve_category_owned(user, category)
    merchant = _resolve_merchant_visible(user, merchant)

    transaction = Transaction.objects.create(
        owner=user,
        type=Transaction.Type.EXPENSE,
        amount=amount,
        date=date,
        description=description,
        account=account,
        category=category,
        merchant=merchant,
        normalized_description=normalized_description or "",
        source=source,
        notes=notes,
        external_id=external_id or "",
    )
    return transaction


def _resolve_merchant_visible(user, merchant):
    """Valida que o Merchant é visível ao usuário (global ou pessoal seu)."""
    if merchant is None:
        return None
    if merchant.owner_id is not None and merchant.owner_id != user.id:
        require_owned(
            Merchant.objects, user, model_label="Estabelecimento", object_id=merchant.pk
        )
    return merchant


def _resolve_category_owned(user, category):
    """Retorna a categoria validada (ownership) ou None."""
    if category is None:
        return None
    if category.owner_id != user.id:
        require_owned(
            Category.objects, user, model_label="Categoria", object_id=category.pk
        )
    return category


def _assert_editable(transaction):
    """Permite edição/exclusão de qualquer lançamento do usuário.

    O usuário tem controle total: receitas, despesas, ajustes, transferências,
    pagamentos de fatura e lançamentos vinculados a compras no cartão podem ser
    alterados ou excluídos (com os devidos efeitos colaterais, como estorno de
    fatura e remoção da dupla perna de transferência).
    """


def update_transaction(
    *,
    user,
    transaction,
    amount=None,
    date=None,
    description=None,
    category=None,
    notes=None,
    account=None,
):
    """Atualiza um lançamento do usuário (qualquer tipo).

    Regras:
    - ownership da transação, conta e categoria é validado;
    - o TIPO não é editável (evita reclassificação indevida de receita/despesa);
    - transferências: atualiza as DUAS pernas + registro Transfer em conjunto
      (a conta individual de cada perna é mantida; valor/data/descrição/notas
      sincronizam a dupla);
    - pagamento de fatura / compra no cartão: alterações seguem como um
      lançamento simples (o estorno é feito pelo fluxo de fatura).
    """
    require_owned(
        Transaction.objects, user, model_label="Transação",
        object_id=getattr(transaction, "pk", None),
    )
    _assert_editable(transaction)

    if transaction.transfer_id is not None:
        return _update_transfer_leg(
            user=user,
            transaction=transaction,
            amount=amount,
            date=date,
            description=description,
            category=category,
            notes=notes,
            account=account,
        )

    if amount is not None:
        amount = ensure_owned_integer_amount(amount)
        transaction.amount = amount
    if date is not None:
        transaction.date = date
    if description is not None:
        transaction.description = (description or "").strip()
    if notes is not None:
        transaction.notes = (notes or "").strip()
    if account is not None:
        if account.owner_id != user.id:
            require_owned(
                Account.objects, user, model_label="Conta",
                object_id=getattr(account, "pk", None),
            )
        transaction.account = account
    if category is not None:
        transaction.category = _resolve_category_owned(user, category)
    transaction.save()
    return transaction


def _update_transfer_leg(
    *,
    user,
    transaction,
    amount=None,
    date=None,
    description=None,
    category=None,
    notes=None,
    account=None,
):
    """Atualiza uma transferência a partir de uma de suas pernas.

    A perna recebida é a referência: os campos de valor/data/descrição/notas
    são aplicados nas DUAS pernas e no registro Transfer, mantendo o par
    sincronizado. A conta de cada perna é preservada (a transferência conecta
    origem->destino; trocar a "conta" de uma perna isolada quebraria o par).
    """
    transfer = Transfer.objects.for_user(user).filter(out_transaction=transaction).first()
    if transfer is None:
        transfer = Transfer.objects.for_user(user).filter(in_transaction=transaction).first()
    if transfer is None and transaction.transfer_id:
        transfer = Transfer.objects.for_user(user).filter(pk=transaction.transfer_id).first()
    if transfer is None:
        raise InvalidStateError("Transação de transferência sem vínculo válido.")

    if category not in (None, ""):
        raise InvalidStateError(
            "Transferências não possuem categoria: remova a categoria e salve novamente."
        )

    out_leg = transfer.out_transaction
    in_leg = transfer.in_transaction

    with db_transaction.atomic():
        if amount is not None:
            amount = ensure_owned_integer_amount(amount)
            transfer.amount = amount
            if out_leg:
                out_leg.amount = amount
            if in_leg:
                in_leg.amount = amount
        if date is not None:
            transfer.date = date
            if out_leg:
                out_leg.date = date
            if in_leg:
                in_leg.date = date
        if description is not None:
            desc = (description or "").strip()
            if out_leg:
                out_leg.description = desc
            if in_leg:
                in_leg.description = desc
        if notes is not None:
            notes_val = (notes or "").strip()
            transfer.notes = notes_val
            if out_leg:
                out_leg.notes = notes_val
            if in_leg:
                in_leg.notes = notes_val
        if account is not None:
            if account.pk != transaction.account_id:
                raise InvalidStateError(
                    "A conta de uma transferência é definida no momento da "
                    "criação (origem e destino). Para mudá-la, exclua e refaça "
                    "a transferência."
                )
        transfer.save()
        if out_leg:
            out_leg.save()
        if in_leg:
            in_leg.save()

    return transaction


def delete_transaction(*, user, transaction):
    """Exclui um lançamento do usuário (qualquer tipo).

    - Transferências: exclui as DUAS pernas + registro Transfer (atômico).
    - Pagamento de fatura: estorna o pagamento (fatura volta a aberta e as
      parcelas voltam a pendentes) e exclui o lançamento.
    - Demais lançamentos (receita, despesa, ajuste, compra de cartão): exclui
      diretamente, preservando o histórico (o vínculo com a compra, quando
      houver, é desfeito via SET_NULL).
    """
    require_owned(
        Transaction.objects, user, model_label="Transação",
        object_id=getattr(transaction, "pk", None),
    )
    _assert_editable(transaction)

    if transaction.transfer_id is not None:
        return _delete_transfer(user=user, transaction=transaction)

    if _has_paid_invoices(transaction):
        return _delete_invoice_payment(user=user, transaction=transaction)

    transaction.delete()
    return None


def _has_paid_invoices(transaction):
    try:
        return transaction.paid_invoices.exists()
    except Exception:
        return False


def _delete_transfer(*, user, transaction):
    """Exclui uma transferência inteira (duas pernas + registro Transfer)."""
    with db_transaction.atomic():
        transfer = transaction.transfer
        if transfer is None:
            transfer = (
                Transfer.objects.for_user(user)
                .filter(out_transaction=transaction)
                .first()
                or Transfer.objects.for_user(user)
                .filter(in_transaction=transaction)
                .first()
            )
        legs = set()
        if transfer:
            if transfer.out_transaction_id:
                legs.add(transfer.out_transaction_id)
            if transfer.in_transaction_id:
                legs.add(transfer.in_transaction_id)
            credits = Transaction.objects.filter(
                owner=user, transfer=transfer
            ).exclude(pk__in=legs)
            for _credit in credits:
                legs.add(_credit.pk)
            transfer.delete()
        for pk in legs:
            Transaction.objects.filter(owner=user, pk=pk).delete()
        transaction.delete()
    return None


def _delete_invoice_payment(*, user, transaction):
    """Apaga o lançamento de pagamento de fatura estornando o pagamento."""
    from apps.cards.services.invoices import reverse_invoice_payment

    with db_transaction.atomic():
        for invoice in list(transaction.paid_invoices.all()):
            reverse_invoice_payment(user=user, invoice=invoice)
        if transaction.pk is not None:
            transaction.delete()
    return None
