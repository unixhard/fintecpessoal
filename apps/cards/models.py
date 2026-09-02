"""App cards — cartões de crédito e suas faturas/parcelas.

Modelos (arquitetura docs/ARQUITETURA_DOMINIO.md D4/D5/D6):
- CreditCard          : linha de crédito (entidade SEPARADA de Account).
- InstallmentPurchase : compra parcelada (ex.: 1.200 em 12x).
- Installment         : uma parcela da compra (paga/pendente/...).
- CreditCardInvoice   : fatura mensal; amount DERIVADO das parcelas do período
                        (evita dupla contabilização).
"""

from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.ownership import OwnedModel
from apps.finance.models import Transaction


class CreditCard(OwnedModel):
    """Cartão de crédito — entidade independente de Account."""

    class Status(models.TextChoices):
        ACTIVE = "active", _("Ativo")
        BLOCKED = "blocked", _("Bloqueado")
        CLOSED = "closed", _("Encerrado")

    name = models.CharField("nome", max_length=120)
    institution = models.CharField("instituição", max_length=120, blank=True)
    limit = models.IntegerField("limite (centavos)", default=0)
    closing_day = models.PositiveIntegerField("dia de fechamento", default=1)
    due_day = models.PositiveIntegerField("dia de vencimento", default=10)
    payment_account = models.ForeignKey(
        "finance.Account",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="credit_cards",
        verbose_name="conta de pagamento",
    )
    status = models.CharField(
        "status", max_length=20, choices=Status.choices, default=Status.ACTIVE
    )
    created_at = models.DateTimeField("criado em", auto_now_add=True)
    updated_at = models.DateTimeField("atualizado em", auto_now=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "cartão de crédito"
        verbose_name_plural = "cartões de crédito"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(limit__gte=0),
                name="cards_creditcard_limit_gte_0",
            ),
            models.CheckConstraint(
                condition=models.Q(closing_day__gte=1) & models.Q(closing_day__lte=31),
                name="cards_creditcard_closing_day_range",
            ),
            models.CheckConstraint(
                condition=models.Q(due_day__gte=1) & models.Q(due_day__lte=31),
                name="cards_creditcard_due_day_range",
            ),
        ]

    def __str__(self):
        return self.name

    def clean(self):
        if (
            self.payment_account_id
            and self.payment_account.owner_id != self.owner_id
        ):
            raise ValidationError(
                {"payment_account": "A conta de pagamento deve ser do mesmo usuário."}
            )

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)


class InstallmentPurchase(OwnedModel):
    """Compra parcelada no cartão.

    Representa a compra como entidade própria (decisão D5), agrupando as
    parcelas (Installment), de modo a enxergar pago/falta/comprometimento.
    """

    class Status(models.TextChoices):
        ONGOING = "ongoing", _("Em andamento")
        COMPLETED = "completed", _("Concluída")
        CANCELLED = "cancelled", _("Cancelada")

    card = models.ForeignKey(
        CreditCard,
        on_delete=models.PROTECT,
        related_name="purchases",
        verbose_name="cartão",
    )
    description = models.CharField("descrição", max_length=200)
    total_amount = models.IntegerField("valor total (centavos)")
    installment_count = models.PositiveIntegerField("quantidade de parcelas")
    installment_amount = models.IntegerField("valor da parcela (centavos)")
    first_due_date = models.DateField("primeira parcela")
    status = models.CharField(
        "status", max_length=20, choices=Status.choices, default=Status.ONGOING
    )
    created_at = models.DateTimeField("criado em", auto_now_add=True)
    updated_at = models.DateTimeField("atualizado em", auto_now=True)

    class Meta:
        ordering = ["-first_due_date"]
        verbose_name = "compra parcelada"
        verbose_name_plural = "compras parceladas"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(total_amount__gt=0),
                name="cards_purchase_total_gt_0",
            ),
            models.CheckConstraint(
                condition=models.Q(installment_count__gte=1),
                name="cards_purchase_count_gte_1",
            ),
            models.CheckConstraint(
                condition=models.Q(installment_amount__gt=0),
                name="cards_purchase_installment_amount_gt_0",
            ),
        ]

    def __str__(self):
        return f"{self.description} ({self.installment_count}x)"

    def clean(self):
        if self.card and self.card.owner_id != self.owner_id:
            raise ValidationError(
                {"card": "O cartão deve pertencer ao mesmo usuário."}
            )

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    @property
    def paid_amount(self):
        return sum(
            i.amount
            for i in self.installments.filter(status=Installment.Status.PAID)
        )

    @property
    def remaining_amount(self):
        return self.total_amount - self.paid_amount

    def generate_installments(self, period_months=1):
        """Cria as parcelas (Installment) desta compra.

        Distribui as parcelas a partir de ``first_due_date`` usando
        ``period_months`` (padrão mensal). O saldo de arredondamento é
        absorvido pela última parcela, garantindo que
        ``sum(parcelas) == total_amount``. As parcelas nascem pendentes.
        """
        from datetime import date

        if self.installments.exists():
            return self.installments.all()

        base = self.installment_amount * self.installment_count
        rows = []
        for number in range(1, self.installment_count + 1):
            amount = self.installment_amount
            # Última parcela absorve eventual diferença de arredondamento.
            if number == self.installment_count and base != self.total_amount:
                amount += self.total_amount - base
            due = add_months(self.first_due_date, (number - 1) * period_months)
            rows.append(
                Installment(
                    owner=self.owner,
                    purchase=self,
                    number=number,
                    amount=amount,
                    due_date=due,
                )
            )
        Installment.objects.bulk_create(rows)
        return self.installments.all()


