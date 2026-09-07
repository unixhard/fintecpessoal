"""App debts — dívidas e compromissos financeiros (núcleo enxuto).

Sem subsistema completo de amortização/juros Price/SAC/simuladores nesta fase
(decisão documentada). Apenas os registros essenciais.
"""

from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.ownership import OwnedModel


class Debt(OwnedModel):
    """Dívida/compromisso financeiro (empréstimo, financiamento, outros)."""

    class Type(models.TextChoices):
        LOAN = "loan", _("Empréstimo")
        FINANCING = "financing", _("Financiamento")
        EXTERNAL_INSTALLMENT = "external_installment", _("Parcelamento externo")
        OTHER = "other", _("Outros")

    class Status(models.TextChoices):
        ACTIVE = "active", _("Ativa")
        PAID_OFF = "paid_off", _("Quitada")
        DEFAULTED = "defaulted", _("Inadimplente")
        ARCHIVED = "archived", _("Arquivada")

    type = models.CharField(
        "tipo", max_length=30, choices=Type.choices, default=Type.LOAN
    )
    name = models.CharField("nome", max_length=120)
    total_amount = models.IntegerField("valor total (centavos)", default=0)
    paid_amount = models.IntegerField("valor pago (centavos)", default=0)
    # Taxa de juros NÃO é dinheiro: usa decimal percentual, nunca float sobre centavos.
    interest_rate = models.DecimalField(
        "taxa de juros (% a.m.)",
        max_digits=6,
        decimal_places=4,
        null=True,
        blank=True,
    )
    start_date = models.DateField("data inicial", null=True, blank=True)
    end_date = models.DateField("data final", null=True, blank=True)
    creditor = models.CharField("credor", max_length=120, blank=True)
    status = models.CharField(
        "status", max_length=20, choices=Status.choices, default=Status.ACTIVE
    )
    created_at = models.DateTimeField("criado em", auto_now_add=True)
    updated_at = models.DateTimeField("atualizado em", auto_now=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "dívida"
        verbose_name_plural = "dívidas"
        indexes = [
            models.Index(fields=["owner", "status"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(total_amount__gte=0),
                name="debts_debt_total_gte_0",
            ),
            models.CheckConstraint(
                condition=models.Q(paid_amount__gte=0),
                name="debts_debt_paid_gte_0",
            ),
            models.CheckConstraint(
                condition=models.Q(paid_amount__lte=models.F("total_amount")),
                name="debts_debt_paid_le_total",
            ),
        ]

    def __str__(self):
        return self.name

    @property
    def remaining_amount(self):
        return self.total_amount - self.paid_amount
