"""
FINTECPESSOAL — Configurações de produção.

Use com o servidor WSGI próprio para produção. Antes de usar, defina no .env:
  - SECRET_KEY (obrigatório, forte)
  - DEBUG=false
  - ALLOWED_HOSTS com o domínio real
"""

import os

from .base import (  # noqa: F401
    BASE_DIR,
    env_bool,
    env_list,
    env_str,
    load_dotenv,
)

load_dotenv(BASE_DIR / ".env")

from .base import *  # noqa: F401,F403

DEBUG = env_bool("DEBUG", default=False)
SECRET_KEY = env_str("SECRET_KEY", default="")
ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", default=[])

# Exige SECRET_KEY explícita em produção.
if not SECRET_KEY or SECRET_KEY.startswith("django-insecure-dev-only"):
    raise RuntimeError(
        "SECRET_KEY não definida ou insegura no ambiente de produção."
    )

# Segurança básica recomendada para produção.
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"

# Serve de arquivos estáticos em produção via WhiteNoise (sem servidor extra).
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    *[m for m in MIDDLEWARE if m not in (
        "django.middleware.security.SecurityMiddleware",
        "whitenoise.middleware.WhiteNoiseMiddleware",
    )],
]

# Em produção usamos arquivos estáticos coletados, servidos com compressão
# (minificação) via WhiteNoise. Usamos CompressedStaticFilesStorage (sem hash
# nos nomes) porque o source do Tailwind (input.css) usa @import "tailwindcss"
# e quebraria o post-processamento do backend Manifest. O cache-busting do
# frontend é feito manualmente com ?v= no template (base.html).
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedStaticFilesStorage",
    },
}

# Email real deve ser configurado quando houver servidor de e-mail.
EMAIL_BACKEND = os.getenv(
    "EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend"
)

# Log básico para produção.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
}
