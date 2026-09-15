"""Onboarding + Tutorial completo do app (7 etapas) — "Seu CFO te guia".

Leva o usuário de "criei minha conta" até "dominei o app". A criação da
primeira conta financeira delega para o serviço
`apps.finance.services.accounts.create_account`; este módulo apenas coordena
as etapas e o estado `Profile.onboarding_completed` (fonte de verdade ÚNICA —
nenhum estado duplicado em sessão).

Etapas:
  1. Boas-vindas + mapa do tutorial       (posicionamento do CFO de bolso)
  2. Perfil (display_name)
  3. Primeira conta financeira (via service — NÃO conclui)
  4. Módulo "Seu dia a dia"  (movimentações, Assistente, categorias, recorrências)
  5. Módulo "Planejamento e Cartões" (cartões/faturas, orçamentos, metas, dívidas)
  6. Módulo "Inteligência"    (relatório IA, patrimônio, lembretes, imports…)
  7. Checklist mestre + plano dos primeiros 7 dias → conclui o onboarding

As etapas 4–7 ficam acessíveis depois da conclusão (tutorial "Como usar").
"""

from django import forms
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views import View
from django.views.generic import TemplateView

from decimal import Decimal

from apps.core.forms import BRLInput
from apps.core.money import parse_money_to_cents

from apps.finance.models import Account
from apps.finance.services.accounts import create_account
from apps.finance.services.categories import seed_default_categories

TOTAL_STEPS = 7

# Etapas que permanecem acessíveis após a conclusão (tutorial "Como usar").
TUTORIAL_STEPS = (4, 5, 6, 7)


def _redirect_post_onboarding(user):
    """Retorna o destino padrão: aplicação (onboarding já concluído)."""
    return redirect(reverse("dashboard:index"))


def _user_onboarded(user):
    return getattr(getattr(user, "profile", None), "onboarding_completed", False)


def _step_url(step: int) -> str:
    return reverse("accounts:onboarding_step", args=[step])


