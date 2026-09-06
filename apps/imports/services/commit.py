"""Confirmação da importação: cria registros financeiros REAIS.

Regra da Ordem 17: a criação definitiva é DELEGADA aos services financeiros
existentes (record_income / record_expense). Este módulo apenas VALIDA, resolve
categoria/contas e orquestra a confirmação em lote de forma atômica.

- Nenhum registro definitivo é criado antes desta confirmação.
- Toda a operação roda em um único ``transaction.atomic`` (rollback total em erro).
- Rows ignoradas (possível duplicidade) NÃO são reimportadas.
- Reusa o ``external_id``/``source`` para rastreabilidade e anti-duplicação.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional

from django.db import transaction
from django.utils import timezone

from ...finance.models import Account, Category, Transaction
from ...finance.services.categories import create_category
from ...finance.services.classifier import extract_card_name
from ...finance.services.transactions import record_expense, record_income
from ...finance.services.transfers import transfer_between
from ..models import ImportBatch, StagedTransaction

_SOURCE_BY_TYPE = {
    ImportBatch.FileType.CSV: Transaction.Source.IMPORTED_CSV,
    ImportBatch.FileType.OFX: Transaction.Source.IMPORTED_OFX,
    ImportBatch.FileType.XLSX: Transaction.Source.IMPORTED_CSV,
}


class CommitError(ValueError):
    pass


def _resolve_account(user, staged: StagedTransaction) -> Optional[Account]:
    account = staged.default_account
    if account is None or account.owner_id != user.id:
        return None
    return account


def _resolve_or_create_card_account(user, card_name: str) -> Account:
    """Obtém ou cria uma conta tipo CREDIT_CARD para o cartão informado.

    Busca por conta ativa com nome contendo ``card_name`` (case-insensitive).
    Se não encontrar, cria uma nova automaticamente.
    """
    if not card_name:
        return None
    existing = (
        Account.objects.for_user(user)
        .filter(
            name__icontains=card_name,
            type=Account.Type.CREDIT_CARD,
            status=Account.Status.ACTIVE,
        )
        .first()
    )
    if existing:
        return existing
    return Account.objects.create(
        owner=user,
        name=card_name,
        type=Account.Type.CREDIT_CARD,
        institution=card_name,
    )


def _resolve_category(user, staged: StagedTransaction, category_name: str) -> Optional[Category]:
    kind = (
        Category.Kind.INCOME
        if staged.direction == StagedTransaction.Direction.INCOME
        else Category.Kind.EXPENSE
    )
    # usa a categoria já vinculada à linha
    if staged.category is not None and staged.category.owner_id == user.id:
        return staged.category
    # cria/obtém a categoria sugerida pela classificação
    if category_name:
        existing = (
            Category.objects.for_user(user)
            .filter(name__iexact=category_name, kind=kind, status=Category.Status.ACTIVE)
            .first()
        )
        if existing:
            return existing
        return create_category(user=user, name=category_name, kind=kind)
    return None


@dataclass
class CommitResult:
    imported: int = 0
    pending: int = 0
    ignored: int = 0
    errors: int = 0
    error_messages: List[str] = None

    def __post_init__(self):
        if self.error_messages is None:
            self.error_messages = []


@transaction.atomic
def commit_batch(*, user, batch: ImportBatch, account=None, categories: Optional[Dict[int, str]] = None) -> CommitResult:
    """Confirma um lote de staging criando os registros reais.

    ``categories``: mapeamento opcional {staged_pk: category_name} aplicado
    antes da confirmação (vindo da tela de revisão). ``account`` define a conta
    padrão para linhas sem conta vinculada.
    """
    rows = list(
        batch.staged_rows.select_related("category", "default_account").order_by("date", "id")
    )
    source = _SOURCE_BY_TYPE.get(batch.file_type, Transaction.Source.SYSTEM)
    result = CommitResult()

    # validate account ownership once
    account = _validate_user_account(user, account)

    # Aprendizado intra-lote: quando o usuário corrige UMA linha de uma
    # descrição, todas as OUTRAS linhas do mesmo lote com a MESMA descrição
    # normalizada (mesma direção) herdam a categoria automaticamente. Assim
    # uma única confirmação cobre centenas de recorrências sem fricção.
    if categories:
        categories = _propagate_user_picks(user, rows, categories)

    for staged in rows:
        # nunca reimportar o que já foi confirmado ou marcado como ignorado
        if staged.row_status in (
            StagedTransaction.RowStatus.IMPORTED,
            StagedTransaction.RowStatus.IGNORED,
        ):
            continue

        # anti-duplicação por external_id no razão (nunca duplicar acidentalmente)
        if staged.external_id:
            exists = Transaction.objects.for_user(user).filter(
                external_id=staged.external_id
            ).exists()
            if exists:
                _skip(staged, "Já existe lançamento com este identificador externo.")
                result.ignored += 1
                continue

        effective_account = _resolve_account(user, staged) or account
        if effective_account is None:
            _skip(staged, "Defina uma conta para esta linha.")
            result.pending += 1
            continue

        cat_name = None
        if categories:
            cat_name = categories.get(str(staged.pk))
        category = _resolve_category(user, staged, cat_name)

        # Roteamento de pagamento de fatura: se a categoria é
        # "Transferência para cartão", cria uma transferência em vez de despesa.
        # Isso evita dupla contabilidade (a despesa real acontece na compra do
        # cartão, não no pagamento da fatura).
        is_fatura_transfer = (
            category is not None
            and category.name == "Transferência para cartão"
            and staged.direction == StagedTransaction.Direction.EXPENSE
        )

        try:
            if is_fatura_transfer:
                card_name = extract_card_name(staged.description) or "Cartão"
                to_account = _resolve_or_create_card_account(user, card_name)
                transfer = transfer_between(
                    user=user,
                    from_account=effective_account,
                    to_account=to_account,
                    amount=staged.amount_cents,
                    date=staged.date,
                    notes=f"Pagamento fatura — {card_name}",
                    source=source,
                )
                tx_obj = None
            elif staged.direction == StagedTransaction.Direction.INCOME:
                tx_obj = record_income(
                    user=user,
                    account=effective_account,
                    amount=staged.amount_cents,
                    date=staged.date,
                    description=staged.description,
                    category=category,
                    source=source,
                    external_id=staged.external_id or "",
                    merchant=staged.merchant,
                    normalized_description=staged.normalized_description,
                )
            else:
                tx_obj = record_expense(
                    user=user,
                    account=effective_account,
                    amount=staged.amount_cents,
                    date=staged.date,
                    description=staged.description,
                    category=category,
                    source=source,
                    external_id=staged.external_id or "",
                    merchant=staged.merchant,
                    normalized_description=staged.normalized_description,
                )
            # Aprende quando o usuário escolheu a categoria manualmente
            # (inputs do review) — popula UserPreference para próximas imports.
            user_picked = bool(cat_name and categories and str(staged.pk) in categories)
            _write_analysis(user, tx_obj, staged, user_corrected=user_picked)
        except Exception as exc:  # rollback da linha
            _skip(staged, f"Erro ao criar: {exc}")
            result.errors += 1
            result.error_messages.append(str(exc))
            continue

        staged.row_status = StagedTransaction.RowStatus.IMPORTED
        staged.save(update_fields=["row_status"])
        result.imported += 1

    _finalize(batch, result)
    return result


def _validate_user_account(user, account):
    if account is None:
        return None
    if not isinstance(account, Account) or account.owner_id != user.id:
        raise CommitError("Conta inválida ou não pertence ao usuário.")
    return account


def _propagate_user_picks(user, rows, categories: Dict[int, str]):
    """Propaga a categoria escolhida pelo usuário para outras linhas iguais.

    Se o usuário corrigir a categoria de UMA linha com determinada descrição
    normalizada, todas as demais linhas do lote com a MESMA descrição (mesma
    direção) que ainda estejam em revisão recebem a MESMA categoria. Isso reduz
    drasticamente a revisão manual em extratos com muitas repetições.

    Retorna o novo ``categories`` já enriquecido (mantém as escolhas explícitas).
    """
    # 1) Índice das escolhas explícitas por (normalized, direction).
    picks = {}  # (normalized_upper, direction) -> dict(line), usado p/ resolver
    explicit = list(categories) if isinstance(categories, (dict, list)) else []
    for staged in rows:
        cat_name = categories.get(str(staged.pk))
        if not cat_name or not staged.normalized_description:
            continue
        key = (staged.normalized_description.upper(), staged.direction)
        picks.setdefault(key, cat_name)

    if not picks:
        return categories

    # 2) Para cada linha sem escolha explícita, aplica a categoria herdada.
    enriched = dict(categories)
    for staged in rows:
        if str(staged.pk) in enriched or not staged.normalized_description:
            continue
        if staged.category is not None and staged.category.owner_id == user.id:
            continue
        if staged.row_status not in (
            StagedTransaction.RowStatus.READY,
            StagedTransaction.RowStatus.REVIEW,
        ):
            continue
        key = (staged.normalized_description.upper(), staged.direction)
        if key in picks:
            enriched[str(staged.pk)] = picks[key]
    return enriched


def _skip(staged: StagedTransaction, reason: str):
    staged.row_status = StagedTransaction.RowStatus.IGNORED
    staged.skip_reason = reason
    staged.save(update_fields=["row_status", "skip_reason"])


def _write_analysis(user, tx_obj, staged: StagedTransaction, *, user_corrected=False):
    """Persiste o snapshot 1:1 da decisão de classificação (FASE 5 §14).

    Reutiliza o resultado já calculado na etapa de staging (método e confiança
    guardados em ``metadata``) — não recalcula nem consome recursos extras.

    Quando ``user_corrected=True``, também aprende na memória determinística
    (UserPreference) para que a próxima importação classifique automaticamente.
    """
    if tx_obj is None:
        return None
    from ...finance.services.classifier import ClassificationResult, record_analysis

    md = staged.metadata or {}
    method = md.get("classification_method") or ""
    conf_raw = md.get("classification_confidence") or "0"
    from decimal import Decimal

    try:
        confidence = Decimal(str(conf_raw))
    except Exception:
        confidence = Decimal("0")
    needs_review = bool(md.get("classification_needs_review"))

    # Reconstrói o resultado para persistência fiel ao cálculo original.
    from ...finance.models import TransactionAnalysis

    cat = staged.category if (staged.category and staged.category.owner_id == user.id) else tx_obj.category
    result = ClassificationResult(
        category=cat,
        category_name=cat.parent.name if (cat and cat.parent_id) else (cat.name if cat else ""),
        subcategory_name=cat.name if (cat and cat.parent_id) else "",
        merchant=staged.merchant or tx_obj.merchant,
        confidence=confidence,
        method=method or TransactionAnalysis.Source.NONE,
        needs_review=needs_review,
        normalized_description=staged.normalized_description or "",
    )

    if user_corrected and cat and cat.owner_id == user.id:
        result.method = TransactionAnalysis.Source.USER_CORRECTION
        result.confidence = Decimal("0.97")
        result.needs_review = False

    record = record_analysis(user, tx_obj, result, user_corrected=user_corrected)

    if user_corrected and cat and cat.owner_id == user.id:
        from ...finance.services.memory import learn
        from ...finance.models import Category

        kind = (
            Category.Kind.INCOME
            if tx_obj.type == "income"
            else Category.Kind.EXPENSE
        )
        normalized = staged.normalized_description or (
            tx_obj.description or ""
        )[:120]
        learn(
            user=user,
            key=normalized,
            category=cat,
            merchant=staged.merchant or tx_obj.merchant,
            kind=kind,
        )

    return record


def _finalize(batch: ImportBatch, result: CommitResult):
    from django.db.models import Count, Q

    counts = batch.staged_rows.aggregate(
        imported=Count("id", filter=Q(row_status=StagedTransaction.RowStatus.IMPORTED)),
        pending=Count("id", filter=Q(row_status=StagedTransaction.RowStatus.REVIEW)),
        ignored=Count("id", filter=Q(row_status=StagedTransaction.RowStatus.IGNORED)),
        errors=Count("id", filter=Q(row_status=StagedTransaction.RowStatus.ERROR)),
    )
    batch.imported_count = counts["imported"] or 0
    batch.pending_count = counts["pending"] or 0
    batch.ignored_count = counts["ignored"] or 0
    batch.error_count = counts["errors"] or 0
    batch.status = ImportBatch.Status.COMMITTED
    batch.committed_at = timezone.now()
    batch.save()

    result.imported = batch.imported_count
    result.pending = batch.pending_count
    result.ignored = batch.ignored_count
    result.errors = batch.error_count
