"""Núcleo financeiro do FINTECPESSOAL.

Contém o razão (ledger) principal: Account, Category, Transaction, Transfer e
RecurringRule. Todos os valores monetários são inteiros em CENTAVOS (nunca
float — decisão D10). Todo model herda de OwnedModel (isolamento, decisão D14).

Modelos desta app:
- Account         : onde o dinheiro existe (conta corrente, poupança, carteira...).
- Category        : classificação (com hierarquia pai/subcategoria).
- Transaction     : lançamento raiz (income/expense/transfer/adjustment).
- Transfer        : transferência entre contas do mesmo usuário (2 pernas).
- RecurringRule   : regra de repetição (projeção sob demanda, sem gerar milhares).

Relações cruzam outras apps (cards.CreditCard) via referências por string de
label ("cards.CreditCard") para evitar importes circulares.
"""

from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.ownership import OwnedModel


class Account(OwnedModel):
    """Conta financeira — representa onde o dinheiro existe."""

    class Type(models.TextChoices):
        CHECKING = "checking", _("Conta corrente")
        SAVINGS = "savings", _("Poupança")
        CASH = "cash", _("Carteira / dinheiro físico")
        DIGITAL = "digital", _("Conta digital")
        INVESTMENT = "investment", _("Investimento")
        CREDIT_CARD = "credit_card", _("Cartão de crédito")
        OTHER = "other", _("Outros")

    class Status(models.TextChoices):
        ACTIVE = "active", _("Ativa")
        ARCHIVED = "archived", _("Arquivada")
        CLOSED = "closed", _("Encerrada")

    name = models.CharField("nome", max_length=120)
    institution = models.CharField("instituição", max_length=120, blank=True)
    type = models.CharField(
        "tipo", max_length=20, choices=Type.choices, default=Type.CHECKING
    )
    # Valores monetários em CENTAVOS (int) — nunca float.
    initial_balance = models.IntegerField("saldo inicial (centavos)", default=0)
    initial_balance_date = models.DateField(
        "data do saldo inicial", null=True, blank=True
    )
    currency = models.CharField("moeda", max_length=3, default="BRL")
    status = models.CharField(
        "status", max_length=20, choices=Status.choices, default=Status.ACTIVE
    )
    created_at = models.DateTimeField("criado em", auto_now_add=True)
    updated_at = models.DateTimeField("atualizado em", auto_now=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "conta"
        verbose_name_plural = "contas"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(initial_balance__gte=0),
                name="finance_account_initial_balance_gte_0",
            ),
        ]

    def __str__(self):
        return f"{self.name} ({self.get_type_display()})"


class Category(OwnedModel):
    """Categoria de classificação, com suporte a hierarquia pai/subcategoria.

    Categorias padrão são providas (semeadas) por usuário no cadastro
    (decisão D9), permitindo personalização sem afetar outros usuários.
    """

    class Kind(models.TextChoices):
        EXPENSE = "expense", _("Despesa")
        INCOME = "income", _("Receita")
        TRANSFER = "transfer", _("Transferência")

    class Status(models.TextChoices):
        ACTIVE = "active", _("Ativa")
        INACTIVE = "inactive", _("Inativa")

    name = models.CharField("nome", max_length=120)
    parent = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="subcategories",
        verbose_name="categoria pai",
    )
    kind = models.CharField(
        "tipo", max_length=20, choices=Kind.choices, default=Kind.EXPENSE
    )
    is_default = models.BooleanField("categoria padrão", default=False)
    status = models.CharField(
        "status", max_length=20, choices=Status.choices, default=Status.ACTIVE
    )
    created_at = models.DateTimeField("criado em", auto_now_add=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "categoria"
        verbose_name_plural = "categorias"
        constraints = [
            models.UniqueConstraint(
                fields=["owner", "name", "parent", "kind"],
                name="finance_category_unique_per_owner",
            ),
        ]

    def __str__(self):
        if self.parent_id:
            return f"{self.parent} / {self.name}"
        return self.name

    def clean(self):
        if self.parent_id:
            if self.pk and self.parent_id == self.pk:
                raise ValidationError("Uma categoria não pode ser pai dela mesma.")
            if self.parent.owner_id != self.owner_id:
                raise ValidationError(
                    "A categoria pai deve pertencer ao mesmo usuário."
                )

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)


