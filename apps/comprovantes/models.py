"""Modelo de comprovantes e garantias.

Guarda um anexo (arquivo) pequeno e dados de contexto: tipo, descrição,
data de expiração da garantia (quando aplicável) e observações.
"""

from datetime import timedelta

from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.ownership import OwnedModel


def comprovante_upload_to(instance, filename):
    return f"comprovantes/user_{instance.owner_id}/{instance.slug}_{filename}"


class Comprovante(OwnedModel):
    class Kind(models.TextChoices):
        RECEIPT = "receipt", _("Comprovante / Recibo")
        INVOICE = "invoice", _("Nota fiscal")
        WARRANTY = "warranty", _("Garantia")
        HEALTH = "health", _("Recibo de saúde (IR)")
        OTHER = "other", _("Outros")

    slug = models.CharField("código", max_length=60, blank=True)
    title = models.CharField("título", max_length=160)
    kind = models.CharField(
        "tipo", max_length=20, choices=Kind.choices, default=Kind.RECEIPT
    )
    file = models.FileField("arquivo", upload_to=comprovante_upload_to)
    warranty_expiry = models.DateField(
        "expiração da garantia", null=True, blank=True
    )
    notes = models.CharField(
        "observações", max_length=500, blank=True, default=""
    )
    created_at = models.DateTimeField("criado em", auto_now_add=True)
    updated_at = models.DateTimeField(_("atualizado em"), auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "comprovante"
        verbose_name_plural = "comprovantes"

    def __str__(self):
        return self.title

    def is_warranty_expiring(self, ref_date=None):
        """True se há garantia e ela expira dentro de 60 dias (ou já expirou)."""
        if not self.warranty_expiry:
            return False
        ref_date = ref_date or timezone.localdate()
        return self.warranty_expiry <= ref_date + timedelta(days=60)

    def warranty_status(self, ref_date=None):
        """Situação da garantia: expired | expiring | active | none."""
        if not self.warranty_expiry:
            return "none"
        ref_date = ref_date or timezone.localdate()
        if self.warranty_expiry < ref_date:
            return "expired"
        if self.warranty_expiry <= ref_date + timedelta(days=60):
            return "expiring"
        return "active"
