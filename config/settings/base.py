"""
FINTECPESSOAL — Configurações base (compartilhadas).

Contém todas as configurações comuns aos ambientes development, production e test.
Nenhuma configuração de ambiente específica deve ficar aqui.

Ambientes específicos importam este módulo e sobrescrevem o necessário.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# Caminhos base do projeto
# BASE_DIR = C:\fintecpessoal (raiz que contém manage.py)
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# Carrega variáveis de ambiente a partir de um arquivo .env (se existir).
# As configurações de ambiente (development/production/test) chamam esta função.
load_dotenv(BASE_DIR / ".env")


def env_str(name, default=""):
    """Lê uma variável de ambiente como string, com valor padrão."""
    return os.getenv(name, default)


def env_bool(name, default=False):
    """Lê uma variável de ambiente como booleano."""
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def env_list(name, default=None):
    """Lê uma variável de ambiente como lista separada por vírgula."""
    value = os.getenv(name)
    if value is None:
        return default if default is not None else []
    return [item.strip() for item in value.split(",") if item.strip()]


# SECURITY WARNING: nunca use a chave real em produção.
SECRET_KEY = env_str(
    "SECRET_KEY",
    default="django-insecure-dev-only-change-me-in-production",
)

# Em desenvolvimento deixamos DEBUG configurável via .env.
DEBUG = env_bool("DEBUG", default=False)

ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", default=[])

# ---------------------------------------------------------------------------- #
# IA opcional (Google Gemini Flash Lite)
# ---------------------------------------------------------------------------- #
# Recursos de IA (leitura de comprovantes e sugestão de categoria) funcionam
# como FEATURE FLAG OPCIONAL: se GEMINI_API_KEY estiver vazia, todos os fluxos
# caem para o modo manual sem lançar erros ao usuário.
GEMINI_API_KEY = env_str("GEMINI_API_KEY")
GEMINI_MODEL = env_str("GEMINI_MODEL", default="gemini-3.5-flash-lite")
# Modelo/sistema usados como prefixo nos prompts (não é a chave — nada sensível).
GEMINI_TIMEOUT_SECONDS = 90

# Application definition
DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

# Apps locais do FINTECPESSOAL
# (apps de terceiros seriam colocados em uma lista separada, antes de LOCAL_APPS)
LOCAL_APPS = [
    "apps.core",
    "apps.accounts",
    "apps.dashboard",
    "apps.finance",
    "apps.cards",
    "apps.budgets",
    "apps.goals",
    "apps.debts",
    "apps.reports",
    "apps.networth",
    "apps.reminders",
    "apps.comprovantes",
    "apps.imports",
    "apps.user_settings",
]

INSTALLED_APPS = DJANGO_APPS + LOCAL_APPS

# Modelo de usuário customizado (decisão D2 — custom user desde o início).
AUTH_USER_MODEL = "accounts.User"

# Autenticação exclusivamente pelo sistema nativo do Django. O backend padrão
# (ModelBackend) + EmailBackend permitem login por email (identificador amigável),
# pois o `username` é derivado automaticamente no cadastro e não é pedido ao usuário.
AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
    "apps.accounts.backends.EmailBackend",
]

# Após login, direciona para o onboarding se pendente; senão para a aplicação.
LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "dashboard:index"
LOGOUT_REDIRECT_URL = "accounts:login"

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.dashboard.context.app_navigation",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# Database
# SQLite por padrão. Se a variável DATABASE_URL (ex.: PostgreSQL do Supabase)
# estiver definida, usa o banco remoto; caso contrário mantém o SQLite local.
def _default_database():
    url = env_str("DATABASE_URL", "").strip()
    if url:
        return _database_from_url(url)
    return {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }


def _database_from_url(url: str):
    """Monta a config do Django a partir de uma connection string (ex.: Postgres).

    Aceita o formato ``postgresql://user:password@host:port/dbname``, com a
    senha devidamente URL-encodada. Reusa stdlib, sem dependências extras.
    """
    import urllib.parse

    parsed = urllib.parse.urlsplit(url)
    options = dict(urllib.parse.parse_qsl(parsed.query))
    sslmode = options.get("sslmode", "require")

    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": parsed.path.strip("/"),
        "USER": urllib.parse.unquote(parsed.username or ""),
        "PASSWORD": urllib.parse.unquote(parsed.password or ""),
        "HOST": parsed.hostname,
        "PORT": parsed.port or 5432,
        "CONN_MAX_AGE": 60,
        "OPTIONS": {"sslmode": sslmode},
    }


DATABASES = {"default": _default_database()}

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": (
            "django.contrib.auth.password_validation."
            "UserAttributeSimilarityValidator"
        ),
    },
    {
        "NAME": (
            "django.contrib.auth.password_validation.MinimumLengthValidator"
        ),
    },
    {
        "NAME": (
            "django.contrib.auth.password_validation.CommonPasswordValidator"
        ),
    },
    {
        "NAME": (
            "django.contrib.auth.password_validation.NumericPasswordValidator"
        ),
    },
]

# Internationalization
LANGUAGE_CODE = "pt-br"
TIME_ZONE = "America/Sao_Paulo"
USE_I18N = True
USE_TZ = True

# Static files
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [
    BASE_DIR / "static",
]

# Media files (uploads futuros)
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

# Email — por padrão envia apenas para o console em desenvolvimento.
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# Django default primary key field type
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Limites de upload — aumentados para suportar importações com muitas linhas
# (ex.: 1000+ transações geram >1000 campos POST no formulário de revisão).
DATA_UPLOAD_MAX_NUMBER_FIELDS = 10_000