class CatalogQuerySet(models.QuerySet):
    """QuerySet para entidades de catálogo (Merchant/Alias).

    Um estabelecimento/alias pode ser:
      - GLOBAL (``owner IS NULL``) — catálogo compartilhado, gerenciado por
        admin, apenas leitura para usuários comuns;
      - PESSOAL (``owner`` definido) — personalizado pelo usuário, isolado.

    ``for_user(user)`` devolve global + pessoal do usuário — o usuário NUNCA
    enxerga o pessoal de outro usuário (isolamento, decisão D14).
    """

    def for_user(self, user):
        return self.filter(models.Q(owner=user) | models.Q(owner__isnull=True))

    def owned(self, user):
        """Apenas itens pessoais do usuário."""
        return self.filter(owner=user)

    def catalog(self):
        """Apenas itens globais (catálogo compartilhado)."""
        return self.filter(owner__isnull=True)


class CatalogManager(models.Manager.from_queryset(CatalogQuerySet)):
    pass


class Merchant(models.Model):
    """Estabelecimento financeiro (identidade normalizada).

    Modelo HÍBRIDO (decisão Ordem 18/FASE 2):
      - ``owner IS NULL``  → estabelecimento GLOBAL (catálogo compartilhado),
        read-only para usuários; gerenciado por admin.
      - ``owner`` definido  → estabelecimento PESSOAL do usuário (isolado).

    ``name`` é o nome normalizado/apresentável (ex.: "Uber"). Aliases mapeiam
    descrições variantes para esta identidade. ``default_category_name`` é a
    associação SEMÂNTICA FUTURA com categoria/subcategoria (resolvida na FASE 5
    de classificação), sem violar ownership de Category.
    """

    class Source(models.TextChoices):
        CATALOG = "catalog", _("Catálogo")
        USER = "user", _("Usuário")
        AUTO = "auto", _("Automática")

    name = models.CharField("nome", max_length=120)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="merchants",
        verbose_name="proprietário (null = global)",
    )
    source = models.CharField(
        "origem", max_length=20, choices=Source.choices, default=Source.CATALOG
    )
    default_category_name = models.CharField(
        "categoria padrão sugerida", max_length=120, blank=True, default=""
    )
    is_default = models.BooleanField("estabelecimento padrão", default=False)
    created_at = models.DateTimeField("criado em", auto_now_add=True)
    updated_at = models.DateTimeField("atualizado em", auto_now=True)

    objects = CatalogManager()

    class Meta:
        ordering = ["name"]
        verbose_name = "estabelecimento"
        verbose_name_plural = "estabelecimentos"
        constraints = [
            models.UniqueConstraint(
                fields=["owner", "name"],
                name="finance_merchant_unique_per_owner",
            ),
        ]

    def __str__(self):
        return self.name or "(sem nome)"

    @property
    def is_global(self) -> bool:
        return self.owner_id is None


