"""Serviço de criação de conta financeira (Account).

Decisão documentada (Ordem 6, onboarding): não existia service específico para
criar `Account` na camada de serviços. Para não duplicar regra financeira em
view, cria-se esta operação mínima e coerente com o restante da camada — recebe
`user` e parâmetros explícitos, valida posse/valores e retorna a `Account`
criada (com `owner` derivado do usuário autenticado, nunca de input do cliente).
"""

from django.utils import timezone

from ..models import Account
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
