"""
Ponto de entrada das configurações do FINTECPESSOAL.

Escolhe o módulo de ambiente (development | production | test) com base na
variável de ambiente DJANGO_ENV. O padrão é development.

Uso:
    DJANGO_ENV=production python manage.py runserver
    DJANGO_ENV=test      python manage.py test

A DJANGO_SETTINGS_MODULE continua apontando para "config.settings"; este
pacote repassa as configurações do ambiente selecionado.
"""

import os

ENV = os.getenv("DJANGO_ENV", "development")

if ENV == "production":
    from .production import *  # noqa: F401,F403
elif ENV == "test":
    from .test import *  # noqa: F401,F403
else:
    from .development import *  # noqa: F401,F403
