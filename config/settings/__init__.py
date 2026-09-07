"""
Ponto de entrada das configurações do FINTECPESSOAL.

Escolhe o módulo de ambiente (development | production | test) com base na
variável de ambiente DJANGO_ENV. O padrão é development.

Se DJANGO_ENV não estiver definida e o processo for de teste (manage.py test),
usa automaticamente o módulo de teste — assim a suíte nunca carrega a chave de
IA real nem o banco de desenvolvimento.

Uso:
    DJANGO_ENV=production; python manage.py runserver
    django-admin test          (detecta test automaticamente)

A DJANGO_SETTINGS_MODULE continua apontando para "config.settings"; este
pacote repassa as configurações do ambiente selecionado.
"""

import os
import sys

ENV = os.getenv("DJANGO_ENV")

if not ENV and any(arg in ("test", "testserver") for arg in sys.argv):
    ENV = "test"

if ENV is None:
    ENV = "development"

if ENV == "production":
    from .production import *  # noqa: F401,F403
elif ENV == "test":
    from .test import *  # noqa: F401,F403
else:
    from .development import *  # noqa: F401,F403
