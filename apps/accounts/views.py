"""Views do app accounts — autenticação e cadastro.

Autenticação inteiramente baseada no sistema nativo do Django: `LoginView`,
`LogoutView` (POST) e o conjunto de views de password reset, apenas com
templates e formulários próprios (mensagens em português).
"""

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.views import (
    LoginView,
    LogoutView,
    PasswordResetCompleteView,
    PasswordResetConfirmView,
    PasswordResetDoneView,
    PasswordResetView,
)
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.views import View

from .forms import FintroLoginForm, SignUpForm


class FintroLoginView(LoginView):
    template_name = "accounts/login.html"
    authentication_form = FintroLoginForm
    redirect_authenticated_user = True

    def get_success_url(self):
        # Vai para a home; a home desvia para onboarding ou para a aplicação.
        return reverse_lazy("core:home")


class FintroLogoutView(LogoutView):
    """Logout via POST (boas práticas). Nada além do redirect configurado."""


class SignUpView(View):
    template_name = "accounts/signup.html"

    def get(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect("core:home")
        return render(request, self.template_name, {"form": SignUpForm()})

    def post(self, request, *args, **kwargs):
        form = SignUpForm(request.POST)
        if not form.is_valid():
            return render(request, self.template_name, {"form": form})
        user = form.save()
        # Autentica automaticamente após o cadastro (sem redigitar a senha).
        login(self.request, user, backend="django.contrib.auth.backends.ModelBackend")
        messages.success(
            self.request,
            "Conta criada com sucesso. Vamos começar seu cadastro financeiro.",
        )
        return redirect("accounts:onboarding_step", step=1)


class FintroPasswordResetView(PasswordResetView):
    template_name = "accounts/password_reset_form.html"
    subject_template_name = "accounts/emails/password_reset_subject.txt"
    email_template_name = "accounts/emails/password_reset_email.txt"
    html_email_template_name = "accounts/emails/password_reset_email.html"
    success_url = reverse_lazy("accounts:password_reset_done")


class FintroPasswordResetDoneView(PasswordResetDoneView):
    template_name = "accounts/password_reset_done.html"


class FintroPasswordResetConfirmView(PasswordResetConfirmView):
    template_name = "accounts/password_reset_confirm.html"
    success_url = reverse_lazy("accounts:password_reset_complete")


class FintroPasswordResetCompleteView(PasswordResetCompleteView):
    template_name = "accounts/password_reset_complete.html"
