"""Modelos do painel do dono: telemetria agregada de uso e monetização.

Decisão arquitetural (baixo custo computacional):
- Uso é registrado como CONTADOR agregado por (usuário, recurso, dia) — uma
  única linha por dia/recurso/usuário, atualizada com ``F('count') + 1``.
  Sem fila de eventos individual: consultas e escrita são O(1) por beacon.
- A monetização é um singleton ``MonetizationConfig`` (uma linha só) com o
  interruptor "cadastro exige pagamento" e o catálogo de códigos de acesso
  que o dono emite manualmente (ou vende) para liberar novos cadastros.
"""

from django.conf import settings
from django.db import models
from django.utils import timezone


class FeatureEvent(models.Model):
    """Contador diário de uso de uma feature por usuário.

    ``feature`` é um slug de telemetria (ex.: ``nav.inicio``, ``nav.mais.importar``,
    ``cta.nova_transacao``, ``chat.abrir``). Uma linha = (user, feature, date).
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="+",
        verbose_name="usuário",
        db_index=True,
    )
    feature = models.CharField("recurso", max_length=64, db_index=True)
    date = models.DateField("data", db_index=True)
    count = models.PositiveIntegerField("contagem", default=0)

    class Meta:
        verbose_name = "evento de feature"
        verbose_name_plural = "eventos de feature"
        constraints = [
            models.UniqueConstraint(
                fields=["user", "feature", "date"],
                name="painel_featureevent_user_feature_date_uniq",
            ),
        ]
        indexes = [
            models.Index(fields=["date"], name="painel_feat_date_idx"),
            models.Index(fields=["feature"], name="painel_feat_feature_idx"),
        ]

    def __str__(self):
        return f"{self.feature} · {self.date} · {self.count}"


class MonetizationConfig(models.Model):
    """Configuração singleton de monetização do cadastro.

    Apenas uma linha deve existir (criada de forma preguiçosa). Quando
    ``signup_requires_payment`` está ligado, ``SignUpView`` passa a exigir um
    ``AccessCode`` válido e não usado para criar a conta.
    """

    signup_requires_payment = models.BooleanField(
        "cadastro exige pagamento",
        default=False,
        help_text="Quando ligado, novos cadastros só são aceitos com um código "
        "de acesso válido (indicado após o pagamento).",
    )
    price_label = models.CharField(
        "descrição do preço",
        max_length=60,
        default="R$ 9,90 / mês",
        help_text="Texto exibido na tela de cadastro quando o pagamento é exigido.",
    )
    payment_instructions = models.TextField(
        "instruções de pagamento",
        blank=True,
        help_text="Como o visitante deve proceder para obter o código de acesso.",
    )
    updated_at = models.DateTimeField("atualizado em", auto_now=True)

    class Meta:
        verbose_name = "configuração de monetização"
        verbose_name_plural = "configuração de monetização"

    def __str__(self):
        state = "exige pagamento" if self.signup_requires_payment else "cadastro livre"
        return f"Monetização — {state}"

    @classmethod
    def get_singleton(cls):
        """Retorna a configuração singleton, criando a primeira linha se preciso."""
        instance = cls.objects.first()
        if instance is None:
            instance = cls.objects.create()
        return instance


class AccessCode(models.Model):
    """Código de acesso emitido pelo dono para liberar um cadastro pago.

    Quando a monetização está ativa, o cadastro só cria a conta após informar
    um código não usado. O código é marcado como utilizado na criação da conta.
    """

    code = models.CharField(
        "código",
        max_length=40,
        unique=True,
        help_text="Código que o visitante informa no cadastro após pagar.",
    )
    note = models.CharField(
        "observação",
        max_length=120,
        blank=True,
        help_text="Ex.: canal de venda, cliente, lote.",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="criado por",
    )
    created_at = models.DateTimeField("criado em", auto_now_add=True)
    used_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="usado por",
    )
    used_at = models.DateTimeField("usado em", null=True, blank=True)
    revoked = models.BooleanField("revogado", default=False)

    class Meta:
        verbose_name = "código de acesso"
        verbose_name_plural = "códigos de acesso"
        ordering = ["-created_at"]

    def __str__(self):
        return self.code

    @property
    def is_used(self):
        return self.used_at is not None and self.used_by_id is not None

    @classmethod
    def redeem(cls, code: str, user):
        """Valida e consome um código de acesso para o usuário.

        Retorna a instância em caso de sucesso ou ``None`` se o código for
        inválido, revogado ou já utilizado.
        """
        obj = cls.objects.filter(
            code__iexact=code.strip(), used_by__isnull=True, revoked=False
        ).first()
        if obj is None:
            return None
        obj.used_by = user
        obj.used_at = timezone.now()
        obj.save(update_fields=["used_by", "used_at"])
        return obj