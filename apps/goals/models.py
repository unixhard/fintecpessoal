"""App goals — metas financeiras."""

from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.ownership import OwnedModel


class Goal(OwnedModel):
    """Meta financeira (ex.: Viagem R$ 5.000, Reserva R$ 10.000)."""

    class Priority(models.TextChoices):
        LOW = "low", _("Baixa")
        MEDIUM = "medium", _("Média")
        HIGH = "high", _("Alta")

    class Status(models.TextChoices):
        ACTIVE = "active", _("Ativa")
        PAUSED = "paused", _("Pausada")
        ACHIEVED = "achieved", _("Alcançada")
        ARCHIVED = "archived", _("Arquivada")

    name = models.CharField("nome", max_length=120)
    target_amount = models.IntegerField("valor objetivo (centavos)", default=0)
    current_amount = models.IntegerField(
        "valor atual (centavos)", default=0
    )
    target_date = models.DateField("data objetivo", null=True, blank=True)
    priority = models.CharField(
        "prioridade", max_length=20, choices=Priority.choices,
        default=Priority.MEDIUM,
    )
    status = models.CharField(
        "status", max_length=20, choices=Status.choices, default=Status.ACTIVE
    )
    notes = models.TextField("observações", blank=True)
    created_at = models.DateTimeField("criado em", auto_now_add=True)
    updated_at = models.DateTimeField("atualizado em", auto_now=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "meta"
        verbose_name_plural = "metas"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(target_amount__gte=0),
                name="goals_goal_target_gte_0",
            ),
            models.CheckConstraint(
                condition=models.Q(current_amount__gte=0),
                name="goals_goal_current_gte_0",
            ),
        ]

    def __str__(self):
        return self.name

    @property
    def progress_percent(self):
        """Progresso percentual conforme os valores (nunca float crítico)."""
        if self.target_amount <= 0:
            return 0
        return int((self.current_amount / self.target_amount) * 100)
