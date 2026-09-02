"""Exceções da camada de serviços financeiros.

Permitem distinguir problemas de domínio (valor inválido, estado inválido) de
problemas de segurança/isolamento (objeto de outro usuário), mantendo a camada
de serviços independente de request e views.
"""

from django.core.exceptions import ValidationError


class FinancialServiceError(Exception):
    """Erro-base de todos os serviços financeiros."""


class ForbiddenResourceError(FinancialServiceError, PermissionError):
    """O usuário tentou usar um objeto financeiro que pertence a outro usuário.

    Lançada sempre que a verificação de ownership falha. Nunca devemos retornar
    um objeto de outro usuário; em vez disso, tratamos como recurso inexistente.
    """


class InvalidAmountError(FinancialServiceError, ValidationError):
    """Valor monetário inválido (<= 0, não inteiro, etc.)."""


class InvalidStateError(FinancialServiceError):
    """Operação inválida para o estado atual do objeto (ex.: fatura já paga)."""


class DuplicateOccurrenceError(FinancialServiceError):
    """Já existe ocorrência materializada para a regra/periodo solicitado."""
