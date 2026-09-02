"""Serviços do app networth (patrimônio consolidado).

Agrega apenas dados que já existem no domínio, sem duplicar regras:
- Ativos ..... somatório dos saldos das contas (finance.balances).
- Passivos ... dívidas restantes (debts) + parcelas de cartão comprometidas (cards).
- Reservas ... valor reservado em metas (goals) — exibido separadamente.
"""

from datetime import timedelta

from django.utils.timezone import localdate as tz_localdate

from apps.cards.models import CreditCard, Installment
from apps.cards.services.reads import card_usage
from apps.debts.services.reads import total_remaining
from apps.finance.services import balances
from apps.goals.services.goals import get_goal_summary

from .models import NetWorthSnapshot


def card_liabilities(user) -> int:
    """Somatório do comprometido (parcelas pendentes/vencidas) em todos os cartões."""
    total = 0
    for card in CreditCard.objects.for_user(user):
        total += card_usage(card)["used"]
    return total


def debts_liabilities(user) -> int:
    return total_remaining(user)


def compose(user, *, ref_date=None):
    """Composição atual do patrimônio do usuário (valores em centavos)."""
    ref_date = ref_date or tz_localdate()
    # Ativos: saldo das contas
    assets = balances.net_worth(user)
    # Reservas em metas (informacional — aspiração, não necessariamente no banco)
    goal_summary = get_goal_summary(user=user, ref_date=ref_date)
    reserves = goal_summary["total_current"]
    # Passivos
    liabilities = debts_liabilities(user) + card_liabilities(user)
    net = assets - liabilities
    return {
        "assets": assets,
        "liabilities": liabilities,
        "reserves": reserves,
        "net_worth": net,
    }


def register_snapshot(user, *, assets=None, liabilities=None, ref_date=None):
    """Registra/congela um ponto de patrimônio para a data (um por dia, idempotente)."""
    ref_date = ref_date or tz_localdate()
    assets = (
        assets
        if assets is not None
        else balances.net_worth(user)
    )
    liabilities = (
        liabilities
        if liabilities is not None
        else debts_liabilities(user) + card_liabilities(user)
    )
    net = assets - liabilities
    obj, _ = NetWorthSnapshot.objects.update_or_create(
        owner=user,
        recorded_on=ref_date,
        defaults={
            "assets": assets,
            "liabilities": liabilities,
            "net_worth": net,
        },
    )
    return obj


def get_history(user, *, limit=90, ref_date=None):
    """Série cronológica (ascendente) dos pontos registrados para o gráfico."""
    ref_date = ref_date or tz_localdate()
    start = ref_date - timedelta(days=limit)
    qs = (
        NetWorthSnapshot.objects.for_user(user)
        .filter(recorded_on__gte=start)
        .order_by("recorded_on")
    )
    return [
        {
            "date": s.recorded_on,
            "assets": s.assets,
            "liabilities": s.liabilities,
            "net_worth": s.net_worth,
        }
        for s in qs
    ]


def latest_snapshot(user):
    obj = NetWorthSnapshot.objects.for_user(user).first()
    if obj is None:
        return None
    return {
        "recorded_on": obj.recorded_on,
        "assets": obj.assets,
        "liabilities": obj.liabilities,
        "net_worth": obj.net_worth,
    }
