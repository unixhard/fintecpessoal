"""Utilitário de isolamento multiusuário (decisão D14).

Fornece uma base reutilizável para todas as entidades do domínio financeiro:

- ``OwnedQuerySet``: QuerySet com ``for_user(user)`` para filtrar por owner.
- ``OwnedModel``: base abstrata com campo ``owner`` (FK para AUTH_USER_MODEL)
  e manager padrão baseado em ``OwnedQuerySet``.

Todo model financeiro deve herdar de ``OwnedModel``. As views/serviços DEVERÃO
usar ``Model.objects.for_user(request.user)`` — nunca confiar apenas na interface.
"""

from django.conf import settings
from django.db import models


class OwnedQuerySet(models.QuerySet):
    """QuerySet com consciência do proprietário."""

    def for_user(self, user):
        """Retorna apenas objetos pertencentes a ``user``."""
        return self.filter(owner=user)


class OwnedManager(models.Manager.from_queryset(OwnedQuerySet)):
    """Manager padrão para entidades com proprietário."""


class OwnedModel(models.Model):
    """Base abstrata: toda entidade financeira pertence a um usuário.

    Todos os dados financeiros devem ser isolados por usuário (requisito
    crítico). O campo ``owner`` é derivado do ``request.user`` autenticado
    nas camadas de escrita, nunca recebido de input do cliente.
    """

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="%(app_label)s_%(class)s_set",
        verbose_name="proprietário",
    )

    objects = OwnedManager()

    class Meta:
        abstract = True
