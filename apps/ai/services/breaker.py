"""Circuit breaker global (em cache) para o serviço de IA.

Protege o app de espirais de falha e de queimar o rate limit do free tier:
depois de ``CIRCUIT_BREAKER_FAILURES`` erros consecutivos de infraestrutura, o
breaker abre e os fluxos passam a usar o fallback determinístico por
``CIRCUIT_BREAKER_OPEN_SECONDS``.
"""

from __future__ import annotations

from django.core.cache import cache
from django.utils import timezone

from apps.ai import budget

_BREAKER_KEY = "ai:breaker:global"
_FAILURES_KEY = "ai:breaker:failures"


def permission_granted() -> bool:
    """True quando chamadas de IA estão permitidas no momento."""
    opens_at = cache.get(_BREAKER_KEY)
    if not opens_at:
        return True
    try:
        return timezone.now().timestamp() >= float(opens_at)
    except (TypeError, ValueError):
        return True


def report_failure() -> None:
    """Registra uma falha; abre o breaker ao atingir o limite."""
    failures = int(cache.get(_FAILURES_KEY, 0) or 0) + 1
    cache.set(_FAILURES_KEY, failures, timeout=3600)
    if failures >= budget.CIRCUIT_BREAKER_FAILURES:
        opens_at = timezone.now().timestamp() + budget.CIRCUIT_BREAKER_OPEN_SECONDS
        cache.set(_BREAKER_KEY, opens_at, timeout=budget.CIRCUIT_BREAKER_OPEN_SECONDS)
        cache.set(_FAILURES_KEY, 0, timeout=3600)


def report_success() -> None:
    """Zera o contador de falhas após uma chamada bem-sucedida."""
    cache.delete(_FAILURES_KEY)