class OnboardingBaseMixin(LoginRequiredMixin):
    """Garante autenticação e desvia usuários que já concluíram o onboarding.

    As etapas de tutorial (4–7) podem permanecer acessíveis após a conclusão
    via ``allow_when_onboarded``.
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

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["step"] = 1
        ctx["total_steps"] = TOTAL_STEPS
        return ctx


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

    widget = BRLInput

    default_error_messages = {
        "invalid": "Informe um valor monetário válido (ex.: 1.500,00).",
        "negative": "O saldo inicial não pode ser negativo.",
    }

    def to_python(self, value):
        if value in self.empty_values:
            return 0
        if isinstance(value, (int, Decimal)) and not isinstance(value, bool):
            value = str(value)
        if not isinstance(value, str):
            raise forms.ValidationError(self.error_messages["invalid"], code="invalid")
        value = value.strip()
        if not value:
            return 0
        cents = parse_money_to_cents(value)
        if cents is None:
            raise forms.ValidationError(self.error_messages["invalid"], code="invalid")
        return cents

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
        widget=BRLInput(attrs={"placeholder": "0,00"}),
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
            # Taxonomia padrão (Ordem 18/FASE 3): semeia as categorias base
            # quando o usuário realmente começa a usar a plataforma.
            seed_default_categories(user=request.user)
            messages.success(
                request,
                "Primeira conta cadastrada. Agora vamos te mostrar como o app funciona na prática.",
            )
            return redirect(reverse("accounts:onboarding_step", args=[4]))
        return self._render(request, form)

    def _render(self, request, form, status=200):
        return render(
            request,
            self.template_name,
            {"form": form, "step": 3, "total_steps": TOTAL_STEPS},
            status=status,
        )


# --------------------------------------------------------------------------- #
# Módulos do tutorial (etapas 4–6) e checklist mestre (etapa 7)
# --------------------------------------------------------------------------- #

# Cada card: título, explicação "simples como para uma criança", ação.
_TUTORIAL_CONTENT = {
    4: {
        "eyebrow": "Etapa 4 de 7 · Seu dia a dia",
        "heading": "Dinheiro que entra e dinheiro que sai",
        "subtitle": (
            "Essa é a base de tudo: registrar o que acontece com o seu dinheiro. "
            "Fica mais fácil do que parece — e o app faz boa parte por você."
        ),
        "cards": [
            {
                "title": "Movimentações",
                "text": (
                    "Todo dinheiro que entra ou sai é uma movimentação. "
                    "Você cria uma em menos de 1 minuto e ela vira parte do seu painel."
                ),
                "url": lambda request: reverse("finance:transaction_create"),
                "action": "Criar movimentação",
            },
            {
                "title": "Assistente Fintec",
                "text": (
                    "Escreva uma frase e ele cria o lançamento pra você — "
                    "ex.: “Gastei 58 no Uber”. Entende valor, data e já sugere a categoria."
                ),
                "url": None,
                "action": "Abre no app (botão “Nova Transação”)",
            },
            {
                "title": "Categorias (automáticas)",
                "text": (
                    "Cada gasto recebe uma categoria sozinho. Na fila de revisão "
                    "você confere e acerta tudo com poucos cliques."
                ),
                "url": lambda request: reverse("finance:review_queue"),
                "action": "Ver fila de revisão",
            },
            {
                "title": "Recorrências",
                "text": (
                    "Salário, aluguel, internet: coisas que se repetem todo mês "
                    "você cadastra UMA vez e o app lembra sozinho."
                ),
                "url": lambda request: reverse("finance:recurring_list"),
                "action": "Ver recorrências",
            },
            {
                "title": "Transferências",
                "text": (
                    "Mudou dinheiro entre suas contas? Registre como transferência "
                    "para não contar o mesmo dinheiro duas vezes."
                ),
                "url": lambda request: reverse("finance:transfer_create"),
                "action": "Criar transferência",
            },
        ],
        "tip": (
            "Dica de mestre: registre tudo numa vez só no fim do dia (5 minutos). "
            "O mesmo horário, todos os dias, vira um hábito que dura."
        ),
    },
    5: {
        "eyebrow": "Etapa 5 de 7 · Planejamento e Cartões",
        "heading": "Seus cartões e os seus planos",
        "subtitle": (
            "Aqui você liga o crédito ao seu controle: fatura, parcelas, "
            "orçamentos, metas e dívidas em um só lugar."
        ),
        "cards": [
            {
                "title": "Cartões e faturas",
                "text": (
                    "Adicione seus cartões e veja limite, valor da fatura e "
                    "a data em que ela vence — antes do susto, não depois."
                ),
                "url": lambda request: reverse("cards:card_create"),
                "action": "Adicionar cartão",
            },
            {
                "title": "Compras parceladas",
                "text": (
                    "Uma compra no crédito pode virar várias parcelas. "
                    "O app mostra o total e quanto ainda falta pagar."
                ),
                "url": lambda request: reverse("cards:purchase_list"),
                "action": "Ver compras",
            },
            {
                "title": "Orçamentos",
                "text": (
                    "Escolha quanto você pode gastar em cada categoria e receba "
                    "alerta ANTES de estourar, não depois."
                ),
                "url": lambda request: reverse("budgets:budget_create"),
                "action": "Criar orçamento",
            },
            {
                "title": "Metas",
                "text": (
                    "Quer uma viagem, uma reserva ou ficar mais tranquilo? "
                    "As metas mostram sua chegada a cada passo do caminho."
                ),
                "url": lambda request: reverse("goals:goal_create"),
                "action": "Criar meta",
            },
            {
                "title": "Dívidas",
                "text": (
                    "O que você deve, em parcelas e com data: registrar a dívida "
                    "é o primeiro passo para quitar sem ansiedade."
                ),
                "url": lambda request: reverse("debts:debt_create"),
                "action": "Registrar dívida",
            },
        ],
        "tip": (
            "Dica de mestre: comece com UM orçamento pequeno (uma só categoria) "
            "e UMA meta pequena, como R$ 100. Pequenos ganhos geram hábitos."
        ),
    },
    6: {
        "eyebrow": "Etapa 6 de 7 · Inteligência",
        "heading": "O poder da IA e da organização",
        "subtitle": (
            "Chega de adivinhar onde está seu dinheiro. Seu CFO, o patrimônio, "
            "os lembretes e o time de organização trabalham pra você."
        ),
        "cards": [
            {
                "title": "Relatório do seu CFO",
                "text": (
                    "A IA lê o resumo das suas finanças e escreve um relatório "
                    "com diagnóstico e plano de ação. Disponível a cada 3 dias."
                ),
                "url": lambda request: reverse("reports:ai_report"),
                "action": "Gerar relatório",
            },
            {
                "title": "Patrimônio",
                "text": (
                    "Tudo que você tem, menos o que você deve: é aqui que você "
                    "vê seu patrimônio (net worth) crescer."
                ),
                "url": lambda request: reverse("networth:index"),
                "action": "Ver patrimônio",
            },
            {
                "title": "Lembretes",
                "text": (
                    "As contas dos próximos 30 dias, em um só lugar. "
                    "Esqueceu de pagar? Não no seu controle."
                ),
                "url": lambda request: reverse("reminders:index"),
                "action": "Ver lembretes",
            },
            {
                "title": "Importar lançamentos",
                "text": (
                    "Tem uma planilha ou extrato pronto? Importe em lote "
                    "em vez de digitar um por um."
                ),
                "url": lambda request: reverse("imports:import_upload"),
                "action": "Importar",
            },
            {
                "title": "Comprovantes",
                "text": (
                    "Guarde a foto do comprovante junto do lançamento. "
                    "A leitura é automática: foto vira lançamento."
                ),
                "url": lambda request: reverse("comprovantes:list"),
                "action": "Ver comprovantes",
            },
            {
                "title": "Backup e privacidade",
                "text": (
                    "Seus dados são seus. Exporte um backup quando quiser — "
                    "nada de ficar refém de uma senha."
                ),
                "url": lambda request: reverse("settings:backup_export"),
                "action": "Exportar backup",
            },
        ],
        "tip": (
            "Dica de mestre: uma vez por semana, gere o relatório e pergunte ao "
            "seu CFO no painel: “O que devo priorizar?”"
        ),
    },
}

_MASTERY_CHECKLIST = [
    "Registrar entradas e saídas (até pelo Assistente Fintec)",
    "Vincular cartões, faturas e parcelas",
    "Definir orçamentos e metas com alertas",
    "Manter dívidas registradas e em dia",
    "Usar o Relatório do CFO, Patrimônio e Lembretes",
    "Importar, guardar comprovantes e fazer backup",
]

_DAILY_PLAN = [
    ("Dia 1", "Registrar todos os gastos e receitas de hoje"),
    ("Dia 2", "Conferir a fila de revisão e acertar categorias"),
    ("Dia 3", "Adicionar seus cartões e conferir a fatura"),
    ("Dia 4", "Criar um orçamento simples de uma categoria"),
    ("Dia 5", "Criar uma meta pequena e separar R$ 100"),
    ("Dia 6", "Gerar o primeiro Relatório do seu CFO"),
    ("Dia 7", "Ver o Patrimônio e agendar o lembrete semanal"),
]


class _TutorialModuleView(OnboardingBaseMixin, TemplateView):
    """Etapas 4–6: módulos do tutorial (acessíveis também após conclusão)."""

    template_name = "onboarding/step_module.html"
    allow_when_onboarded = True
    module_step = 4

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        step = self.module_step
        content = _TUTORIAL_CONTENT[step]
        ctx.update(
            {
                "step": step,
                "total_steps": TOTAL_STEPS,
                "eyebrow": content["eyebrow"],
                "heading": content["heading"],
                "subtitle": content["subtitle"],
                "cards": [
                    {
                        "title": c["title"],
                        "text": c["text"],
                        "url": c["url"](self.request) if c["url"] else None,
                        "action": c["action"],
                    }
                    for c in content["cards"]
                ],
                "tip": content["tip"],
                "prev_step": _step_url(step - 1),
                "next_step": _step_url(step + 1),
                "is_last": False,
            }
        )
        return ctx


class OnboardingStep4View(_TutorialModuleView):
    module_step = 4


class OnboardingStep5View(_TutorialModuleView):
    module_step = 5


class OnboardingStep6View(_TutorialModuleView):
    module_step = 6


class OnboardingStep7View(OnboardingBaseMixin, View):
    """Checklist mestre + plano dos primeiros 7 dias — conclui o onboarding.

    A conclusão só acontece aqui (POST "Concluir"), quando o usuário caminhou
    por todo o tutorial. Continua acessível depois (tutorial "Como usar").
    """

    template_name = "onboarding/step7_mastery.html"
    allow_when_onboarded = True

    def get(self, request, *args, **kwargs):
        return render(
            request,
            self.template_name,
            {
                "step": 7,
                "total_steps": TOTAL_STEPS,
                "prev_step": _step_url(6),
                "checklist": _MASTERY_CHECKLIST,
                "daily_plan": _DAILY_PLAN,
            },
        )

    def post(self, request, *args, **kwargs):
        profile = request.user.profile
        if not profile.onboarding_completed:
            profile.onboarding_completed = True
            profile.save(update_fields=["onboarding_completed"])
        messages.success(
            request,
            "Pronto! Seu CFO está de plantão — a plataforma inteira é sua.",
        )
        return _redirect_post_onboarding(request.user)


def tutorial(request):
    """Rota amigável do tutorial completo (sempre acessível após concluir)."""
    return redirect(reverse("accounts:onboarding_step", args=[4]))


_STEP_VIEWS = {
    1: OnboardingStep1View,
    2: OnboardingStep2View,
    3: OnboardingStep3View,
    4: OnboardingStep4View,
    5: OnboardingStep5View,
    6: OnboardingStep6View,
    7: OnboardingStep7View,
}


def _onboarding_step_view(request, step):
    """Despacha para a view da etapa correspondente (1–7)."""
    view_cls = _STEP_VIEWS.get(step)
    if view_cls is None:
        messages.warning(request, "Etapa de onboarding não encontrada.")
        return redirect(reverse("accounts:onboarding_step", args=[1]))
    return view_cls.as_view()(request)