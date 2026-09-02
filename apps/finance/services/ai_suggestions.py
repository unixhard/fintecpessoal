"""Sugestão de categoria por IA (feature flag opcional).

Retorna a categoria financeira mais provável do usuário para uma descrição,
usando o Gemini Flash Lite. 100% opcional: sem chave ou em falha, devolve
``None`` (sem exceção) e a interface simplesmente não usa a sugestão.

Apenas o texto da descrição é enviado à IA (nada de DPI desnecessário), e o
resultado é sempre validado de volta contra categorias reais ``for_user`` —
nunca inventa uma categoria que o usuário não tenha.
"""

from __future__ import annotations

import logging

from apps.core.services.ai import AIServiceError, ai_enabled, generate_json

from ..models import Category

logger = logging.getLogger(__name__)

_SYSTEM_CATEGORY_PROMPT = (
    "Você é um assistente de finanças pessoais. Receba uma descrição curta de "
    "um lançamento financeiro e a lista de categorias existentes do usuário. "
    "Escolha a categoria MAIS provável. Responda APENAS com JSON no formato "
    '{"categoria": "nome exato da categoria escolhida"}. Se nenhuma categoria '
    "das listadas for razoável, use {\"categoria\": \"\"}."
)


def list_category_names(*, user, kind=Category.Kind.EXPENSE) -> list[str]:
    """Nomes das categorias ativas do usuário filtradas por tipo."""
    qs = Category.objects.for_user(user).filter(status=Category.Status.ACTIVE)
    if kind in (Category.Kind.EXPENSE, Category.Kind.INCOME, Category.Kind.TRANSFER):
        qs = qs.filter(kind=kind)
    return sorted({c.name.strip() for c in qs if c.name.strip()})


def _pick_owned_category(*, user, suggested_name, kind):
    """Valida o nome sugerido contra as categorias reais do usuário."""
    if not suggested_name:
        return None
    suggested = suggested_name.strip().lower()
    qs = Category.objects.for_user(user).filter(status=Category.Status.ACTIVE)
    if kind in (Category.Kind.EXPENSE, Category.Kind.INCOME, Category.Kind.TRANSFER):
        qs = qs.filter(kind=kind)
    for cat in qs:
        if cat.name.strip().lower() == suggested:
            return cat
    # fallback: corresponde ignorando diferenças de acento/caixa já cobertas
    return None


def suggest_category_with_ai(*, user, descricao, kind=Category.Kind.EXPENSE):
    """Sugere a categoria mais provável do usuário para ``descricao``.

    Retorna uma instância ``Category`` pertencente ao usuário (ou ``None`` se a
    IA estiver indisponível, a descrição for insuficiente ou não houver match).
    Nunca lança exceção para o chamador — é uma melhoria opcional.
    """
    if not ai_enabled():
        return None

    descricao = (descricao or "").strip()
    if not descricao:
        return None

    names = list_category_names(user=user, kind=kind)
    if not names:
        return None

    names_list = "\n".join(f"- {n}" for n in names)
    user_prompt = (
        f"Descrição do lançamento: \"{descricao}\"\n"
        "Categorias disponíveis do usuário:\n"
        f"{names_list}\n\n"
        "Retorne a categoria mais provável."
    )

    try:
        result = generate_json(
            system_prompt=_SYSTEM_CATEGORY_PROMPT,
            user_prompt=user_prompt,
        )
    except AIServiceError as exc:
        logger.info("Sugestão de categoria indisponível: %s", exc)
        return None

    suggested = (result.get("categoria") or "").strip()
    return _pick_owned_category(user=user, suggested_name=suggested, kind=kind)
