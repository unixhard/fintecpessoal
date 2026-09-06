"""Classificação e backfill de transações existentes (Ordem 18 — FASE 7).

Abrange o "motor antes da Transaction" (FASE 5, staging) e a aplicação
retroativa a transações já criadas sem análise. É SEMPRE não destrutivo:

  - NÃO sobrescreve correção explícita do usuário (user_corrected);
  - NÃO altera accounting core nem double-count (transferências/movimentos
    ficam com análise ::is_movement, sem virar consumo);
  - só cria/atualiza o snapshot TransactionAnalysis e preenche ``category``
    quando ainda ausente.

Sem IA por transação (regra §13): o backfill é totalmente determinístico.
"""

from django.db.models import Q

from ..models import Transaction, TransactionAnalysis
from .classifier import apply_classification, classify_transaction


def classify_and_apply(user, transaction) -> TransactionAnalysis:
    """Classifica uma Transaction e aplica/persiste a decisão (§14).

    Respeita correção do usuário: se já há análise com user_corrected, não
    sobrepõe (retorna a análise existente).
    """
    existing = getattr(transaction, "analysis", None)
    if existing is not None and existing.user_corrected:
        return existing
    result = classify_transaction(user, transaction)
    return apply_classification(user, transaction, result)


def backfill_missing(user, *, limit: int = 0) -> int:
    """Aplica o motor a transações do usuário que ainda não têm análise.

    Não toca transações com análise marcada como correção do usuário.
    ``limit=0`` processa todas. Retorna o número de análises criadas.
    """
    qs = (
        Transaction.objects.for_user(user)
        .filter(
            Q(analysis__isnull=True),
            type__in=(Transaction.Type.INCOME, Transaction.Type.EXPENSE),
        )
        .select_related("account", "merchant")
        .order_by("date", "id")
    )
    if limit:
        qs = qs[:limit]

    counter = 0
    for tx in qs:
        classify_and_apply(user, tx)
        counter += 1
    return counter


def pending_review(user, *, category=None) -> list:
    """Análises do usuário que precisam de revisão humana (FASE 9).

    Inclui análise inexistente com transação ainda sem categoria (sem decisão).
    """
    from ..models import Category as Cat

    if category is not None:
        analysis = (
            TransactionAnalysis.objects.for_user(user)
            .filter(needs_review=True, category=category)
            .select_related("transaction", "merchant", "category", "rule")
            .order_by("transaction__date")
        )
        return list(analysis)
    analysis = (
        TransactionAnalysis.objects.for_user(user)
        .filter(needs_review=True)
        .select_related("transaction", "merchant", "category", "rule")
        .order_by("transaction__date")
    )
    uncat = (
        Transaction.objects.for_user(user)
        .filter(analysis__isnull=True, category__isnull=True)
        .select_related("account", "merchant")
        .order_by("date")
    )
    return list(analysis) + list(uncat)


def review_count(user) -> int:
    """Número de análises pendentes de revisão (sem contar duplicados)."""
    return (
        TransactionAnalysis.objects.for_user(user).filter(needs_review=True).count()
    ) + (
        Transaction.objects.for_user(user)
        .filter(analysis__isnull=True, category__isnull=True)
        .count()
    )