class MerchantAlias(models.Model):
    """Alias (nome variante) que resolve para um Merchant.

    Ex.: "UBER *TRIP", "UBER TECNOLOGIA", "IFD", "IFOOD.COM" -> Merchant.

    Também híbrido: ``owner IS NULL`` é alias GLOBAL (catálogo compartilhado);
    ``owner`` definido é alias PESSOAL (isolado), criado/aprendido pelo usuário.

    ``confidence`` (quando preenchida) é derivada por uma REGRA OBJETIVA no
    momento da resolução — nunca inventada.
    """

    class Source(models.TextChoices):
        CATALOG = "catalog", _("Catálogo")
        USER = "user", _("Usuário")
        HISTORY = "history", _("Histórico do usuário")
        AUTO = "auto", _("Automática")

    merchant = models.ForeignKey(
        Merchant,
        on_delete=models.CASCADE,
        related_name="aliases",
        verbose_name="estabelecimento",
    )
    alias = models.CharField("alias", max_length=200)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="merchant_aliases",
        verbose_name="proprietário (null = global)",
    )
    source = models.CharField(
        "origem", max_length=20, choices=Source.choices, default=Source.CATALOG
    )
    confidence = models.DecimalField(
        "confiança", max_digits=4, decimal_places=3, null=True, blank=True
    )
    use_count = models.PositiveIntegerField("usos", default=0)
    created_at = models.DateTimeField("criado em", auto_now_add=True)
    updated_at = models.DateTimeField("atualizado em", auto_now=True)

    objects = CatalogManager()

    class Meta:
        ordering = ["alias"]
        verbose_name = "alias de estabelecimento"
        verbose_name_plural = "aliases de estabelecimento"
        constraints = [
            models.UniqueConstraint(
                fields=["owner", "alias"],
                name="finance_merchantalias_unique_per_owner",
            ),
        ]

    def __str__(self):
        return f"{self.alias} -> {self.merchant}"

    @property
    def is_global(self) -> bool:
        return self.owner_id is None


class Transaction(OwnedModel):
    """Lançamento financeiro raiz.

    Regras de contabilização por tipo (decisões D5/D6/D7):
    - income/expense : lançamento simples sobre uma conta.
    - transfer       : duas pernas associadas (origem/destino) — patrimônio cte.
    - adjustment     : correção de saldo (notes obrigatório).

    Regras de isolamento (não expressáveis como CHECK de linha única):
    - account.owner  == self.owner
    - category.owner == self.owner
    Validadas em clean()/save().
    """

    class Type(models.TextChoices):
        INCOME = "income", _("Receita")
        EXPENSE = "expense", _("Despesa")
        TRANSFER = "transfer", _("Transferência")
        ADJUSTMENT = "adjustment", _("Ajuste")

    class Source(models.TextChoices):
        MANUAL = "manual", _("Manual")
        IMPORTED_CSV = "imported_csv", _("Importado (CSV)")
        IMPORTED_OFX = "imported_ofx", _("Importado (OFX)")
        RECURRENCE = "recurrence", _("Recorrência")
        SYSTEM = "system", _("Sistema")

    type = models.CharField("tipo", max_length=20, choices=Type.choices)
    # Valor em CENTAVOS, sempre > 0 (o sinal/convenção vem do tipo).
    amount = models.IntegerField("valor (centavos)")
    date = models.DateField("data")
    description = models.CharField("descrição", max_length=200, blank=True)
    account = models.ForeignKey(
        Account,
        on_delete=models.PROTECT,
        related_name="transactions",
        verbose_name="conta",
    )
    category = models.ForeignKey(
        Category,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="transactions",
        verbose_name="categoria",
    )
    merchant = models.ForeignKey(
        Merchant,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="transactions",
        verbose_name="estabelecimento",
    )
    normalized_description = models.CharField(
        "descrição normalizada",
        max_length=200,
        blank=True,
        default="",
        help_text="Derivada da descrição original; nunca substitui a original.",
    )
    transfer = models.ForeignKey(
        "finance.Transfer",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="transactions",
        verbose_name="transferência",
    )
    recurrence = models.ForeignKey(
        "finance.RecurringRule",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="transactions",
        verbose_name="recorrência",
    )
    card_purchase = models.ForeignKey(
        "cards.InstallmentPurchase",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="transactions",
        verbose_name="compra no cartão",
    )
    external_id = models.CharField(
        "identificador externo",
        max_length=128,
        blank=True,
        default="",
        help_text="Identificador de origem para importação/conciliação futura.",
    )
    source = models.CharField(
        "origem", max_length=20, choices=Source.choices, default=Source.MANUAL
    )
    is_reconciled = models.BooleanField("conciliada", default=False)
    reconciled_at = models.DateTimeField(
        "conciliada em", null=True, blank=True
    )
    notes = models.TextField("observações", blank=True)
    created_at = models.DateTimeField("criado em", auto_now_add=True)
    updated_at = models.DateTimeField("atualizado em", auto_now=True)

    class Meta:
        ordering = ["-date", "-id"]
        verbose_name = "transação"
        verbose_name_plural = "transações"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount__gt=0),
                name="finance_transaction_amount_gt_0",
            ),
        ]
        indexes = [
            models.Index(fields=["owner", "date"]),
            models.Index(fields=["owner", "account", "date"]),
            models.Index(fields=["external_id"]),
        ]

    def __str__(self):
        return f"{self.get_type_display()} {self.amount} ({self.date})"

    def clean(self):
        errors = {}
        if self.account and self.account.owner_id != self.owner_id:
            errors["account"] = "A conta deve pertencer ao mesmo usuário."
        if self.category and self.category.owner_id != self.owner_id:
            errors["category"] = "A categoria deve pertencer ao mesmo usuário."
        if (
            self.merchant_id
            and self.merchant.owner_id
            and self.merchant.owner_id != self.owner_id
        ):
            errors["merchant"] = (
                "O estabelecimento pessoal deve pertencer ao mesmo usuário."
            )
        if self.type == self.Type.ADJUSTMENT and not self.notes:
            errors["notes"] = "Ajustes exigem uma observação."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)


