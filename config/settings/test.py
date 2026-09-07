"""
FINTECPESSOAL — Configurações de teste.

Usado ao executar a suíte de testes (manage.py test).
Banco isolado, sem pedir credenciais, e com dados descartáveis.
"""

from .base import (  # noqa: F401
    BASE_DIR,
    env_bool,
    env_list,
    env_str,
    load_dotenv,
)

import os

# Garante cooldown padrão (3 dias) nos testes, mesmo se .env local definir 0
# (liberado para teste manual). Os testes de cooldown partem desse valor base.
os.environ["REPORT_COOLDOWN_DAYS"] = "3"

load_dotenv(BASE_DIR / ".env")

from .base import *  # noqa: F401,F403

DEBUG = False

# IA desligada por padrão nos testes: cada teste de IA habilita a chave via
# ``override_settings(GEMINI_API_KEY=...)`` e mocka a chamada HTTP. Isso
# garante que a suíte nunca faça chamadas reais à API nem gaste cotas.
GEMINI_API_KEY = ""

# Usa um banco SQLite em memória para os testes.
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

# Evita que testes esperem por tráfego real de estáticos.
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.MD5PasswordHasher",
]

EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
