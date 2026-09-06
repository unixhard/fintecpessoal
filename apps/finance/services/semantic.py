"""Classificador semântico OPCIONAL (Ordem 18 — FASE 11).

Princípio (§13): a IA NUNCA é chamada por transação rotineiramente. Este módulo
é um complemento DESLIGADO POR PADRÃO que só entra em cena para RESOLVER
AMBIGUIDADE — transações que o motor determinístico deixou SEM EVIDÊNCIA
(method == none) ou com confiança abaixo do limiar e ainda não corrigidas.

Garantias:
  - Nunca sobrescreve decisão explícita do usuário (user_correction),
    regra do usuário, merchant, movimento neutro nem correção persistida.
  - Nunca altera accounting core (apenas persiste TransactionAnalysis).
  - Provider INJETÁVEL: em produção o cliente real só é instanciado se
    explicitamente ativado; em teste usa-se um provider mock (sem chamada
    externa real). Nunca há chamada de rede ao Gemini por transação.
  - Falha silenciosa: qualquer erro do provider cai de volta ao resultado
    determinístico sem afetar a operação.
"""

import logging

from decimal import Decimal

from django.conf import settings

from .classifier import (
    ClassificationResult,
    _confidence,
    _resolve_category,
    classify,
)
from ..models import Category, Transaction, TransactionAnalysis

logger = logging.getLogger(__name__)

# Nome da configuração booleana que liga o classificador semântico.
ENABLED_SETTING = "FINANCE_SEMANTIC_ENABLED"

# Nome da classe provider a instanciar (string de importação).
PROVIDER_SETTING = "FINANCE_SEMANTIC_PROVIDER"

_CONFIDENCE_SEMANTIC = Decimal("0.88")


def is_enabled() -> bool:
    """Ligado só se explicitamente configurado (default: desligado)."""
    return bool(getattr(settings, ENABLED_SETTING, False))


class SemanticProvider:
    """Interface base. Subclasses retornam (category_name, confidence).

    ``classify_text`` recebe descrição normalizada e direção e deve devolver
    ``None`` (sem sugestão) ou uma tupla ``(nome_da_categoria, confiança)``.
    """

    def classify_text(self, description: str, direction: str):
        raise NotImplementedError


def _load_provider():
    """Instancia o provider configurado via import string. Falso por padrão.

    Nunca chama rede aqui: apenas constrói o objeto. Chamadas reais ocorrem
    exclusivamente quando o usuário ativar explicitamente a integração.
    """
    path = getattr(settings, PROVIDER_SETTING, "")
    if not path:
        return None
    try:
        module_name, _, attr = path.rpartition(".")
        import importlib

        module = importlib.import_module(module_name)
        provider_cls = getattr(module, attr)
        return provider_cls()
    except Exception:  # noqa: BLE001 - falha de configuração é não-crítica
        logger.warning("Classificador semântico não pôde ser carregado (%s)", path)
        return None


def semantic_classify(*, user, description, direction, provider=None) -> ClassificationResult:
    """Tenta a IA apenas sobre ambiguidade. Cobre todos os casos de falha.

    - Retorna o resultado determinístico se o recurso estiver desligado,
      sem provider, sem categoria sugerida, ou se o provider falhar.
    - NUNCA é chamado para transações já resolvidas por fontes determinísticas
      de valor (correção, regra, merchant, movimento).
    """
    # Recomeça do motor determinístico para avaliar o status real.
    base = classify(
        user=user,
        description=description,
        direction=direction,
    )

    # Só ambíguo: sem evidência OU sem categoria com confiança baixa.
    ambiguous = (
        base.method == TransactionAnalysis.Source.NONE
        or (base.category is None and base.needs_review)
    )
    if not ambiguous:
        return base

    if not is_enabled():
        return base

    provider = provider or _load_provider()
    if provider is None:
        return base

    kind = Category.Kind.INCOME if direction == "income" else Category.Kind.EXPENSE
    try:
        suggestion = provider.classify_text(base.normalized_description or description, direction)
    except Exception:  # noqa: BLE001 - falha externa nunca quebra o fluxo
        logger.warning("Falha no classificador semântico; usa determinístico")
        return base
    if not suggestion:
        return base

    name, conf = suggestion
    category = _resolve_category(user, name, kind)
    if category is None or not conf:
        return base

    result = ClassificationResult(
        category=category,
        category_name=category.parent.name if category.parent_id else category.name,
        subcategory_name=category.name if category.parent_id else "",
        merchant=base.merchant,
        confidence=Decimal(conf),
        method=TransactionAnalysis.Source.SEMANTIC,
        needs_review=Decimal(conf) < Decimal("0.75"),
        normalized_description=base.normalized_description,
    )
    return result


def apply_semantic(user, transaction, provider=None):
    """Ponto de entrada para backfill/revisão: resolve ambiguidade por IA.

    Idempotente e seguro: preserva todo o accounting e nunca sobrescreve
    correções/regras/merchant já resolvidos. Retorna a Transaction.
    """
    from .classifier import apply_classification

    direction = "income" if transaction.type == Transaction.Type.INCOME else "expense"
    result = semantic_classify(
        user=user,
        description=transaction.description or "",
        direction=direction,
        provider=provider,
    )
    # Persiste o snapshot da decisão (semântica ou determinística de fallback),
    # para que a Transaction tenha sempre um TransactionAnalysis 1:1.
    apply_classification(user, transaction, result)
    return transaction
