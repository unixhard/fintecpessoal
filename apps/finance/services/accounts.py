"""Serviço de criação de conta financeira (Account).

Decisão documentada (Ordem 6, onboarding): não existia service específico para
criar `Account` na camada de serviços. Para não duplicar regra financeira em
view, cria-se esta operação mínima e coerente com o restante da camada — recebe
`user` e parâmetros explícitos, valida posse/valores e retorna a `Account`
criada (com `owner` derivado do usuário autenticado, nunca de input do cliente).
"""

from django.db import transaction as db_transaction
from django.utils import timezone

from ..models import Account, Transaction, Transfer
from .base import require_owned
from .errors import InvalidAmountError


def _validate_initial_balance(initial_balance):
    """Valor inicial deve ser inteiro em centavos >= 0 (pode ser zero)."""
    if isinstance(initial_balance, bool) or not isinstance(initial_balance, int):
        raise InvalidAmountError("saldo inicial deve ser um inteiro em centavos.")
    if initial_balance < 0:
        raise InvalidAmountError("saldo inicial não pode ser negativo.")
    return initial_balance


def create_account(
    *,
    user,
    name,
    type=Account.Type.CHECKING,
    initial_balance=0,
    currency="BRL",
    institution="",
    initial_balance_date=None,
):
    """Cria uma conta financeira pertencente ao usuário.

    - `name`: obrigatório (validado pelo model); vazio lança erro.
    - `type`: um dos valores de ``Account.Type`` (padrão CHECKING).
    - `initial_balance`: inteiro em centavos >= 0 (padrão 0).
    - A conta nasce com `status=ACTIVE` e `owner=user`.
    """
    name = (name or "").strip()
    if not name:
        raise ValueError("nome da conta é obrigatório.")

    initial_balance = _validate_initial_balance(initial_balance)
    if initial_balance_date is None:
        initial_balance_date = timezone.localdate()

    return Account.objects.create(
        owner=user,
        name=name,
        type=type,
        initial_balance=initial_balance,
        initial_balance_date=initial_balance_date,
        currency=currency or "BRL",
        institution=institution or "",
        status=Account.Status.ACTIVE,
    )


def update_account(*, user, account, name=None, type=None, institution=None):
    """Atualiza campos editáveis de uma conta (ownership validado).

    O saldo de uma conta é SEMPRE derivado de ``initial_balance`` + efeito das
    transações (decisão já existente). Editar ``initial_balance`` após movimentar
    a conta alteraria o saldo de forma enganosa; por isso este fluxo NÃO expõe
    ``initial_balance`` na edição (o usuário deve corrigir via lançamentos).
    """
    require_owned(
        Account.objects, user, model_label="Conta",
        object_id=getattr(account, "pk", None),
    )
    if name is not None:
        name = (name or "").strip()
        if not name:
            raise ValueError("nome da conta é obrigatório.")
        account.name = name
    if type is not None:
        account.type = type
    if institution is not None:
        account.institution = institution or ""
    account.save()
    return account


def archive_account(*, user, account):
    """Arquiva uma conta (status ARCHIVED — não é encerrada).

    A conta arquivada deixa de compor o dinheiro disponível, mas mantém o
    histórico de movimentações (nada é apagado).
    """
    require_owned(
        Account.objects, user, model_label="Conta",
        object_id=getattr(account, "pk", None),
    )
    account.status = Account.Status.ARCHIVED
    account.save()
    return account


def reactivate_account(*, user, account):
    """Reativa uma conta arquivada (status ACTIVE)."""
    require_owned(
        Account.objects, user, model_label="Conta",
        object_id=getattr(account, "pk", None),
    )
    account.status = Account.Status.ACTIVE
    account.save()
    return account


def delete_account(*, user, account):
    """Exclui uma conta do usuário e apaga tudo o que a referencia.

    - Apaga todas as transações vinculadas à conta (usando o serviço de
      lançamento, que já trata transferências inteiras);
    - desfaz pagamentos de fatura que usaram essa conta (payment_account é
      PROTECT na fatura);
    - apaga transferências que usaram a conta como origem ou destino;
    - por fim apaga a própria conta.

    Retorna a quantidade de lançamentos excluídos.
    """
    require_owned(
        Account.objects, user, model_label="Conta",
        object_id=getattr(account, "pk", None),
    )

    from apps.cards.models import CreditCard, CreditCardInvoice

    deleted = 0
    with db_transaction.atomic():
        # 0) Desvincula a conta dos cartões que a usam como conta de pagamento
        #    (CreditCard.payment_account é PROTECT) e das recorrências que a
        #    usam (RecurringRule.account é PROTECT). Recorrências que ficariam
        #    sem conta/cartão (regras do model) são excluídas.
        CreditCard.objects.filter(owner=user, payment_account=account).update(
            payment_account=None
        )
        from apps.finance.models import RecurringRule
        for rule in list(
            RecurringRule.objects.for_user(user).filter(account=account)
        ):
            if rule.card_id and rule.kind == RecurringRule.Kind.EXPENSE:
                rule.account = None
                rule.save()
            else:
                rule.delete()

        # 1) Desfaz pagamentos de fatura liquidados por essa conta, para que o
        #    FK PROTECT de payment_account não bloqueie a exclusão.
        invoices = CreditCardInvoice.objects.filter(
            owner=user, payment_account=account
        )
        for invoice in list(invoices):
            if invoice.status == "paid" and invoice.payment_transaction_id:
                try:
                    from apps.cards.services.invoices import reverse_invoice_payment
                    reverse_invoice_payment(user=user, invoice=invoice)
                    deleted += 1
                except Exception:
                    invoice.payment_account = None
                    invoice.save(update_fields=["payment_account"])
            else:
                invoice.payment_account = None
                invoice.save(update_fields=["payment_account"])

        # 2) Apaga transferências que envolvem a conta (pernas origem/destino),
        #    apagando cada par inteiro.
        related = Transfer.objects.filter(owner=user).filter(
            from_account=account
        ) | Transfer.objects.filter(owner=user).filter(to_account=account)
        for transfer in list(related):
            legs = [
                leg
                for leg in (
                    transfer.out_transaction,
                    transfer.in_transaction,
                )
                if leg is not None
            ]
            # PROTECT: apagar o Transfer antes das pernas (FK SET_NULL nas
            # transações libera a exclusão das mesmas).
            transfer.delete()
            for leg in legs:
                Transaction.objects.filter(owner=user, pk=leg.pk).delete()
                deleted += 1

        # 3) Apaga as demais transações da conta.
        for tx in list(
            Transaction.objects.filter(owner=user, account=account).only("pk")
        ):
            try:
                from .transactions import delete_transaction
                delete_transaction(user=user, transaction=tx)
            except Exception:
                Transaction.objects.filter(owner=user, pk=tx.pk).delete()
            deleted += 1

        # 4) Remove a conta.
        account.delete()

    return deleted
