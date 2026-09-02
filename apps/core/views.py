"""Views do app core (páginas institucionais/técnicas básicas).

A rota raiz (`/`) funciona como roteadora da experiência:
- anônimo  -> landing page institucional (home.html)
- autenticado e sem onboarding concluído -> onboarding etapa 1
- autenticado e onboarding concluído    -> shell da aplicação (dashboard)
"""

from django.conf import settings
from django.shortcuts import redirect, render


def home(request):
    """Roteia o visitante conforme o estado de autenticação/onboarding."""
    if not request.user.is_authenticated:
        return render(request, "core/home.html")
    # Usuário autenticado: direciona para onboarding ou aplicação.
    onboarded = getattr(getattr(request.user, "profile", None), "onboarding_completed", False)
    if not onboarded:
        return redirect("accounts:onboarding_step", step=1)
    return redirect(settings.LOGIN_REDIRECT_URL or "dashboard:index")


def health_check(request):
    """Health check simples para confirmar que a aplicação está de pé."""
    return render(request, "core/health.html", status=200)
