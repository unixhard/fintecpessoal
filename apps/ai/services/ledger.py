"""Ledger de orçamento diário por usuário (defesa do free tier).

Conta chamadas de IA por feature e por usuário/dia usando o framework de cache
(Django cache) — sem escrita no banco no caminho quente. O ledger É o limite
que mantém o app de pé: quando o orçamento diário de uma feature acaba, o fluxo
cai para o fallback determinístico (que não consome token) e o usuário é
avisado de forma transparente.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from django.core.cache import cache
from django.utils import timezone

FEATURES = {
    "presence": "presença",
    "consult": "consultoria",
    "report": "relatório",
}


def _day_key(user_id: int, feature: str) -> str:
    today = timezone.localdate().isoformat()
    return f"ai:ledger:{today}:{feature}:{user_id}"


def remaining(feature: str, user, cap: int) -> int:
    """Quantas chamadas de IA ainda restam hoje para esta feature."""
    if not cap:
        return 0
    used = int(cache.get(_day_key(user.pk, feature), 0) or 0)
    return max(0, cap - used)


def consume(feature: str, user, cap: int, amount: int = 1) -> bool:
    """Registra uma chamada de IA se ainda houver orçamento.

    Retorna True quando o consumo foi autorizado (dentro do limite).
    """
    if cap <= 0:
        return False
    key = _day_key(user.pk, feature)
    used = int(cache.get(key, 0) or 0)
    if used >= cap:
        return False
    # Expira o contador no começo do próximo dia (fuso local).
    now = timezone.localtime()
    end_of_day = datetime.combine(
        now.date() + timedelta(days=1),
        datetime.min.time(),
        tzinfo=now.tzinfo,
    )
    ttl = int((end_of_day - now).total_seconds())
    cache.set(key, used + amount, timeout=ttl)
    return True


def count(feature: str, user) -> int:
    """Chamadas registradas hoje para a feature."""
    return int(cache.get(_day_key(user.pk, feature), 0) or 0)


def feature_label(feature: str) -> str:
    return FEATURES.get(feature, feature)