"""Modelo de snapshot do patrimônio (histórico para a curva de evolução).

Não duplica saldos: apenas congela o valor líquido consolidado em uma data,
para que o usuário acompanhe a evolução do patrimônio ao longo do tempo.
"""

from django.db import models

from apps.core.ownership import OwnedModel


class NetWorthSnapshot(OwnedModel):
    """Ponto de patrimônio líquido registrado em uma data (uma por dia)."""

    recorded_on = models.DateField("data", unique=False)
    assets = models.IntegerField("ativos (centavos)", default=0)
    liabilities = models.IntegerField("passivos (centavos)", default=0)
    net_worth = models.IntegerField("patrimônio líquido (centavos)", default=0)
    created_at = models.DateTimeField("criado em", auto_now_add=True)

    class Meta:
        ordering = ["-recorded_on"]
        constraints = [
            models.UniqueConstraint(
                fields=["owner", "recorded_on"], name="networth_snapshot_per_day"
            )
        ]
        verbose_name = "ponto de patrimônio"
        verbose_name_plural = "pontos de patrimônio"

    def __str__(self):
        return f"Patrimônio em {self.recorded_on}"
