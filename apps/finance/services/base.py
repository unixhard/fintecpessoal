"""Helpers compartilhados pelos serviços financeiros.

Centraliza o isolamento multiusuário (ownership) e a validação de valores
monetários em centavos, evitando repetição entre `finance` e `cards`.
"""

from .errors import ForbiddenResourceError, InvalidAmountError


def require_owned(manager, user, *, model_label, object_id=None, **extra):
    """Retorna o objeto do usuário OU lança ForbiddenResourceError.

    Usa ``objects.for_user(user)`` — nunca confia em um ID vindo da interface
    sem verificar ownership (regra 15). Se o objeto não pertence ao usuário (ou
    não existe), a operação é tratada como recurso inexistente para o usuário.
    """
    qs = manager.for_user(user)
    if object_id is not None:
        qs = qs.filter(pk=object_id)
    for key, value in extra.items():
        qs = qs.filter(**{key: value})
    obj = qs.first()
    if obj is None:
        raise ForbiddenResourceError(
            f"{model_label} inexistente ou não pertence ao usuário."
        )
    return obj


def ensure_owned_integer_amount(amount, *, field="valor"):
    """Valida que um valor monetário é um inteiro em centavos > 0.

    Decisão D10: dinheiro é SEMPRE inteiro em centavos, nunca float.
    """
    if isinstance(amount, bool) or not isinstance(amount, int):
        raise InvalidAmountError(f"{field} deve ser um inteiro em centavos.")
    if amount <= 0:
        raise InvalidAmountError(f"{field} deve ser maior que zero.")
    return amount
