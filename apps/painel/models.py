"""Modelos do Painel do Dono — telemetria, monetização e vendas.

Decisões arquiteturais (baixo custo):
- Uso é registrado como CONTADOR agregado por (usuário, recurso, dia) — uma
  linha por dia/recurso/usuário. Sem fila de eventos individual.
- Monetização/assinaturas usam poucas tabelas e índices; as métricas de receita
  são agregadas no banco (``values().annotate(...)``), nunca em Python.
- ``AccessCode`` pode estar ligado a um ``Plan``: ao resgatar, gera uma
  ``Subscription`` automaticamente.
"""

from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.text import slugify


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


# --------------------------------------------------------------------------- #
# Vendas — planos, cupons, assinaturas e pagamentos
# --------------------------------------------------------------------------- #

class Plan(models.Model):
    """Plano comercial vendido pelo dono (mensal, anual ou vitalício)."""

    MONTHLY = "monthly"
    YEARLY = "yearly"
    LIFETIME = "lifetime"
    CYCLE_CHOICES = [
        (MONTHLY, "Mensal"),
        (YEARLY, "Anual"),
        (LIFETIME, "Vitalício"),
    ]

    name = models.CharField("nome", max_length=80)
    slug = models.SlugField("identificador", max_length=80, unique=True, blank=True)
    description = models.TextField("descrição", blank=True)
    price = models.DecimalField("preço", max_digits=10, decimal_places=2, default=0)
    billing_cycle = models.CharField(
        "ciclo", max_length=10, choices=CYCLE_CHOICES, default=MONTHLY
    )
    duration_days = models.PositiveIntegerField(
        "duração (dias)",
        default=30,
        help_text="Dias de acesso liberados. Use 0 para vitalício/ilimitado.",
    )
    is_active = models.BooleanField("ativo", default=True)
    is_featured = models.BooleanField("destacado", default=False)
    order = models.PositiveIntegerField("ordem", default=0)
    created_at = models.DateTimeField("criado em", auto_now_add=True)
    updated_at = models.DateTimeField("atualizado em", auto_now=True)

    class Meta:
        verbose_name = "plano"
        verbose_name_plural = "planos"
        ordering = ["order", "price", "name"]

    def __str__(self):
        return f"{self.name} ({self.get_billing_cycle_display()})"

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.name)[:70] or "plano"
            slug = base
            counter = 1
            while Plan.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base}-{counter}"
                counter += 1
            self.slug = slug
        super().save(*args, **kwargs)

    @property
    def is_lifetime(self):
        return self.billing_cycle == self.LIFETIME or self.duration_days == 0

    @property
    def monthly_value(self):
        """Receita equivalente mensal (normaliza anual/vitalício para MRR)."""
        price = Decimal(self.price or 0)
        if self.is_lifetime:
            return Decimal("0")  # vitalício não entra no MRR recorrente
        if self.billing_cycle == self.YEARLY:
            return (price / Decimal("12")).quantize(Decimal("0.01"))
        return price


class Coupon(models.Model):
    """Cupom de desconto aplicável a um pagamento."""

    PERCENT = "percent"
    FIXED = "fixed"
    TYPE_CHOICES = [
        (PERCENT, "Percentual (%)"),
        (FIXED, "Valor fixo (R$)"),
    ]

    code = models.CharField("código", max_length=40, unique=True)
    discount_type = models.CharField("tipo", max_length=10, choices=TYPE_CHOICES, default=PERCENT)
    discount_value = models.DecimalField("valor do desconto", max_digits=10, decimal_places=2, default=0)
    valid_until = models.DateField("válido até", null=True, blank=True)
    max_uses = models.PositiveIntegerField("limite de usos", default=0, help_text="0 = ilimitado.")
    times_used = models.PositiveIntegerField("usos", default=0)
    is_active = models.BooleanField("ativo", default=True)
    created_at = models.DateTimeField("criado em", auto_now_add=True)

    class Meta:
        verbose_name = "cupom"
        verbose_name_plural = "cupons"
        ordering = ["-created_at"]

    def __str__(self):
        return self.code

    @property
    def is_valid(self):
        if not self.is_active:
            return False
        if self.valid_until and self.valid_until < timezone.localdate():
            return False
        if self.max_uses and self.times_used >= self.max_uses:
            return False
        return True

    def apply_to(self, value):
        """Aplica o desconto a ``value`` e retorna o valor final (>= 0)."""
        value = Decimal(value or 0)
        if self.discount_type == self.PERCENT:
            discount = value * (Decimal(self.discount_value) / Decimal("100"))
        else:
            discount = Decimal(self.discount_value)
        result = value - discount
        return result if result > 0 else Decimal("0")


