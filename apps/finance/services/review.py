"""Fila de revisão humana e correção em massa (Ordem 18 — FASE 9).

Reúne as consultas de pendências (transações sem decisão confiável) e a ação
de correção em lote, sempre com isolamento multiusuário e ordem de aprendizado
do usuário (FASE 5 §4). Nada aqui altera accounting core.
"""

from ..models import Transaction, TransactionAnalysis
from .backfill import pending_review, review_count
from .classifier import apply_user_correction


def pending(user, *, category=None, limit=100):
    """Transações do usuário que precisam de revisão (decisão de baixa confiança)."""
    return pending_review(user, category=category)[:limit]


def stats(user) -> dict:
    """Resumo para a tela de inteligência/revisão."""
    return {
        "needs_review": review_count(user),
        "with_analysis": TransactionAnalysis.objects.for_user(user).count(),
        "uncategorized": (
            Transaction.objects.for_user(user)
            .filter(analysis__isnull=True, category__isnull=True)
            .count()
        ),
        "corrected": TransactionAnalysis.objects.for_user(user).filter(user_corrected=True).count(),
    }


def bulk_correct(*, user, corrections) -> dict:
    """Aplica corrreções em lote.

    ``corrections``: iterável de dicts {"transaction_id": int, "category_id": int}.
    Valida ownership de TODAS antes de aplicar qualquer (transação e categoria
    devem pertencer ao usuário). É atômico-ish por item; retorna resumo.

    Retorna {"applied": n, "errors": [...]}.
    """
    from django.db import transaction as db_transaction

    tx_ids = [int(c["transaction_id"]) for c in corrections]
    cat_ids = {int(c["category_id"]) for c in corrections}

    tx_qs = list(Transaction.objects.for_user(user).filter(pk__in=tx_ids))
    tx_map = {t.id: t for t in tx_qs}
    cat_map = {
        c.id: c
        for c in _categories_for(user, cat_ids)
    }

    missing_tx = set(tx_ids) - set(tx_map)
    missing_cat = cat_ids - set(cat_map)
    applied = 0
    errors = []
    if missing_tx:
        errors.append(f"Transações não encontradas: {sorted(missing_tx)}")
    if missing_cat:
        errors.append(f"Categorias não encontradas ou de outro usuário: {sorted(missing_cat)}")

    for c in corrections:
        tx = tx_map.get(int(c["transaction_id"]))
        cat = cat_map.get(int(c["category_id"]))
        if tx is None or cat is None:
            continue
        with db_transaction.atomic():
            apply_user_correction(user=user, transaction=tx, category=cat)
        applied += 1

    return {"applied": applied, "errors": errors}


def _categories_for(user, ids):
    from ..models import Category

    return list(Category.objects.for_user(user).filter(pk__in=ids))
