"""Read layer de metas financeiras.

Queries de leitura (agregação, isolamento por usuário) para listas, dashboard
e próximos passos. Não duplica regras de escrita.
"""

from django.utils.timezone import localdate as tz_localdate

from ..models import Goal


def active_goals(user):
    """Metas ativas do usuário (não arquivadas), ordenadas por prioridade."""
    return Goal.objects.for_user(user).filter(
        status__in=[Goal.Status.ACTIVE, Goal.Status.PAUSED]
    ).order_by("-priority", "target_date", "name")


def goals_near_deadline(user, *, days=60, ref_date=None):
    """Metas ativas com prazo dentro do horizonte (dias) que ainda não atingiram."""
    ref_date = ref_date or tz_localdate()
    from datetime import timedelta

    horizon = ref_date + timedelta(days=days)
    return [
        g for g in active_goals(user)
        if g.target_date and ref_date <= g.target_date <= horizon
        and g.current_amount < g.target_amount
    ]


def overdue_goals(user, ref_date=None):
    """Metas ativas com prazo vencido e ainda não alcançadas."""
    ref_date = ref_date or tz_localdate()
    return [
        g for g in active_goals(user)
        if g.target_date and g.target_date < ref_date
        and g.current_amount < g.target_amount
    ]