class Transfer(OwnedModel):
    """Transferência entre contas do mesmo usuário.

    Não é receita + despesa: gera duas pernas (out_transaction/in_transaction)
    de modo que o patrimônio total permaneça invariável (decisões D7).
    """

    from_account = models.ForeignKey(
        Account,
        on_delete=models.PROTECT,
        related_name="transfers_out",
        verbose_name="conta de origem",
    )
    to_account = models.ForeignKey(
        Account,
        on_delete=models.PROTECT,
        related_name="transfers_in",
        verbose_name="conta de destino",
    )
    amount = models.IntegerField("valor (centavos)")
    date = models.DateField("data")
    out_transaction = models.OneToOneField(
        Transaction,
        on_delete=models.PROTECT,
        related_name="transfer_out",
        null=True,
        blank=True,
        verbose_name="perna de saída",
    )
    in_transaction = models.OneToOneField(
        Transaction,
        on_delete=models.PROTECT,
        related_name="transfer_in",
        null=True,
        blank=True,
        verbose_name="perna de entrada",
    )
    notes = models.TextField("observações", blank=True)
    created_at = models.DateTimeField("criado em", auto_now_add=True)

    class Meta:
        verbose_name = "transferência"
        verbose_name_plural = "transferências"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount__gt=0),
                name="finance_transfer_amount_gt_0",
            ),
            models.CheckConstraint(
                condition=~models.Q(from_account=models.F("to_account")),
                name="finance_transfer_from_ne_to",
            ),
        ]

    def __str__(self):
        return f"{self.from_account} → {self.to_account} ({self.amount})"

    def clean(self):
        errors = {}
        if self.from_account and self.from_account.owner_id != self.owner_id:
            errors["from_account"] = "A conta de origem deve ser do mesmo usuário."
        if self.to_account and self.to_account.owner_id != self.owner_id:
            errors["to_account"] = "A conta de destino deve ser do mesmo usuário."
        if (
            self.from_account_id
            and self.from_account_id == self.to_account_id
        ):
            errors["to_account"] = "Origem e destino devem ser contas distintas."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)


