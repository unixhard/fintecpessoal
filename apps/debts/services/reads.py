"""Read layer de dívidas.

Queries de leitura (agregação, isolamento por usuário) usadas por listas,
dashboard e próximos vencimentos. Não duplica regras de escrita.
"""

from django.utils.timezone import localdate as tz_localdate

from ..models import Debt


def active_debts(user):
    """Dívidas ativas/inadimplentes do usuário, ordenadas por nome."""
    return Debt.objects.for_user(user).filter(
        status__in=[Debt.Status.ACTIVE, Debt.Status.DEFAULTED]
    ).order_by("name")


def total_remaining(user) -> int:
    """Saldo restante total das dívidas ativas/inadimplentes."""
    return sum(d.remaining_amount for d in active_debts(user))


def next_payments(user, *, limit=8, ref_date=None):
    """Dívidas ativas ordenadas por vencimento mais próximo."""
    import datetime

    ref_date = ref_date or tz_localdate()
    with_due = [
        d for d in active_debts(user)
        if d.end_date and d.end_date >= ref_date and d.status == Debt.Status.ACTIVE
    ]
    with_due.sort(key=lambda d: d.end_date)
    return with_due[:limit]


def overdue_debts(user, ref_date=None):
    """Dívidas inadimplentes ou com vencimento <= hoje ainda ativas."""
    ref_date = ref_date or tz_localdate()
    return [
        d for d in active_debts(user)
        if d.status == Debt.Status.DEFAULTED
        or (d.status == Debt.Status.ACTIVE and d.end_date and d.end_date < ref_date)
    ]
