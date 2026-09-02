"""Serviços de leitura de saldos (derivados das movimentações).

Não há saldo mutável redundante: o saldo de uma conta é sempre derivado de
``initial_balance`` + efeito das transações (decisão já existente no domínio).
"""

from ..models import Account, Transaction


def account_balance(account):
    """Saldo atual de uma conta (centavos), derivado das movimentações.

    - INCOME ............ + valor
    - TRANSFER origem .... - valor  (conta "de onde saiu")
    - TRANSFER destino ... + valor  (conta "para onde entrou")
    - EXPENSE/ADJUSTMENT . - valor

    A transferência interna soma zero no patrimônio total (uma - e uma +).
    """
    total = account.initial_balance
    for tx in account.transactions.all():
        if tx.type == Transaction.Type.INCOME:
            total += tx.amount
        elif tx.type == Transaction.Type.TRANSFER:
            if hasattr(tx, "transfer_out"):
                total -= tx.amount
            elif hasattr(tx, "transfer_in"):
                total += tx.amount
        else:  # EXPENSE / ADJUSTMENT
            total -= tx.amount
    return total


def net_worth(user, *, as_of=None):
    """Patrimônio total do usuário = soma dos saldos de todas as suas contas."""
    total = 0
    for account in Account.objects.for_user(user):
        total += account_balance(account)
    return total


def total_balance(user):
    """Alias de ``net_worth``: soma dos saldos das contas do usuário."""
    return net_worth(user)
