"""Serviço de gestão de regras de classificação (Ordem 18 — FASE 6).

Coordenada criação/edição/exclusão de ``ClassificationRule`` com a regra de
isolamento multiusuário fora das views (regra 16):

  - Regras PESSOAIS (owner definido): gerenciáveis pelo próprio usuário.
  - Regras GLOBAIS (owner IS NULL): catálogo read-only para usuários comuns;
    apenas admin cria/edita. Usuário nunca vê nem altera o global de outro.

Sempre retorna 404/sem conflito (não cria segunda contabilidade/Transaction).
Nenhuma regra apaga/referencia categoria de outro usuário.
"""

from django.core.exceptions import ValidationError

from ..models import Category, ClassificationRule, Merchant

_GLOBAL_READONLY_MSG = "Regras globais são read-only para usuários comuns."


def _validate_owned(action: str, user, rule: ClassificationRule):
    """Garante que uma regra PESSOAL pertence a ``user`` (isolamento D14)."""
    if rule.owner_id is None:
        raise PermissionError(_GLOBAL_READONLY_MSG)
    if rule.owner_id != user.id:
        raise PermissionError("Regra não pertence ao usuário.")


def create_rule(
    *,
    user,
    is_global: bool = False,
    name: str = "",
    condition_type: str = ClassificationRule.ConditionType.CONTAINS,
    pattern: str = "",
    merchant=None,
    category: Category = None,
    category_name: str = "",
    kind: str = ClassificationRule.Kind.ANY,
    priority: int = 100,
    source: str = "user",
) -> ClassificationRule:
    """Cria uma regra pessoal (padrão) ou global (admin/catálogo).

    A categoria-alvo, se fornecida via FK, deve pertencer a ``user`` quando a
    regra for pessoal. Regras globais usam ``category_name`` (string da
    taxonomia) resolvida em runtime — nunca referenciam category de usuário.
    """
    if is_global:
        _validate_category_name_for_global(category_name, category)
        return ClassificationRule.objects.create(
            owner=None,
            name=name,
            condition_type=condition_type,
            pattern=pattern,
            merchant=merchant if merchant and merchant.owner_id is None else None,
            category=category if (category and category.owner_id is None) else None,
            category_name=category_name,
            kind=kind,
            priority=priority,
            source=source or "admin",
        )

    if category is not None and category.owner_id != user.id:
        raise ValueError("Categoria deve pertencer ao usuário.")
    if merchant is not None and merchant.owner_id is not None and merchant.owner_id != user.id:
        raise ValueError("Estabelecimento pessoal deve pertencer ao usuário.")
    return ClassificationRule.objects.create(
        owner=user,
        name=name,
        condition_type=condition_type,
        pattern=pattern,
        merchant=merchant,
        category=category,
        category_name=category_name,
        kind=kind,
        priority=priority,
        source=source or "user",
    )


def _validate_category_name_for_global(category_name, category):
    # Regra global não pode apontar para category de um usuário específico.
    if category is not None and category.owner_id is not None:
        raise ValueError("Regra global não pode referenciar categoria de usuário.")
    if not (category_name or "").strip() and category is None:
        raise ValidationError("Informe category_name para a regra global.")


def update_rule(user, rule: ClassificationRule, **fields) -> ClassificationRule:
    """Atualiza campos de uma regra PESSOAL do usuário (isolamento)."""
    _validate_owned("update", user, rule)
    allowed = {
        "name", "condition_type", "pattern", "merchant", "category",
        "category_name", "kind", "priority", "is_active",
    }
    for key, value in fields.items():
        if key not in allowed:
            raise ValueError(f"Campo não permitido: {key}")
    if "category" in fields and fields["category"] is not None and fields["category"].owner_id != user.id:
        raise ValueError("Categoria deve pertencer ao usuário.")
    if "merchant" in fields and fields["merchant"] is not None \
            and fields["merchant"].owner_id is not None \
            and fields["merchant"].owner_id != user.id:
        raise ValueError("Estabelecimento pessoal deve pertencer ao usuário.")
    for key, value in fields.items():
        setattr(rule, key, value)
    rule.save()
    return rule


def delete_rule(user, rule: ClassificationRule) -> bool:
    """Remove uma regra PESSOAL do usuário."""
    _validate_owned("delete", user, rule)
    rule.delete()
    return True


def set_active(user, rule: ClassificationRule, is_active: bool) -> ClassificationRule:
    _validate_owned("set_active", user, rule)
    rule.is_active = bool(is_active)
    rule.save(update_fields=["is_active"])
    return rule


def set_priority(user, rule: ClassificationRule, priority: int) -> ClassificationRule:
    _validate_owned("set_priority", user, rule)
    rule.priority = int(priority)
    rule.save(update_fields=["priority"])
    return rule


def list_rules(user) -> list:
    """Regras pessoais do usuário (para gestão). Ordenadas por prioridade."""
    return list(
        ClassificationRule.objects.filter(owner=user).select_related("category", "merchant")
    )


def list_global_rules() -> list:
    """Regras globais do catálogo (read-only para usuários comuns)."""
    return list(
        ClassificationRule.objects.filter(owner__isnull=True).select_related("category", "merchant")
    )
