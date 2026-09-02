"""Views do shell da aplicação autenticada.

A rota index renderiza o DASHBOARD com dados reais a partir do ViewModel
(ordem 7). As demais áreas continuam como placeholders estruturais.
"""

from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse
from django.views.generic import TemplateView

from apps.budgets.models import Budget
from apps.cards.models import CreditCard
from apps.finance.models import Account, Transaction
from apps.goals.models import Goal
from apps.reports.services import can_generate, latest_report, next_available_date

from .viewmodel import build_dashboard


def _first_steps(user) -> dict:
    """Checklist progressivo de primeiros passos para usuários em início de jornada."""
    has_account = Account.objects.for_user(user).exists()
    has_movement = Transaction.objects.for_user(user).exists()
    has_card = CreditCard.objects.for_user(user).exists()
    has_goal = Goal.objects.for_user(user).exists()
    has_budget = Budget.objects.for_user(user).exists()

    steps = [
        {
            "key": "conta",
            "label": "Cadastre sua primeira conta",
            "url": reverse("finance:account_create"),
            "done": has_account,
        },
        {
            "key": "movimento",
            "label": "Registre sua primeira despesa ou receita",
            "url": reverse("finance:transaction_create") + "?kind=expense",
            "done": has_movement,
        },
        {
            "key": "cartao",
            "label": "Adicione um cartão",
            "url": reverse("cards:card_create"),
            "done": has_card,
        },
        {
            "key": "meta",
            "label": "Defina uma meta",
            "url": reverse("goals:goal_create"),
            "done": has_goal,
        },
        {
            "key": "orcamento",
            "label": "Crie um orçamento",
            "url": reverse("budgets:budget_create"),
            "done": has_budget,
        },
    ]
    remaining = [s for s in steps if not s["done"]]
    done_count = len(steps) - len(remaining)
    # Só exibe enquanto o usuário ainda tem passos importantes a concluir.
    show = bool(remaining) and done_count < 4
    return {
        "steps": steps,
        "remaining": remaining,
        "done_count": done_count,
        "show": show,
        "progress": round(done_count * 100 / len(steps)),
    }


class DashboardIndexView(LoginRequiredMixin, TemplateView):
    """Página inicial da área autenticada — dashboard financeiro real."""

    template_name = "app/dashboard.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        user = self.request.user
        period = self.request.GET.get("period", "30d")
        account_id = self.request.GET.get("account") or None
        card_id = self.request.GET.get("card") or None

        if period not in ("7d", "30d", "3m", "6m", "12m"):
            period = "30d"

        ctx.update(
            build_dashboard(
                user,
                period=period,
                account_id=account_id,
                card_id=card_id,
            )
        )
        ctx["first_steps"] = _first_steps(user)
        ctx["dashboard"] = True
        ctx["ai_report_card"] = self._ai_report_card(user)
        return ctx

    def _ai_report_card(self, user) -> dict:
        """Informações do Relatório de Análise IA exibidas na dashboard."""
        report = latest_report(user)
        return {
            "latest": report,
            "has_report": report is not None,
            "generated_at": report.generated_at if report else None,
            "summary": report.summary if report else None,
            "via_ai": bool(report and report.via_ai),
            "can_generate": can_generate(user),
            "next_available": next_available_date(user),
        }


class AppPlaceholderView(LoginRequiredMixin, TemplateView):
    """Página estrutural de uma área ainda em construção (nav lateral)."""

    template_name = "app/placeholder.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        section = self.kwargs.get("section", "Área")
        titles = {
            "orcamentos": "Orçamentos",
            "metas": "Metas",
            "dividas": "Dívidas",
            "configuracoes": "Configurações",
        }
        ctx["section"] = titles.get(section, "Área")
        ctx["section_key"] = section
        return ctx