class Subscription(models.Model):
    """Assinatura de um plano por um usuário."""

    ACTIVE = "active"
    TRIAL = "trial"
    EXPIRED = "expired"
    CANCELED = "canceled"
    STATUS_CHOICES = [
        (ACTIVE, "Ativa"),
        (TRIAL, "Período de teste"),
        (EXPIRED, "Expirada"),
        (CANCELED, "Cancelada"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="subscriptions",
        verbose_name="usuário",
    )
    plan = models.ForeignKey(
        Plan, on_delete=models.SET_NULL, null=True, related_name="subscriptions",
        verbose_name="plano",
    )
    status = models.CharField("status", max_length=10, choices=STATUS_CHOICES, default=ACTIVE)
    started_at = models.DateTimeField("início", default=timezone.now)
    expires_at = models.DateTimeField("expira em", null=True, blank=True)
    canceled_at = models.DateTimeField("cancelada em", null=True, blank=True)
    notes = models.CharField("observação", max_length=160, blank=True)
    created_at = models.DateTimeField("criada em", auto_now_add=True)
    updated_at = models.DateTimeField("atualizada em", auto_now=True)

    class Meta:
        verbose_name = "assinatura"
        verbose_name_plural = "assinaturas"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status"], name="painel_sub_status_idx"),
            models.Index(fields=["expires_at"], name="painel_sub_expires_idx"),
        ]

    def __str__(self):
        return f"{self.user} · {self.plan} · {self.get_status_display()}"

    @property
    def is_current(self):
        if self.status not in (self.ACTIVE, self.TRIAL):
            return False
        if self.expires_at is not None and self.expires_at < timezone.now():
            return False
        return True

    @property
    def days_remaining(self):
        if self.expires_at is None:
            return None
        delta = self.expires_at - timezone.now()
        return max(delta.days, 0)


class Payment(models.Model):
    """Registro de pagamento (entrada financeira da venda)."""

    PIX = "pix"
    CARD = "card"
    BOLETO = "boleto"
    TRANSFER = "transfer"
    OTHER = "other"
    METHOD_CHOICES = [
        (PIX, "Pix"),
        (CARD, "Cartão"),
        (BOLETO, "Boleto"),
        (TRANSFER, "Transferência"),
        (OTHER, "Outro"),
    ]

    PENDING = "pending"
    PAID = "paid"
    REFUNDED = "refunded"
    CANCELED = "canceled"
    STATUS_CHOICES = [
        (PENDING, "Pendente"),
        (PAID, "Pago"),
        (REFUNDED, "Reembolsado"),
        (CANCELED, "Cancelado"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="payments",
        verbose_name="cliente",
    )
    plan = models.ForeignKey(
        Plan, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="payments", verbose_name="plano",
    )
    subscription = models.ForeignKey(
        Subscription, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="payments", verbose_name="assinatura",
    )
    coupon = models.ForeignKey(
        Coupon, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="payments", verbose_name="cupom",
    )
    amount = models.DecimalField("valor", max_digits=10, decimal_places=2, default=0)
    discount = models.DecimalField("desconto", max_digits=10, decimal_places=2, default=0)
    method = models.CharField("método", max_length=10, choices=METHOD_CHOICES, default=PIX)
    status = models.CharField("status", max_length=10, choices=STATUS_CHOICES, default=PENDING)
    paid_at = models.DateTimeField("pago em", null=True, blank=True)
    reference = models.CharField("referência", max_length=120, blank=True)
    notes = models.TextField("observações", blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+", verbose_name="registrado por",
    )
    created_at = models.DateTimeField("criado em", auto_now_add=True)

    class Meta:
        verbose_name = "pagamento"
        verbose_name_plural = "pagamentos"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status"], name="painel_pay_status_idx"),
            models.Index(fields=["created_at"], name="painel_pay_created_idx"),
        ]

    def __str__(self):
        return f"{self.user} · R$ {self.amount} · {self.get_status_display()}"

    @property
    def net_amount(self):
        return (Decimal(self.amount or 0) - Decimal(self.discount or 0)).quantize(Decimal("0.01"))

    def mark_paid(self, when=None):
        self.status = self.PAID
        self.paid_at = when or timezone.now()
        self.save(update_fields=["status", "paid_at"])


class MonetizationConfig(models.Model):
    """Configuração singleton de monetização do cadastro."""

    signup_requires_payment = models.BooleanField(
        "cadastro exige pagamento",
        default=False,
        help_text="Quando ligado, novos cadastros só são aceitos com um código "
        "de acesso válido (indicado após o pagamento).",
    )
    default_plan = models.ForeignKey(
        Plan, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
        verbose_name="plano padrão",
        help_text="Plano liberado por padrão quando a monetização está ativa.",
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
    support_contact = models.CharField(
        "contato de suporte",
        max_length=120,
        blank=True,
        help_text="WhatsApp/email exibido ao cliente para dúvidas de pagamento.",
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
        instance = cls.objects.first()
        if instance is None:
            instance = cls.objects.create()
        return instance


class AccessCode(models.Model):
    """Código de acesso emitido pelo dono para liberar um cadastro pago."""

    code = models.CharField(
        "código",
        max_length=40,
        unique=True,
        help_text="Código que o visitante informa no cadastro após pagar.",
    )
    plan = models.ForeignKey(
        Plan, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="access_codes", verbose_name="plano",
        help_text="Plano liberado ao resgatar este código.",
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

        Se o código estiver ligado a um ``Plan``, cria uma assinatura para o
        usuário. Retorna a instância ou ``None`` se inválido/revogado/usado.
        """
        obj = cls.objects.filter(
            code__iexact=code.strip(), used_by__isnull=True, revoked=False
        ).first()
        if obj is None:
            return None
        obj.used_by = user
        obj.used_at = timezone.now()
        obj.save(update_fields=["used_by", "used_at"])
        if obj.plan_id:
            from .services import grant_subscription

            grant_subscription(user, obj.plan, notes=f"Código {obj.code}")
        return obj
