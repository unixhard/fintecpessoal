"""Seeda a taxonomia padrão (Ordem 18 — FASE 3) para usuários existentes.

Backfill destrutivo: NÃO remove nada. Cria, de forma idempotente, as
categorias/subcategorias padrão de cada usuário já presente no banco.
Novos usuários são semeados no onboarding (accounts/onboarding.py).

A migração é idempotente: rodar/desfazer não duplica nem apaga categorias.
"""

from django.conf import settings
from django.db import migrations


def seed_existing(apps, schema_editor):
    from apps.finance.services.categories import seed_default_categories

    user_model = apps.get_model(settings.AUTH_USER_MODEL)
    for user in list(user_model.objects.all()):
        try:
            seed_default_categories(user=user)
        except Exception:  # pragma: no cover - robustez no backfill
            # Uma falha isolada não deve abortar o backfill de todos.
            continue


def noop(apps, schema_editor):
    """Reverse: não removemos categorias padronizadas (não destrutivo)."""
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("finance", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed_existing, noop),
    ]
