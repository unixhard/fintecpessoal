"""Onboarding — fluxo de cadastro inicial (4 etapas).

Leva o usuário de "criei minha conta" até "minha primeira conta financeira
cadastrada". Regras financeiras NÃO ficam aqui: a criação da primeira conta
delega para o serviço `apps.finance.services.accounts.create_account`. Este
módulo apenas coordena as etapas e o estado `Profile.onboarding_completed`
(fonte de verdade ÚNICA para o flag — nenhum estado duplicado em sessão).

Etapas:
  1. Boas-vindas
  2. Perfil (display_name)
  3. Primeira conta financeira (via service)
  4. Conclusão
"""

import decimal
from decimal import Decimal

from django import forms
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect
from django.urls import reverse
from django.views import View
from django.views.generic import TemplateView

from apps.finance.models import Account
from apps.finance.services.accounts import create_account

TOTAL_STEPS = 4


def _redirect_post_onboarding(user):
    """Retorna o destino padrão: aplicação (onboarding já concluído)."""
    return redirect(reverse("dashboard:index"))


def _user_onboarded(user):
    return getattr(getattr(user, "profile", None), "onboarding_completed", False)


class OnboardingBaseMixin(LoginRequiredMixin):
    """Garante autenticação e desvia usuários que já concluíram o onboarding.

    Páginas de conclusão (ex.: a etapa 4 com o resumo) podem optar por
    permanecer acessíveis após a conclusão via ``allow_when_onboarded``.
    """

    allow_when_onboarded = False

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if _user_onboarded(request.user) and not self.allow_when_onboarded:
            return _redirect_post_onboarding(request.user)
        return super().dispatch(request, *args, **kwargs)


class OnboardingStep1View(OnboardingBaseMixin, TemplateView):
    template_name = "onboarding/step1_welcome.html"


class ProfileStepForm(forms.Form):
    display_name = forms.CharField(
        label="Como devemos te chamar?",
        required=False,
        max_length=80,
        widget=forms.TextInput(attrs={"placeholder": "Seu nome de exibição"}),
    )
    preferred_currency = forms.ChoiceField(
        label="Moeda padrão",
        choices=[("BRL", "Real (BRL)")],
        initial="BRL",
    )


class OnboardingStep2View(OnboardingBaseMixin, View):
    template_name = "onboarding/step2_profile.html"

    def get(self, request, *args, **kwargs):
        form = ProfileStepForm(initial={"display_name": request.user.profile.display_name})
        return self._render(request, form)

    def post(self, request, *args, **kwargs):
        form = ProfileStepForm(request.POST)
        if form.is_valid():
            profile = request.user.profile
            profile.display_name = form.cleaned_data["display_name"].strip()
            profile.preferred_currency = form.cleaned_data["preferred_currency"]
            profile.save(update_fields=["display_name", "preferred_currency"])
            return redirect(reverse("accounts:onboarding_step", args=[3]))
        return self._render(request, form)

    def _render(self, request, form, status=200):
        from django.shortcuts import render

        return render(
            request,
            self.template_name,
            {"form": form, "step": 2, "total_steps": TOTAL_STEPS},
            status=status,
        )


class _ReaisToCentavosField(forms.Field):
    """Campo que recebe um valor em reais (ex.: '1.000,00') e devolve em centavos.

    A conversão reais→centavos é apresentação na fronteira do formulário; a
    regra financeira (inteiro em centavos, ownership) permanece no service.
    """

    default_error_messages = {
        "invalid": "Informe um valor monetário válido (ex.: 1.500,00).",
        "negative": "O saldo inicial não pode ser negativo.",
    }

    def to_python(self, value):
        if value in self.empty_values:
            return 0
        if not isinstance(value, str):
            raise forms.ValidationError(self.error_messages["invalid"], code="invalid")
        value = value.strip()
        if not value:
            return 0
        normalized = value.replace(".", "").replace(",", ".")
        try:
            amount = Decimal(normalized)
        except (TypeError, ValueError, decimal.InvalidOperation):
            raise forms.ValidationError(self.error_messages["invalid"], code="invalid")
        return int((amount * 100).to_integral_value(rounding=decimal.ROUND_HALF_UP))

    def validate(self, value):
        super().validate(value)
        if value < 0:
            raise forms.ValidationError(self.error_messages["negative"], code="negative")


class FirstAccountForm(forms.Form):
    name = forms.CharField(
        label="Nome da conta",
        max_length=120,
        widget=forms.TextInput(attrs={"placeholder": "Ex.: Conta do dia a dia"}),
    )
    type = forms.ChoiceField(label="Tipo de conta", choices=Account.Type.choices)
    initial_balance = _ReaisToCentavosField(
        label="Saldo inicial (R$)",
        required=False,
        widget=forms.TextInput(
            attrs={"placeholder": "0,00", "inputmode": "decimal"}
        ),
    )

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        if not name:
            raise forms.ValidationError("Informe um nome para a conta.")
        return name


class OnboardingStep3View(OnboardingBaseMixin, View):
    template_name = "onboarding/step3_account.html"

    def get(self, request, *args, **kwargs):
        form = FirstAccountForm()
        return self._render(request, form)

    def post(self, request, *args, **kwargs):
        form = FirstAccountForm(request.POST)
        if form.is_valid():
            create_account(
                user=request.user,
                name=form.cleaned_data["name"],
                type=form.cleaned_data["type"],
                initial_balance=form.cleaned_data["initial_balance"],
                currency="BRL",
            )
            profile = request.user.profile
            profile.onboarding_completed = True
            profile.save(update_fields=["onboarding_completed"])
            messages.success(
                request,
                "Primeira conta cadastrada com sucesso. Que tal explorar o sistema?",
            )
            return redirect(reverse("accounts:onboarding_step", args=[4]))
        return self._render(request, form)

    def _render(self, request, form, status=200):
        from django.shortcuts import render

        return render(
            request,
            self.template_name,
            {"form": form, "step": 3, "total_steps": TOTAL_STEPS},
            status=status,
        )


class OnboardingStep4View(OnboardingBaseMixin, TemplateView):
    template_name = "onboarding/step4_done.html"

    # A conclusão deve permanecer visível após o onboarding ser concluído.
    allow_when_onboarded = True

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        # Resumo simples: a conta criada durante o onboarding (a mais recente).
        account = (
            Account.objects.for_user(self.request.user)
            .order_by("-created_at")
            .first()
        )
        ctx["account"] = account
        ctx["step"] = 4
        ctx["total_steps"] = TOTAL_STEPS
        return ctx


_STEP_VIEWS = {
    1: OnboardingStep1View,
    2: OnboardingStep2View,
    3: OnboardingStep3View,
    4: OnboardingStep4View,
}


def _onboarding_step_view(request, step):
    """Despacha para a view da etapa correspondente (1–4)."""
    view_cls = _STEP_VIEWS.get(step)
    if view_cls is None:
        from django.shortcuts import redirect

        messages.warning(request, "Etapa de onboarding não encontrada.")
        return redirect(reverse("accounts:onboarding_step", args=[1]))
    return view_cls.as_view()(request)
