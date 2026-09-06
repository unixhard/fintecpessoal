"""Detecção de possíveis duplicidades (Ordem 17 — ponto crítico).

Sinais considerados:
  - mesmo identificador externo (external_id / source_id);
  - mesma data;
  - mesmo valor;
  - descrição semelhante;
  - mesmas contas;
  - proximidade temporal.

Classificações: ALTA CONFIANÇA / POSSÍVEL DUPLICIDADE / NÃO DUPLICADO.

NUNCA apagamos lançamento existente: apenas sinalizamos e deixamos a decisão
para o usuário na tela de revisão. A verificação também olha o razão atual
(Transaction) para não duplicar algo já importado antes.
"""

import difflib
from typing import List

from django.db.models import Count

from ...finance.models import Transaction
from .candidates import (
    CONFIDENCE_DUPLICATE,
    CONFIDENCE_HIGH,
    CONFIDENCE_REVIEW,
    ROW_IGNORED,
    ROW_READY,
    Candidate,
)
from .normalized import NormalizedTransaction

_EXACT_KEYS = {}


def _similar(a: str, b: str, ratio: float = 0.9) -> bool:
    if not a or not b:
        return False
    return difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio() >= ratio


def detect(user, parsed: List[NormalizedTransaction], batch=None) -> List[Candidate]:
    """Classifica e detecta duplicidades entre os itens e o razão existente."""
    candidates: List[Candidate] = []
    # chave (date, amount, description_normalizada) -> índice no lote atual
    seen_in_file = {}

    # índice de transações existentes do usuário por (date, amount)
    existing_index = _index_existing(user, parsed)

    for nt in parsed:
        cand = Candidate.from_normalized(nt)
        cand = _identify_merchant(user, cand)
        cand = _classify_with_engine(user, cand)

        date = nt.date
        amount = nt.amount_cents
        desc_norm = _norm(nt.description)

        # 1) duplicidade exata dentro do próprio arquivo
        dup_key = (date, amount, desc_norm)
        if dup_key in seen_in_file:
            _mark_duplicate(cand, status=CONFIDENCE_DUPLICATE,
                            reason="Duplicada no mesmo arquivo",
                            reference=seen_in_file[dup_key])
            candidates.append(cand)
            continue
        seen_in_file[dup_key] = cand

        # 2) external_id já existente no razão
        external = nt.source_id.strip()
        if external:
            if existing_index.get(("external", external)):
                _mark_duplicate(cand, status=CONFIDENCE_DUPLICATE,
                                reason="Identificador externo já existente",
                                reference=existing_index[("external", external)])
                candidates.append(cand)
                continue

        # 3) possível duplicidade contra o razão (mesma data+valor+descrição)
        match = existing_index.get((date, amount))
        if match:
            if _similar(nt.description, match["description"]):
                _mark_duplicate(cand, status=CONFIDENCE_DUPLICATE,
                                reason="Possível duplicidade já existente",
                                reference=match)
                candidates.append(cand)
                continue
            cand.confidence = CONFIDENCE_REVIEW
            cand.metadata["existing_similar"] = match["description"]

        candidates.append(cand)

    return candidates


def _norm(text: str) -> str:
    return " ".join((text or "").lower().split())


def _identify_merchant(user, cand: Candidate) -> Candidate:
    """Identifica o estabelecimento da descrição (Ordem 18 / FASE 4).

    Sem IA por transação: usa a camada determinística de Merchant/Alias.
    Nunca altera ``description``/``original_description``.
    """
    from ...finance.services.merchants import resolve_merchant

    if not (cand.description or "").strip():
        return cand
    res = resolve_merchant(user, cand.description)
    if res.matched and res.merchant is not None:
        cand.merchant = res.merchant
        cand.normalized_description = res.normalized_description
        cand.merchant_method = res.method
        cand.merchant_confidence = res.confidence
    else:
        cand.normalized_description = res.normalized_description
    return cand


def _classify_with_engine(user, cand: Candidate) -> Candidate:
    """Classifica o candidato pelo Motor de Classificação Financeira (FASE 5).

    Usa Merchant + descrição normalizada e aplica a ordem determinística (§3).
    Persiste o resultado no Candidate:
      - ``category``/``category_name``: sugestão (leaf obtida ou nome p/ criar);
      - ``merchant_method``/``confidence`` já trazidos pela FASE 4;
      - metadata com método e confiança objetiva da classificação;
      - ``cand.confidence`` (imports): HIGH se automático, REVIEW se a decisão
        precisa de revisão humana (confiança < limiar).
    """
    from ...finance.services.classifier import classify

    desc = (cand.description or "").strip()
    if not desc:
        return cand

    result = classify(
        user=user,
        description=desc,
        direction=cand.direction,
        merchant=cand.merchant,
        suggested_category=(cand.metadata or {}).get("suggested_category") or "",
    )

    cand.category = result.category
    cand.category_name = result.leaf_name or result.category_name
    cand.normalized_description = result.normalized_description or cand.normalized_description
    cand.metadata["classification_method"] = result.method
    cand.metadata["classification_confidence"] = str(result.confidence)
    cand.metadata["classification_needs_review"] = result.needs_review

    if result.needs_review and cand.confidence == CONFIDENCE_HIGH:
        cand.confidence = CONFIDENCE_REVIEW
    return cand


def _index_existing(user, parsed: List[NormalizedTransaction]):
    """Índice de transações existentes relevantes (mesmas datas+valores+ids)."""
    dates = {nt.date for nt in parsed}
    amounts = {nt.amount_cents for nt in parsed}
    external_ids = {nt.source_id.strip() for nt in parsed if nt.source_id.strip()}

    idx: dict = {}
    if not dates:
        return idx

    qs = (
        Transaction.objects.for_user(user)
        .filter(date__in=dates, amount__in=amounts)
        .order_by("date", "id")
    )
    for t in qs:
        key = (t.date, t.amount)
        idx.setdefault(key, {"transaction_id": t.id, "description": t.description or ""})
        if t.external_id:
            idx.setdefault(("external", t.external_id), {"transaction_id": t.id, "description": t.description or ""})

    if external_ids:
        ext_qs = Transaction.objects.for_user(user).filter(external_id__in=external_ids)
        for t in ext_qs:
            idx.setdefault(("external", t.external_id), {"transaction_id": t.id, "description": t.description or ""})

    return idx


def _mark_duplicate(cand: Candidate, *, status: str, reason: str, reference) -> None:
    cand.confidence = status
    cand.row_status = ROW_IGNORED if status == CONFIDENCE_DUPLICATE else ROW_READY
    cand.skip_reason = reason
    if isinstance(reference, dict) and reference.get("transaction_id"):
        cand.matched_transaction_id = reference["transaction_id"]
