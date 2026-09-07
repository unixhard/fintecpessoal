"""Modelos do app reports (relatórios).

``AIReport`` guarda o resultado de uma análise por IA — um relatório em texto
(Markdown) gerado conforme o cooldown do app (padrão 3 dias, configurável via
REPORT_COOLDOWN_DAYS), com isolamento por usuário (OwnedModel).
"""

from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.ownership import OwnedModel


class AIReport(OwnedModel):
    """Relatório de análise por IA sobre as finanças do usuário."""

    summary = models.CharField(
        "resumo", max_length=200, blank=True, default="",
        help_text="Uma frase de conclusão curta, para exibir na dashboard.",
    )
    content = models.TextField("conteúdo", blank=True, default="")
    via_ai = models.BooleanField("gerado por IA", default=True)
    generated_at = models.DateTimeField("gerado em", auto_now_add=True)

    class Meta:
        ordering = ["-generated_at"]
        verbose_name = "relatório de análise"
        verbose_name_plural = "relatórios de análise"

    def __str__(self):
        return f"Análise de {self.generated_at:%d/%m/%Y %H:%M}"
