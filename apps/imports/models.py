"""Modelos de STAGING da camada de importação.

DECISÃO DE ARQUITETURA (Ordem 17): esta app é uma CAMADA DE ENTRADA DE DADOS.
Estes models NÃO representam registros financeiros definitivos — eles NUNCA
entram no razão (ledger). São apenas a área temporária de revisão.

- ``ImportBatch``   : rastreabilidade do lote (histórico da importação).
- ``StagedTransaction`` : uma movimentação detectada no arquivo, ainda NÃO
  confirmada. Só vira Transaction real no fluxo de confirmação, que DELEGA a
  criação aos services financeiros existentes.

Isolamento multiusuário é garantido herdando ``OwnedModel`` (apps.core.ownership)
— o mesmo mecanismo usado por todos os models do projeto.
"""

from django.conf import settings
from django.db import models

from apps.core.ownership import OwnedModel


class ImportBatch(OwnedModel):
    """Histórico de um lote de importação (rastreabilidade).

    Serve para responder "de onde veio esta informação?" e registrar o ciclo
    de vida do arquivo (que é descartado após o processamento, ver views).
    """

    class FileType(models.TextChoices):
        CSV = "csv", "CSV"
        OFX = "ofx", "OFX"
        XLSX = "xlsx", "XLSX"

    class Status(models.TextChoices):
        PROCESSING = "processing", "Processando"
        READY = "ready", "Pronto para revisão"
        COMMITTED = "committed", "Confirmado"
        DISCARDED = "discarded", "Descartado"
        FAILED = "failed", "Falhou"

    batch_id = models.CharField("identificador do lote", max_length=24, unique=True)
    file_type = models.CharField("tipo de arquivo", max_length=10, choices=FileType.choices)
    file_name = models.CharField("nome do arquivo", max_length=255, blank=True, default="")
    # O arquivo é temporário: após o processamento NÃO é mantido de forma
    # indefinida (ver camada de views). Guardamos apenas metadados.
    original_file_name = models.CharField("arquivo original", max_length=255, blank=True, default="")

    detected_count = models.PositiveIntegerField("detectadas", default=0)
    imported_count = models.PositiveIntegerField("importadas", default=0)
    ignored_count = models.PositiveIntegerField("ignoradas", default=0)
    pending_count = models.PositiveIntegerField("pendentes", default=0)
    error_count = models.PositiveIntegerField("com erro", default=0)

    status = models.CharField("status", max_length=20, choices=Status.choices, default=Status.PROCESSING)
    error_detail = models.TextField("detalhe do erro", blank=True, default="")

    created_at = models.DateTimeField("criado em", auto_now_add=True)
    committed_at = models.DateTimeField("confirmado em", null=True, blank=True)

    class Meta:
        verbose_name = "Lote de importação"
        verbose_name_plural = "Lotes de importação"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "created_at"]),
        ]

    def __str__(self):
        return f"{self.batch_id} · {self.file_type} · {self.status}"


class StagedTransaction(OwnedModel):
    """Movimentação detectada no arquivo, em revisão (ainda NÃO confirmada).

    Conforme a Ordem 17, nunca criamos transações financeiras definitivas
    imediatamente após o upload. Esta linha só se torna um Transaction real
    no fluxo de confirmação, através dos services financeiros existentes.

    Os valores são inteiros em centavos (`amount_cents > 0`), respeitando a
    convenção D10. A direção é capturada em ``direction`` (income/expense) e o
    sinal SEMPRE vem do tipo, nunca do valor.
    """

    class Direction(models.TextChoices):
        INCOME = "income", "Receita"
        EXPENSE = "expense", "Despesa"

    class Confidence(models.TextChoices):
        HIGH = "high", "Alta confiança"
        REVIEW = "review", "Precisa de revisão"
        DUPLICATE = "duplicate", "Possível duplicada"

    class RowStatus(models.TextChoices):
        READY = "ready", "Pronta"
        REVIEW = "review", "Em revisão"
        IGNORED = "ignored", "Ignorada"
        IMPORTED = "imported", "Importada"
        ERROR = "error", "Erro"

    batch = models.ForeignKey(
        ImportBatch, on_delete=models.CASCADE, related_name="staged_rows"
    )
    # Identificador de origem do arquivo (quando disponível — ex.: FITID do OFX).
    source_id = models.CharField("id de origem", max_length=128, blank=True, default="")
    external_id = models.CharField("id externo", max_length=128, blank=True, default="")

    date = models.DateField("data")
    description = models.CharField("descrição", max_length=200, blank=True, default="")
    original_description = models.CharField("descrição original", max_length=200, blank=True, default="")
    normalized_description = models.CharField(
        "descrição normalizada", max_length=200, blank=True, default=""
    )
    amount_cents = models.PositiveIntegerField("valor (centavos)")
    direction = models.CharField("direção", max_length=10, choices=Direction.choices)

    # Referências preenchidas na revisão/confirmação (never definitive here).
    category = models.ForeignKey(
        "finance.Category", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="staged_transactions",
    )
    merchant = models.ForeignKey(
        "finance.Merchant", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="staged_transactions",
    )
    default_account = models.ForeignKey(
        "finance.Account", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="staged_transactions_default",
    )

    confidence = models.CharField("confiança", max_length=10, choices=Confidence.choices, default=Confidence.HIGH)
    row_status = models.CharField("status da linha", max_length=10, choices=RowStatus.choices, default=RowStatus.READY)
    duplicate_of = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="duplicate_candidates",
    )
    skip_reason = models.CharField("motivo de descarte", max_length=120, blank=True, default="")

    metadata = models.JSONField("metadados", default=dict, blank=True)

    created_at = models.DateTimeField("criado em", auto_now_add=True)

    class Meta:
        verbose_name = "Movimentação em revisão"
        verbose_name_plural = "Movimentações em revisão"
        ordering = ["date", "id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount_cents__gt=0),
                name="imports_staged_amount_gt_0",
            ),
        ]
        indexes = [
            models.Index(fields=["batch", "row_status"]),
            models.Index(fields=["owner", "external_id"]),
        ]

    def __str__(self):
        return f"{self.date} · {self.direction} · {self.amount_cents}"
