"""Rotas do app accounts — autenticação, cadastro e onboarding."""

from django.contrib.auth.views import (
    PasswordResetConfirmView,
)
from django.urls import path, reverse_lazy

from . import onboarding, views

app_name = "accounts"

urlpatterns = [
    # Autenticação
    path("entrar/", views.FintroLoginView.as_view(), name="login"),
    path("sair/", views.FintroLogoutView.as_view(), name="logout"),
    path("cadastro/", views.SignUpView.as_view(), name="signup"),
    # Recuperação de senha (fluxo nativo do Django, com templates próprios)
    path(
        "recuperar-senha/",
        views.FintroPasswordResetView.as_view(),
        name="password_reset",
    ),
    path(
        "recuperar-senha/enviado/",
        views.FintroPasswordResetDoneView.as_view(),
        name="password_reset_done",
    ),
    path(
        "recuperar-senha/confirmar/<uidb64>/<token>/",
        PasswordResetConfirmView.as_view(
            template_name="accounts/password_reset_confirm.html",
            success_url=reverse_lazy("accounts:password_reset_complete"),
        ),
        name="password_reset_confirm",
    ),
    path(
        "recuperar-senha/concluido/",
        views.FintroPasswordResetCompleteView.as_view(),
        name="password_reset_complete",
    ),
    # Onboarding (4 etapas)
    path(
        "onboarding/<int:step>/",
        onboarding._onboarding_step_view,
        name="onboarding_step",
    ),
]
