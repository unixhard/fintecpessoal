"""App budgets — orçamentos por categoria ou global."""

from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.ownership import OwnedModel


class Budget(OwnedModel):
    """Limite de gasto por categoria ou global.

    O valor "realizado" não é armazenado — é calculado a partir das
    transações de despesa na categoria/período quando necessário.
    """

    class Kind(models.TextChoices):
        CATEGORY = "category", _("Por categoria")
        GLOBAL = "global", _("Global")

    class Period(models.TextChoices):
        MONTHLY = "monthly", _("Mensal")
        YEARLY = "yearly", _("Anual")
        CUSTOM = "custom", _("Personalizado")

    kind = models.CharField("tipo", max_length=20, choices=Kind.choices)
    category = models.ForeignKey(
        "finance.Category",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="budgets",
        verbose_name="categoria",
        help_text="Obrigatório quando o tipo é 'por categoria'.",
    )
    period = models.CharField(
        "período", max_length=20, choices=Period.choices, default=Period.MONTHLY
    )
    limit_amount = models.IntegerField("limite (centavos)", default=0)
    start_date = models.DateField("data inicial", null=True, blank=True)
    end_date = models.DateField(
        "data final", null=True, blank=True, help_text="Opcional; vazio = ativo."
    )
    is_active = models.BooleanField("ativo", default=True)
    created_at = models.DateTimeField("criado em", auto_now_add=True)
    updated_at = models.DateTimeField("atualizado em", auto_now=True)

    class Meta:
        ordering = ["kind", "id"]
        indexes = [
            models.Index(fields=["owner", "is_active"]),
        ]
        verbose_name = "orçamento"
        verbose_name_plural = "orçamentos"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(limit_amount__gte=0),
                name="budgets_budget_limit_gte_0",
            ),
        ]

    def __str__(self):
        if self.kind == self.Kind.GLOBAL:
            target = "Global"
        else:
            target = str(self.category)
        return f"{target} — {self.limit_amount}"

    def clean(self):
        errors = {}
        if self.kind == self.Kind.CATEGORY and not self.category_id:
            errors["category"] = "Orçamento por categoria exige uma categoria."
        if (
            self.kind == self.Kind.CATEGORY
            and self.category_id
            and self.category.owner_id != self.owner_id
        ):
            errors["category"] = (
                "A categoria deve pertencer ao mesmo usuário."
            )
        if self.kind == self.Kind.GLOBAL and self.category_id:
            errors["category"] = (
                "Orçamento global não deve ter categoria associada."
            )
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)
