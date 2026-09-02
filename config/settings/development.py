"""
FINTECPESSOAL — Configurações de desenvolvimento.

Ambiente local, DEBUG ligado por padrão, servidor de desenvolvimento.
Nada aqui deve ser usado em produção.
"""

from .base import (  # noqa: F401
    BASE_DIR,
    env_bool,
    env_list,
    env_str,
    load_dotenv,
)

load_dotenv(BASE_DIR / ".env")

from .base import *  # noqa: F401,F403

# Força DEBUG True em desenvolvimento, caso não definido explicitamente.
DEBUG = env_bool("DEBUG", default=True)

# Em desenvolvimento aceitamos requisições de localhost.
ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])
