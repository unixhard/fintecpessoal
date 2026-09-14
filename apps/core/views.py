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
        from decimal import Decimal

        from django.contrib.auth import get_user_model

        from apps.painel.models import MonetizationConfig, Plan

        plans = list(Plan.objects.filter(is_active=True).order_by("order", "price"))
        for plan in plans:
            # Equivalência mensal usada na ancoragem de preço da grid de planos
            # (aplicável a planos recorrentes com duração acima de um mês).
            if not plan.is_lifetime and plan.price and plan.duration_days and plan.duration_days > 30:
                plan.per_month = round(
                    plan.price / (Decimal(plan.duration_days) / Decimal("30")), 2
                )
            else:
                plan.per_month = None
        cfg = MonetizationConfig.get_singleton()
        ctx = {
            "plans": plans,
            "monetization": cfg,
            "total_users": get_user_model().objects.count(),
        }
        return render(request, "core/home.html", ctx)
    # Usuário autenticado: direciona para onboarding ou aplicação.
    onboarded = getattr(getattr(request.user, "profile", None), "onboarding_completed", False)
    if not onboarded:
        return redirect("accounts:onboarding_step", step=1)
    return redirect(settings.LOGIN_REDIRECT_URL or "dashboard:index")


def health_check(request):
    """Health check simples para confirmar que a aplicação está de pé."""
    return render(request, "core/health.html", status=200)