class RecurringRule(OwnedModel):
    """Regra de recorrência (despesa ou receita).

    Funciona como REGRA DE GERAÇÃO/PROJEÇÃO, nunca gerando milhares de
    transações futuras no banco (decisão D8). Ocorrências são projetadas sob
    demanda e podem ser materializadas pontualmente em Transaction.
    """

    class Kind(models.TextChoices):
        EXPENSE = "expense", _("Despesa")
        INCOME = "income", _("Receita")

    class Frequency(models.TextChoices):
        WEEKLY = "weekly", _("Semanal")
        MONTHLY = "monthly", _("Mensal")
        YEARLY = "yearly", _("Anual")
        CUSTOM = "custom", _("Personalizado")

    class Status(models.TextChoices):
        ACTIVE = "active", _("Ativa")
        PAUSED = "paused", _("Pausada")
        ENDED = "ended", _("Encerrada")

    kind = models.CharField("tipo", max_length=20, choices=Kind.choices)
    title = models.CharField("título", max_length=120)
    amount = models.IntegerField("valor (centavos)")
    category = models.ForeignKey(
        Category,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="recurring_rules",
        verbose_name="categoria",
    )
    account = models.ForeignKey(
        Account,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="recurring_rules",
        verbose_name="conta",
    )
    card = models.ForeignKey(
        "cards.CreditCard",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="recurring_rules",
        verbose_name="cartão",
    )
    frequency = models.CharField(
        "frequência", max_length=20, choices=Frequency.choices,
        default=Frequency.MONTHLY,
    )
    interval = models.PositiveIntegerField("a cada (períodos)", default=1)
    start_date = models.DateField("data inicial")
    end_date = models.DateField(
        "data final", null=True, blank=True, help_text="Opcional; vazio = indefinida."
    )
    day_of_month = models.PositiveIntegerField(
        "dia do mês", null=True, blank=True, help_text="1 a 31 (usado em mensal)."
    )
    weekday = models.PositiveIntegerField(
        "dia da semana", null=True, blank=True, help_text="0=segunda ... 6=domingo."
    )
    status = models.CharField(
        "status", max_length=20, choices=Status.choices, default=Status.ACTIVE
    )
    next_run_date = models.DateField(
        "próxima ocorrência", null=True, blank=True
    )
    created_at = models.DateTimeField("criado em", auto_now_add=True)

    class Meta:
        ordering = ["title"]
        verbose_name = "recorrência"
        verbose_name_plural = "recorrências"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount__gt=0),
                name="finance_recurring_rule_amount_gt_0",
            ),
            models.CheckConstraint(
                condition=models.Q(interval__gte=1),
                name="finance_recurring_rule_interval_gte_1",
            ),
        ]

    def __str__(self):
        return f"{self.get_kind_display()}: {self.title} ({self.amount})"

    def clean(self):
        errors = {}
        if self.account and self.account.owner_id != self.owner_id:
            errors["account"] = "A conta deve ser do mesmo usuário."
        if self.card and self.card.owner_id != self.owner_id:
            errors["card"] = "O cartão deve ser do mesmo usuário."
        if self.category and self.category.owner_id != self.owner_id:
            errors["category"] = "A categoria deve ser do mesmo usuário."
        if self.kind == self.Kind.EXPENSE and not (self.account_id or self.card_id):
            errors["account"] = "Despesa recorrente exige conta ou cartão."
        if self.kind == self.Kind.INCOME and not self.account_id:
            errors["account"] = "Receita recorrente exige uma conta."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)


def format_cents(cents: int) -> Decimal:
    """Converte centavos (int) em Decimal de reais para exibição/operações."""
    return Decimal(cents) / Decimal(100)


