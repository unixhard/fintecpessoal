"""Camada de serviços da app finance.

Contém as operações de domínio reutilizáveis do núcleo financeiro (receita,
despesa, transferência, recorrência e saldos). Nenhuma destas operações depende
de request/session/template — recebem explicitamente usuário e objetos.

Dependências apenas de cima para baixo (INTERFACE -> SERVICES -> MODELS -> DB):
as views nunca devem conter regras financeiras; devem delegar a estes serviços.
"""

from .ai_suggestions import suggest_category_with_ai  # noqa: F401