def add_months(source_date, months):
    """Avança ``months`` meses a partir de ``source_date``.

    Se o dia não existir no mês de destino (ex.: 31 em fevereiro), cai para o
    último dia do mês (regra de datas financeiras, seção 11 da arquitetura).
    """
    from calendar import monthrange

    year = source_date.year
    month = source_date.month + months
    while month > 12:
        month -= 12
        year += 1
    while month < 1:
        month += 12
        year -= 1
    day = min(source_date.day, monthrange(year, month)[1])
    return source_date.replace(year=year, month=month, day=day)


class Installment(OwnedModel):
    """Uma parcela de uma compra parcelada."""

    class Status(models.TextChoices):
        PENDING = "pending", _("Pendente")
        PAID = "paid", _("Paga")
        OVERDUE = "overdue", _("Atrasada")
        SKIPPED = "skipped", _("Pulada")

    purchase = models.ForeignKey(
        InstallmentPurchase,
        on_delete=models.CASCADE,
        related_name="installments",
        verbose_name="compra",
    )
    number = models.PositiveIntegerField("parcela nº")
    amount = models.IntegerField("valor (centavos)")
    due_date = models.DateField("vencimento")
    status = models.CharField(
        "status", max_length=20, choices=Status.choices, default=Status.PENDING
    )
    invoice = models.ForeignKey(
        "cards.CreditCardInvoice",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="installments",
        verbose_name="fatura",
    )
    created_at = models.DateTimeField("criado em", auto_now_add=True)

    class Meta:
        ordering = ["purchase", "number"]
        verbose_name = "parcela"
        verbose_name_plural = "parcelas"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount__gt=0),
                name="cards_installment_amount_gt_0",
            ),
            models.CheckConstraint(
                condition=models.Q(number__gte=1),
                name="cards_installment_number_gte_1",
            ),
            models.UniqueConstraint(
                fields=["purchase", "number"],
                name="cards_installment_unique_per_purchase",
            ),
        ]

    def __str__(self):
        return f"{self.purchase} — parcela {self.number}"

    def clean(self):
        errors = {}
        if self.purchase and self.purchase.owner_id != self.owner_id:
            errors["purchase"] = "A compra deve pertencer ao mesmo usuário."
        if self.invoice and self.invoice.owner_id != self.owner_id:
            errors["invoice"] = "A fatura deve pertencer ao mesmo usuário."
        if (
            self.purchase_id
            and self.invoice_id
            and self.invoice.card_id != self.purchase.card_id
        ):
            errors["invoice"] = (
                "A fatura deve ser do mesmo cartão da compra."
            )
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)


class CreditCardInvoice(OwnedModel):
    """Fatura de cartão de crédito.

    O valor (amount) é DERIVADO da soma das parcelas do período, evitando
    dupla contabilização. Pagamento da fatura (fluxo futuro) gera UMA
    Transaction e muda o status para paid — sem criar segunda despesa (D6).
    """

    class Status(models.TextChoices):
        OPEN = "open", _("Aberta")
        CLOSED = "closed", _("Fechada")
        PAID = "paid", _("Paga")
        OVERDUE = "overdue", _("Atrasada")

    card = models.ForeignKey(
        CreditCard,
        on_delete=models.PROTECT,
        related_name="invoices",
        verbose_name="cartão",
    )
    period_start = models.DateField("início do período")
    period_end = models.DateField("fim do período")
    closing_date = models.DateField("data de fechamento")
    due_date = models.DateField("data de vencimento")
    status = models.CharField(
        "status", max_length=20, choices=Status.choices, default=Status.OPEN
    )
    payment_transaction = models.ForeignKey(
        "finance.Transaction",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="paid_invoices",
        verbose_name="pagamento",
    )
    payment_account = models.ForeignKey(
        "finance.Account",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="invoice_payments",
        verbose_name="conta de pagamento",
    )
    created_at = models.DateTimeField("criado em", auto_now_add=True)
    updated_at = models.DateTimeField("atualizado em", auto_now=True)

    class Meta:
        ordering = ["-due_date"]
        verbose_name = "fatura de cartão"
        verbose_name_plural = "faturas de cartão"
        constraints = [
            models.UniqueConstraint(
                fields=["card", "period_start", "period_end"],
                name="cards_invoice_unique_per_period",
            ),
        ]

    def __str__(self):
        return f"{self.card} — {self.period_start} a {self.period_end}"

    @property
    def amount(self):
        """Valor da fatura (centavos) derivado das parcelas/linhas do período.

        Derivado (nunca armazenado) para evitar dupla contabilização (D6).
        """
        return sum(i.amount for i in self.installments.all())

    def clean(self):
        errors = {}
        if self.card and self.card.owner_id != self.owner_id:
            errors["card"] = "O cartão deve pertencer ao mesmo usuário."
        if (
            self.payment_transaction_id
            and self.payment_transaction.owner_id != self.owner_id
        ):
            errors["payment_transaction"] = (
                "O pagamento deve pertencer ao mesmo usuário."
            )
        if (
            self.payment_account_id
            and self.payment_account.owner_id != self.owner_id
        ):
            errors["payment_account"] = (
                "A conta de pagamento deve pertencer ao mesmo usuário."
            )
        if self.period_start and self.period_end and self.period_end < self.period_start:
            errors["period_end"] = "O fim do período deve ser após o início."
        if self.closing_date and self.due_date and self.due_date < self.closing_date:
            errors["due_date"] = "O vencimento deve ser após o fechamento."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)
