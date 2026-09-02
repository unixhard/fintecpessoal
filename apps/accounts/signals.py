"""Signals do app accounts.

Cria o Profile automaticamente quando um User é criado (decisão D3).
As categorias padrão também são providas por usuário — ver apps/finance.
"""

from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_user_profile(sender, instance, created, **kwargs):
    """Garante que todo usuário tenha um Profile."""
    if created:
        from .models import Profile

        Profile.objects.create(user=instance)
