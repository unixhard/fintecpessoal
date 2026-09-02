"""Serviço de gerenciamento de categorias (Category).

A criação/edição de categoria é coordenada aqui (ownership + validação),
mantendo a regra de isolamento multiusuário fora das views (regra 16).
Categorias padrão (``is_default``) continuam funcionando; não são tocadas aqui.
"""

from ..models import Category
from .base import require_owned


def create_category(
    *,
    user,
    name,
    kind=Category.Kind.EXPENSE,
    parent=None,
):
    """Cria uma categoria personalizada pertencente ao usuário."""
    name = (name or "").strip()
    if not name:
        raise ValueError("nome da categoria é obrigatório.")
    if parent is not None:
        require_owned(
            Category.objects, user, model_label="Categoria",
            object_id=getattr(parent, "pk", None),
        )
        if parent.pk is None:
            raise ValueError("Categoria pai inválida.")
    return Category.objects.create(
        owner=user,
        name=name,
        kind=kind,
        parent=parent,
        status=Category.Status.ACTIVE,
    )


def update_category(*, user, category, name=None, kind=None, parent=None, status=None):
    """Atualiza campos editáveis de uma categoria (ownership validado).

    Para subcategorias o pai deve ser do mesmo usuário. Não altera
    ``is_default`` (categorias padrão são imutáveis por esse fluxo).
    """
    require_owned(
        Category.objects, user, model_label="Categoria",
        object_id=getattr(category, "pk", None),
    )
    if name is not None:
        name = name.strip()
        if not name:
            raise ValueError("nome da categoria é obrigatório.")
        category.name = name
    if kind is not None:
        category.kind = kind
    if parent is not None:
        if parent.pk:
            require_owned(
                Category.objects, user, model_label="Categoria",
                object_id=parent.pk,
            )
        category.parent = parent or None
    if status is not None:
        category.status = status
    category.save()
    return category


def archive_category(*, user, category):
    """Arquiva (inativa) uma categoria do usuário.

    Não remove dados históricos (transações já vinculadas permanecem).
    """
    require_owned(
        Category.objects, user, model_label="Categoria",
        object_id=getattr(category, "pk", None),
    )
    category.status = Category.Status.INACTIVE
    category.save()
    return category
