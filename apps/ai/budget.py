"""Configurações de economia de tokens e presença da IA (CFO de Bolso).

Todos os limites vivem aqui para serem ajustáveis por env sem tocar no código.
Os valores padrão foram dimensionados para o free tier do Gemini Flash-Lite
(≈15 RPM e ~500–1.000 RPD): no pior caso, ~50 usuários ativos gastam pouco
mais de 200 RPD/dia combinando presença + consultas + relatórios.
"""

import os


def _int_env(name: str, default: int) -> int:
    try:
        return max(0, int(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


# A "presença" é gerada UMA vez por usuário por dia (cache) — o coração da
# economia: todo o texto de IA do dashboard sai de 1 chamada/dia.
PRESENCE_DAILY_CAP = 1

# Consultas "Pergunte ao CFO" (chamadas de IA) por usuário por dia.
CONSULT_DAILY_CAP = _int_env("AI_CONSULT_DAILY_CAP", 3)

# Relatórios mensais por IA são limitados pelo cooldown do app de relatórios.
REPORT_DAILY_CAP = 2

# Janela (em segundos) em que o circuit breaker desliga chamadas após 429.
CIRCUIT_BREAKER_OPEN_SECONDS = _int_env("AI_BREAKER_SECONDS", 900)

# Limite de falhas consecutivas antes de abrir o circuit breaker.
CIRCUIT_BREAKER_FAILURES = _int_env("AI_BREAKER_FAILURES", 3)

# Tetos de saída (tokens) por chamada para conter custo do free tier.
OUTPUT_TOKENS_PRESENCE = 1024
OUTPUT_TOKENS_CONSULT = 600
OUTPUT_TOKENS_REPORT = 8192