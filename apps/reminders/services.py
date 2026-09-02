"""Serviços de leitura do app reminders (agenda de vencimentos).

Reusa a camada de leitura do dashboard (upcoming_events = faturas + recorrências)
e do app debts (dívidas ativas), consolidando a agenda do período.
"""

from datetime import timedelta

from django.utils.timezone import localdate as tz_localdate

from apps.dashboard import queries
from apps.debts.services import reads as debts_reads

HORIZON_CHOICES = (7, 15, 30, 60)


def timeline(user, *, days=30, ref_date=None):
    """Itens da agenda nos próximos ``days`` dias, com marcação de urgência.

    Retorna lista de dicts: {date, label, kind, source, amount, day_diff, urgency}
    ordenada por data. ``urgency``: overdue | today | soon | upcoming.
    """
    ref_date = ref_date or tz_localdate()
    items = []

    for ev in queries.upcoming_events(user, days=days):
        items.append(
            {
                "date": ev.date,
                "label": ev.label,
                "kind": ev.kind,
                "source": ev.source,
                "amount": ev.amount,
            }
        )

    for debt in debts_reads.active_debts(user):
        if debt.end_date:
            items.append(
                {
                    "date": debt.end_date,
                    "label": f"Dívida — {debt.name}",
                    "kind": "debt",
                    "source": debt.name,
                    "amount": debt.remaining_amount,
                }
            )

    today = ref_date
    horizon = ref_date + timedelta(days=days)
    out = []
    for it in items:
        d = it["date"]
        if d < today - timedelta(days=365):
            continue
        day_diff = (d - today).days
        if day_diff < 0:
            urgency = "overdue"
        elif day_diff == 0:
            urgency = "today"
        elif day_diff <= 3:
            urgency = "soon"
        else:
            urgency = "upcoming"
        if day_diff < -30 or day_diff > days:
            continue
        out.append({**it, "day_diff": day_diff, "urgency": urgency})

    out.sort(key=lambda x: (x["day_diff"],))
    return {
        "items": out,
        "horizon": horizon,
        "overdue_count": sum(1 for x in out if x["urgency"] == "overdue"),
        "today_count": sum(1 for x in out if x["urgency"] == "today"),
        "total_amount": sum(x["amount"] for x in out if x["day_diff"] >= 0),
    }