class ClassificationRule(OwnedModel):
    """Regra personalizada/global de classificação (Ordem 18 — FASE 5).

    Representa uma condição determinística -> ação (categoria/subcategoria).

    Híbrida (como Merchant): ``owner IS NULL`` = regra GLOBAL (catálogo);
    ``owner`` definido = regra PESSOAL do usuário (isolada; maior precedência).

    Condições simples nesta fase (sem expressões complexas):
      - CONDITION_CONTAINS : condição textual (descrição contém `pattern`);
      - CONDITION_MERCHANT : quando o Merchant identificado == `merchant`.
    Ação: ``category`` (categoria/subcategoria da taxonomia FASE 3).
    """

    class ConditionType(models.TextChoices):
        CONTAINS = "contains", _("Descrição contém")
        MERCHANT = "merchant", _("Merchant")

    class Kind(models.TextChoices):
        EXPENSE = "expense", _("Despesa")
        INCOME = "income", _("Receita")
        ANY = "any", _("Qualquer")

    name = models.CharField("nome", max_length=120)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="classification_rules",
        verbose_name="proprietário (null = global)",
    )
    condition_type = models.CharField(
        "tipo de condição", max_length=20, choices=ConditionType.choices,
        default=ConditionType.CONTAINS,
    )
    pattern = models.CharField("padrão", max_length=200, blank=True, default="")
    merchant = models.ForeignKey(
        Merchant,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="classification_rules",
        verbose_name="estabelecimento",
    )
    category = models.ForeignKey(
        Category,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="classification_rules",
        verbose_name="categoria (ação)",
    )
    category_name = models.CharField(
        "nome da categoria (ação)",
        max_length=120,
        blank=True,
        default="",
        help_text="Nome (raiz/subcategoria) da taxonomia a classificar; resolvido "
        "para a categoria real do usuário em tempo de execução.",
    )
    kind = models.CharField(
        "tipo de movimentação", max_length=10, choices=Kind.choices, default=Kind.ANY
    )
    priority = models.PositiveIntegerField("prioridade", default=100)
    is_active = models.BooleanField("ativa", default=True)
    source = models.CharField("origem", max_length=20, default="user")
    created_at = models.DateTimeField("criado em", auto_now_add=True)
    updated_at = models.DateTimeField("atualizado em", auto_now=True)

    objects = CatalogManager()

    class Meta:
        ordering = ["priority", "name"]
        verbose_name = "regra de classificação"
        verbose_name_plural = "regras de classificação"
        indexes = [
            models.Index(fields=["owner", "is_active", "priority"]),
        ]

    def __str__(self):
        return self.name or "(sem nome)"

    @property
    def is_global(self):
        return self.owner_id is None

    def clean(self):
        errors = {}
        if self.owner_id and self.category and self.category.owner_id != self.owner_id:
            errors["category"] = "A categoria deve pertencer ao mesmo usuário."
        if not self.category_id and not (self.category_name or "").strip():
            errors["category_name"] = "Informe a categoria/subcategoria da ação."
        if self.condition_type == self.ConditionType.CONTAINS and not self.pattern.strip():
            errors["pattern"] = "Informe o texto da condição."
        if self.condition_type == self.ConditionType.MERCHANT and not self.merchant_id:
            errors["merchant"] = "Selecione o estabelecimento."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def matches(self, *, merchant_id=None, normalized_description=""):
        """Avalia a condição (determinística)."""
        if not self.is_active:
            return False
        if self.condition_type == self.ConditionType.CONTAINS:
            pat = self.pattern.strip().upper()
            return bool(pat) and pat in (normalized_description or "").upper()
        if self.condition_type == self.ConditionType.MERCHANT:
            return bool(merchant_id) and self.merchant_id == merchant_id
        return False


class UserPreference(OwnedModel):
    """Memória determinística de aprendizado por correção (Ordem 18 — FASE 5).

    Cada linha associa uma ``key`` (impressão digital normalizada de uma
    descrição/estabelecimento) à categoria que o usuário escolheu ao corrigir.

    - determinística e explicável (a ``key`` é auditável);
    - por usuário e isolada (owner);
    - reversível (ao apagar a linha, o aprendizado some);
    - ``count`` reflete quantas vezes o usuário confirmou/corrigiu essa chave,
      fortalecendo (não inventando) a confiança.
    """

    key = models.CharField("chave", max_length=200)
    category = models.ForeignKey(
        Category,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="preferences",
        verbose_name="categoria (escolhida)",
    )
    merchant = models.ForeignKey(
        Merchant,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="preferences",
        verbose_name="estabelecimento",
    )
    kind = models.CharField("tipo", max_length=10, choices=Category.Kind.choices, default=Category.Kind.EXPENSE)
    confidence = models.DecimalField("confiança", max_digits=4, decimal_places=3, default=Decimal("0.90"))
    count = models.PositiveIntegerField("confirmações", default=1)
    last_corrected_at = models.DateTimeField("última correção", auto_now=True)

    class Meta:
        ordering = ["-count", "key"]
        verbose_name = "preferência do usuário"
        verbose_name_plural = "preferências do usuário"
        constraints = [
            models.UniqueConstraint(
                fields=["owner", "key"],
                name="finance_userpreference_unique_owner_key",
            ),
        ]
        indexes = [
            models.Index(fields=["owner", "key"]),
        ]

    def __str__(self):
        return f"{self.key} -> {self.category}"


