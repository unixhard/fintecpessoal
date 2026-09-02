"""Views de orçamentos.

Convenção do projeto: views coordenam `request -> form -> service ->
redirect/render`. Nenhuma regra financeira vive aqui. Ownership é garantido
pelo mixin (consulta com ``for_user``) e pelos services.
"""

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect, reverse
from django.views import View
from django.views.generic import FormView, ListView, TemplateView
from django.views.generic.detail import SingleObjectMixin

from .forms import BudgetForm
from .models import Budget
from .services import budgets as budgets_svc


class _OwnedBudgetMixin(SingleObjectMixin):
    model = Budget
    permission_denied_message = "Recurso não encontrado."

    def get_object(self, queryset=None):
        obj = get_object_or_404(
            Budget.objects.for_user(self.request.user),
            pk=self.kwargs.get("pk"),
        )
        self.object = obj
        return obj


class BudgetListView(LoginRequiredMixin, ListView):
    model = Budget
    template_name = "budgets/budget_list.html"
    context_object_name = "budgets"
    paginate_by = 20

    def get_queryset(self):
        qs = Budget.objects.for_user(self.request.user).select_related("category")
        active_only = self.request.GET.get("all") != "1"
        if active_only:
            qs = qs.filter(is_active=True)
        return qs.order_by("kind", "id")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        user = self.request.user
        rows = [
            budgets_svc.get_budget_progress(user=user, budget=b) for b in ctx["budgets"]
        ]
        ctx["rows"] = rows
        ctx["summary"] = budgets_svc.get_budget_summary(user=user)
        ctx["show_all"] = self.request.GET.get("all") == "1"
        return ctx


class BudgetCreateView(LoginRequiredMixin, FormView):
    template_name = "budgets/budget_form.html"
    form_class = BudgetForm

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["title"] = "Novo orçamento"
        return ctx

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    def form_valid(self, form):
        budgets_svc.create_budget(
            user=self.request.user,
            kind=form.cleaned_data["kind"],
            limit_amount=form.cleaned_data["limit_amount"],
            period=form.cleaned_data["period"],
            category=form.cleaned_data.get("category"),
            start_date=form.cleaned_data.get("start_date"),
            end_date=form.cleaned_data.get("end_date"),
            is_active=form.cleaned_data.get("is_active", True),
        )
        messages.success(self.request, "Orçamento criado.")
        return redirect(reverse("budgets:budget_list"))

    def form_invalid(self, form):
        return self.render_to_response(self.get_context_data(form=form))


class BudgetDetailView(LoginRequiredMixin, _OwnedBudgetMixin, TemplateView):
    template_name = "budgets/budget_detail.html"

    def get_context_data(self, **kwargs):
        user = self.request.user
        budget = self.get_object()
        progress = budgets_svc.get_budget_progress(user=user, budget=budget)
        ctx = super().get_context_data(**kwargs)
        ctx.update(progress)
        return ctx


class BudgetEditView(LoginRequiredMixin, _OwnedBudgetMixin, FormView):
    template_name = "budgets/budget_form.html"
    form_class = BudgetForm

    def get_context_data(self, **kwargs):
        self.get_object()
        ctx = super().get_context_data(**kwargs)
        ctx["title"] = "Editar orçamento"
        return ctx

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    def get_initial(self):
        budget = self.get_object()
        return {
            "kind": budget.kind,
            "category": budget.category,
            "period": budget.period,
            "limit_amount": budget.limit_amount,
            "start_date": budget.start_date,
            "end_date": budget.end_date,
            "is_active": budget.is_active,
        }

    def form_valid(self, form):
        budget = self.get_object()
        budgets_svc.update_budget(
            user=self.request.user,
            budget=budget,
            kind=form.cleaned_data["kind"],
            limit_amount=form.cleaned_data["limit_amount"],
            period=form.cleaned_data["period"],
            category=form.cleaned_data.get("category"),
            start_date=form.cleaned_data.get("start_date"),
            end_date=form.cleaned_data.get("end_date"),
            is_active=form.cleaned_data.get("is_active", True),
        )
        messages.success(self.request, "Orçamento atualizado.")
        return redirect(reverse("budgets:budget_detail", args=[budget.pk]))


class BudgetToggleView(LoginRequiredMixin, View):
    """Ativa/inativa um orçamento via services."""

    def post(self, request, *args, **kwargs):
        budget = get_object_or_404(
            Budget.objects.for_user(request.user), pk=kwargs.get("pk")
        )
        new_state = not budget.is_active
        budgets_svc.update_budget(
            user=request.user, budget=budget, is_active=new_state
        )
        label = "ativado" if new_state else "inativado"
        messages.success(request, f"Orçamento {label}.")
        return redirect(reverse("budgets:budget_list"))


class BudgetDeleteView(LoginRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        budget = get_object_or_404(
            Budget.objects.for_user(request.user), pk=kwargs.get("pk")
        )
        budgets_svc.delete_budget(user=request.user, budget=budget)
        messages.success(request, "Orçamento excluído.")
        return redirect(reverse("budgets:budget_list"))
