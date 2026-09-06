"""Serviços de lançamento financeiro (receita e despesa)."""

from ..models import Account, Category, Merchant, Transaction
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
    """Lançamentos com vínculos estruturais não podem ser editados/excluídos.

    - transferência: tem duas pernas (origem/destino) — editar uma perna sozinha
      dessincronizaria o par;
    - pagamento de fatura / compra no cartão: pertence à obrigação do cartão;
    - o tipo do lançamento é imutável (não se transforma receita em despesa).
    """
    if transaction.transfer_id:
        raise InvalidStateError(
            "Lançamentos de transferência devem ser editados/excluídos pela "
            "transferência e não individualmente."
        )
    if transaction.card_purchase_id:
        raise InvalidStateError(
            "Lançamento vinculado a compra no cartão não pode ser editado aqui."
        )
    if hasattr(transaction, "paid_invoices") and transaction.paid_invoices.exists():
        raise InvalidStateError(
            "Lançamento de pagamento de fatura não pode ser editado aqui."
        )


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
    """Atualiza um lançamento simples (receita/despesa/ajuste) do usuário.

    Restrições (regras financeiras existentes, nunca violadas):
    - só lançamentos manuais sem vínculo estrutural (transferência, compra de
      cartão ou pagamento de fatura) são editáveis;
    - ownership da transação, conta e categoria é validado;
    - o TIPO não é editável (evita reclassificação indevida de receita/despesa).
    """
    require_owned(
        Transaction.objects, user, model_label="Transação",
        object_id=getattr(transaction, "pk", None),
    )
    _assert_editable(transaction)

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


def delete_transaction(*, user, transaction):
    """Exclui um lançamento simples do usuário (se seguro fazê-lo).

    Rejeita lançamentos com vínculo estrutural (transferência, compra de cartão,
    pagamento de fatura). Ocorrências geradas por recorrência podem ser
    excluídas (a regra em si permanece intocada).
    """
    require_owned(
        Transaction.objects, user, model_label="Transação",
        object_id=getattr(transaction, "pk", None),
    )
    _assert_editable(transaction)
    if transaction.type not in (
        Transaction.Type.INCOME,
        Transaction.Type.EXPENSE,
        Transaction.Type.ADJUSTMENT,
    ):
        raise InvalidStateError("Este tipo de lançamento não pode ser excluído.")
    transaction.delete()
    return None