class TransactionAnalysis(OwnedModel):
    """Decisão de classificação persistida para uma Transaction (FASE 5 §14).

    Snapshot 1:1 com a Transaction, auditável e independente de renomeação de
    Category: guardamos também os NOMES de categoria/subcategoria na época da
    decisão (FASE 3 ajuste D4).

    A decisão é persistida de forma EXPLÍCITA (não presa em metadata):
      - confiança numérica (regra objetiva);
      - método/origem (classification_source);
      - regra responsável (rule);
      - Merchant utilizado (merchant);
      - necessidade de revisão humana (needs_review) e correção do usuário.
    """

    class Source(models.TextChoices):
        USER_CORRECTION = "user_correction", _("Correção do usuário")
        USER_RULE = "user_rule", _("Regra do usuário")
        MERCHANT = "merchant", _("Merchant conhecido")
        ALIAS = "alias", _("Alias conhecido")
        HISTORY = "history", _("Histórico do usuário")
        GLOBAL_RULE = "global_rule", _("Regra global")
        CONTEXT = "context", _("Contexto")
        MANUAL = "manual", _("Manual")
        MOVEMENT = "movement", _("Movimentação (não consumo)")
        NATURE = "nature", _("Natureza da transação (agnóstica de banco)")
        SUGGESTED = "suggested", _("Categoria sugerida pelo cliente/arquivo")
        SEMANTIC = "semantic", _("Classificador semântico (opcional)")
        NONE = "none", _("Sem evidência")

    transaction = models.OneToOneField(
        Transaction,
        on_delete=models.CASCADE,
        related_name="analysis",
        verbose_name="transação",
    )
    category = models.ForeignKey(
        Category,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="analyses",
        verbose_name="categoria (FK)",
    )
    category_name = models.CharField("nome da categoria", max_length=120, blank=True, default="")
    subcategory_name = models.CharField("nome da subcategoria", max_length=120, blank=True, default="")
    merchant = models.ForeignKey(
        Merchant,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="analyses",
        verbose_name="estabelecimento",
    )
    rule = models.ForeignKey(
        ClassificationRule,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="analyses",
        verbose_name="regra aplicada",
    )
    normalized_description = models.CharField("descrição normalizada", max_length=200, blank=True, default="")
    confidence = models.DecimalField("confiança", max_digits=4, decimal_places=3, default=Decimal("0"))
    classification_source = models.CharField(
        "origem da decisão", max_length=30, choices=Source.choices, default=Source.NONE
    )
    mcc = models.CharField("código do comércio", max_length=8, blank=True, default="")

    needs_review = models.BooleanField("precisa de revisão", default=False)
    reviewed_at = models.DateTimeField("revisto em", null=True, blank=True)
    user_corrected = models.BooleanField("corrigida pelo usuário", default=False)
    is_movement = models.BooleanField("movimentação (não consumo)", default=False)
    created_at = models.DateTimeField("criado em", auto_now_add=True)
    updated_at = models.DateTimeField("atualizado em", auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "análise de transação"
        verbose_name_plural = "análises de transação"
        indexes = [
            models.Index(fields=["owner", "classification_source"]),
            models.Index(fields=["needs_review"]),
        ]

    def __str__(self):
        return f"[{self.classification_source}] {self.category_name} ({self.confidence})"
