"""Orquestração da camada de importação.

Responsabilidades:
  - despachar o parser correto (CSV/OFX/XLSX) por tipo de arquivo;
  - ingerir os dados: criar o `ImportBatch` (rastreabilidade) e as linhas de
    staging (`StagedTransaction`) — NUNCA registros financeiros definitivos;
  - descartar o conteúdo bruto do arquivo após processamento (privacidade).

A criação dos registros financeiros definitivos fica a cargo da camada de
confirmação (`commit.py`), que usa os services financeiros existentes.
"""

from secrets import token_hex
from typing import List, Optional

from django.db import transaction

from ..models import ImportBatch, StagedTransaction
from . import classify, duplicates, importer_registry
from .normalized import NormalizedTransaction


def parse_file(file_type: str, content: bytes) -> List[NormalizedTransaction]:
    """Despacha para o parser adequado e devolve movimentações normalizadas."""
    return importer_registry.parse(file_type, content)


def _next_batch_id() -> str:
    n = ImportBatch.objects.count() + 1
    return f"IMP{n:05d}-{token_hex(2).upper()}"


@transaction.atomic
def ingest(
    *,
    user,
    file_type: str,
    file_name: str,
    content: bytes,
    default_account=None,
    card=None,
    import_type="account",
) -> ImportBatch:
    """Processa o upload e cria o lote + linhas de staging em uma transação.

    Após processar, o conteúdo em memória não é persistido em disco — apenas
    metadados do arquivo são guardados no ImportBatch (privacidade: nada de
    manter o arquivo financeiro sensível indefinidamente).

    Retorna o ImportBatch com as linhas de staging criadas.

    Quando ``import_type == "card"`` e ``card`` é informado, o fluxo é DIFERENTE:
    em vez de staging para revisão, as compras do cartão são criadas diretamente
    como ``InstallmentPurchase`` (à vista ou parceladas) — sem ingressar no razão
    de contas (a saída real só ocorre no pagamento da fatura).
    """
    if file_type not in dict(ImportBatch.FileType.choices):
        raise ValueError(f"Tipo de arquivo não suportado: {file_type}")

    is_card = import_type == "card" and card is not None

    batch = ImportBatch.objects.create(
        owner=user,
        batch_id=_next_batch_id(),
        file_type=file_type,
        file_name=file_name or "",
        original_file_name=file_name or "",
        status=ImportBatch.Status.PROCESSING,
    )

    try:
        parsed = parse_file(file_type, content)
    except Exception as exc:
        batch.status = ImportBatch.Status.FAILED
        batch.error_detail = str(exc)[:2000]
        batch.save()
        raise

    if not parsed:
        batch.status = ImportBatch.Status.FAILED
        batch.error_detail = "Nenhuma movimentação reconhecida no arquivo."
        batch.save()
        raise ValueError("Nenhuma movimentação reconhecida no arquivo.")

    # ====================== FLUXO CARTÃO ======================
    if is_card:
        from ...cards.models import InstallmentPurchase
        from ...cards.services.purchases import create_card_purchase
        from .installment_detector import detect_installment

        created = 0
        errors = 0
        error_detail = ""
        for item in parsed:
            if item.direction != "expense":
                # compras no cartão são sempre despesa (não ignora créditos de nubank/estorno)
                continue
            try:
                info = detect_installment(item.description)
                count = info.total_count if info else 1
                create_card_purchase(
                    user=user,
                    card=card,
                    description=item.description,
                    total_amount=item.amount_cents,
                    installment_count=count,
                    first_due_date=item.date,
                )
                created += 1
            except Exception as exc:
                errors += 1
                error_detail = str(exc)[:500]

        batch.detected_count = len(parsed)
        batch.imported_count = created
        batch.pending_count = 0
        batch.ignored_count = 0
        batch.error_count = errors
        batch.status = ImportBatch.Status.COMMITTED
        batch.error_detail = error_detail
        batch.save()
        return batch

    # ====================== FLUXO CONTA (staging) ======================
    # classificação + detecção de duplicidade
    candidates = duplicates.detect(user, parsed, batch)

    rows = []
    for item in candidates:
        metadata = dict(item.metadata or {})
        if item.merchant_method:
            metadata["merchant_method"] = item.merchant_method
            metadata["merchant_confidence"] = item.merchant_confidence
        if item.metadata.get("classification_method"):
            metadata["classification_method"] = item.metadata["classification_method"]
            metadata["classification_confidence"] = item.metadata["classification_confidence"]
            metadata["classification_needs_review"] = item.metadata["classification_needs_review"]
        rows.append(
            StagedTransaction(
                owner=user,
                batch=batch,
                source_id=item.source_id,
                external_id=item.external_id or item.source_id,
                date=item.date,
                description=item.description,
                original_description=item.original_description or item.description,
                normalized_description=item.normalized_description,
                amount_cents=item.amount_cents,
                direction=item.direction,
                default_account=default_account,
                category=item.category,
                merchant=item.merchant,
                confidence=item.confidence,
                row_status=item.row_status,
                duplicate_of=item.duplicate_of,
                skip_reason=item.skip_reason,
                metadata=metadata,
            )
        )
    if rows:
        StagedTransaction.objects.bulk_create(rows)

    detected = len(parsed)
    n_high = sum(1 for r in rows if r.confidence == StagedTransaction.Confidence.HIGH)
    n_dup = sum(1 for r in rows if r.confidence == StagedTransaction.Confidence.DUPLICATE)
    batch.detected_count = detected
    batch.imported_count = 0
    batch.pending_count = detected - n_dup
    batch.ignored_count = n_dup
    batch.status = ImportBatch.Status.READY
    batch.save()

    return batch
