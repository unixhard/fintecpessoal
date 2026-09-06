"""Memória determinística de aprendizado por correção (Ordem 18 — FASE 5 §4).

- determinística e explicável (a ``key`` é uma impressão digital auditável);
- por usuário e isolada (cada usuário tem sua própria memória);
- reversível (``forget`` apaga e reverte o aprendizado);
- nunca se espalha entre usuários (isolamento multiusuário obrigatório).
"""

from ..models import UserPreference
from .merchants import normalize_description


def learn(*, user, key, category, merchant=None, kind="expense"):
    """Registra (ou fortalece) uma preferência de classificação do usuário.

    ``key`` normalmente é a descrição normalizada. Idempotente por
    (owner, key): se existir, incrementa ``count`` e atualiza categoria.
    """
    if not key:
        return None
    pref, created = UserPreference.objects.get_or_create(
        owner=user,
        key=key,
        defaults={
            "category": category if (category and category.owner_id == user.id) else None,
            "merchant": merchant,
            "kind": kind,
            "confidence": 0.90,
            "count": 1,
        },
    )
    if not created:
        # Fortalece: reaplica a categoria mais recente do usuário.
        if category and category.owner_id == user.id:
            pref.category = category
        if merchant is not None:
            pref.merchant = merchant
        pref.kind = kind
        pref.count += 1
        pref.save(update_fields=["category", "merchant", "kind", "count", "last_corrected_at"])
    return pref


def forget(*, user, key):
    """Reverte o aprendizado (apaga a memória). Reversível/auditável."""
    if not key:
        return 0
    deleted, _ = UserPreference.objects.for_user(user).filter(key=key).delete()
    return deleted


def normalize_key(description: str) -> str:
    """Impressão digital normalizada usada como chave de memória."""
    return normalize_description(description)
