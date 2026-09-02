"""
URL configuration for the FINTECPESSOAL project.

Roteia as URLs globais do projeto. Rotas específicas de cada app ficam no
próprio app (ex.: apps.core.urls), incluídas aqui.
"""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    # Apps locais
    path("", include("apps.core.urls")),
    path("contas/", include("apps.accounts.urls")),
    path("app/finance/", include("apps.finance.urls")),
    path("app/cards/", include("apps.cards.urls")),
    path("app/orcamentos/", include("apps.budgets.urls")),
    path("app/metas/", include("apps.goals.urls")),
    path("app/dividas/", include("apps.debts.urls")),
    path("app/relatorios/", include("apps.reports.urls")),
    path("app/patrimonio/", include("apps.networth.urls")),
    path("app/lembretes/", include("apps.reminders.urls")),
    path("app/comprovantes/", include("apps.comprovantes.urls")),
    path("app/", include("apps.dashboard.urls")),
]

# Em desenvolvimento, servir arquivos estáticos e de mídia localmente.
if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
