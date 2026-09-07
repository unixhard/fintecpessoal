"""Serviços de leitura de saldos (derivados das movimentações).

Não há saldo mutável redundante: o saldo de uma conta é sempre derivado de
``initial_balance`` + efeito das transações (decisão já existente no domínio).

Todos os cáculos são feitos por agregação SQL em uma única query, evitando o
carregamento de todas as transações em Python (N+1 / cópia de objetos).
"""

from django.db.models import Case, IntegerField, Sum, Value, When, F

from ..models import Account, Transaction


def _balance_qs(user, *, account=None, accounts=None):
    """QuerySet de transações com o efeito no saldo anotado por linha."""
    qs = Transaction.objects.filter(owner=user)
    if account is not None:
        qs = qs.filter(account_id=account.pk if hasattr(account, "pk") else account)
    if accounts is not None:
        qs = qs.filter(account_id__in=accounts)
    return qs


def _net_effect_qs(user, *, account=None, accounts=None):
    """Agrega o efeito líquido de todas as transações do escopo em uma query."""
    return _balance_qs(user, account=account, accounts=accounts).aggregate(
        total=Sum(
            Case(
                When(type=Transaction.Type.INCOME, then=F("amount")),
                When(
                    type=Transaction.Type.TRANSFER,
                    transfer_out__isnull=False,
                    then=-F("amount"),
                ),
                When(
                    type=Transaction.Type.TRANSFER,
                    transfer_in__isnull=False,
                    then=F("amount"),
                ),
                # EXPENSE / ADJUSTMENT
                default=-F("amount"),
                output_field=IntegerField(),
            )
        )
    )


def account_balance(account) -> int:
    """Saldo atual de uma conta (centavos), derivado das movimentações.

    - INCOME ............ + valor
    - TRANSFER origem .... - valor  (conta "de onde saiu")
    - TRANSFER destino ... + valor  (conta "para onde entrou")
    - EXPENSE/ADJUSTMENT . - valor

    A transferência interna soma zero no patrimônio total (uma - e uma +).
    """
    total = account.initial_balance
    agg = _net_effect_qs(account.owner, account=account)
    return total + (agg["total"] or 0)


def net_worth(user, *, as_of=None) -> int:
    """Patrimônio total do usuário = soma dos saldos de todas as suas contas."""
    accounts = list(Account.objects.for_user(user))
    total = sum(a.initial_balance for a in accounts)
    if accounts:
        agg = _net_effect_qs(user, accounts=[a.pk for a in accounts])
        total += agg["total"] or 0
    return total


def total_balance(user) -> int:
    """Alias de ``net_worth``: soma dos saldos das contas do usuário."""
    return net_worth(user)