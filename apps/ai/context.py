"""Context processor: é o "sino inteligente".

É barato por construção: nunca gera chamada de IA — apenas lê a presença já
cacheada do dia. Se a presença ainda não foi gerada (ex.: usuário ainda não
abriu o painel), retorna vazio e o sino não mostra nada extra.
"""

from __future__ import annotations

from django.core.cache import cache
from django.utils import timezone


def cfo_notifications(request):
    if not getattr(request, "user", None) or not request.user.is_authenticated:
        return {}
    if not getattr(request.user, "profile", None):
        return {}
    if not request.user.profile.onboarding_completed:
        return {}
    key = f"ai:presence:{request.user.pk}:{timezone.localdate().isoformat()}"
    presence = cache.get(key)
    if not presence:
        return {}
    alerta = (presence.get("alerta") or "").strip()
    if not alerta:
        return {}
    return {"cfo_alert": alerta[:200]}