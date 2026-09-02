"""Views de metas financeiras.

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

from .forms import GoalContributionForm, GoalForm
from .models import Goal
from .services import goals as goals_svc


class _OwnedGoalMixin(SingleObjectMixin):
    model = Goal
    permission_denied_message = "Recurso não encontrado."

    def get_object(self, queryset=None):
        obj = get_object_or_404(
            Goal.objects.for_user(self.request.user),
            pk=self.kwargs.get("pk"),
        )
        self.object = obj
        return obj


class GoalListView(LoginRequiredMixin, ListView):
    model = Goal
    template_name = "goals/goal_list.html"
    context_object_name = "goals"
    paginate_by = 20

    def get_queryset(self):
        statuses = None if self.request.GET.get("all") == "1" else None
        return goals_svc.get_goals(user=self.request.user).order_by(
            "-priority", "target_date", "name"
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        user = self.request.user
        ctx["rows"] = [
            goals_svc.get_goal_progress(user=user, goal=g) for g in ctx["goals"]
        ]
        ctx["summary"] = goals_svc.get_goal_summary(user=user)
        return ctx


class GoalCreateView(LoginRequiredMixin, FormView):
    template_name = "goals/goal_form.html"
    form_class = GoalForm

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["title"] = "Nova meta"
        return ctx

    def form_valid(self, form):
        goals_svc.create_goal(
            user=self.request.user,
            name=form.cleaned_data["name"],
            target_amount=form.cleaned_data["target_amount"],
            target_date=form.cleaned_data.get("target_date"),
            priority=form.cleaned_data["priority"],
            notes=form.cleaned_data.get("notes") or "",
        )
        messages.success(self.request, "Meta criada.")
        return redirect(reverse("goals:goal_list"))

    def form_invalid(self, form):
        return self.render_to_response(self.get_context_data(form=form))


class GoalDetailView(LoginRequiredMixin, _OwnedGoalMixin, TemplateView):
    template_name = "goals/goal_detail.html"

    def get_context_data(self, **kwargs):
        user = self.request.user
        goal = self.get_object()
        progress = goals_svc.get_goal_progress(user=user, goal=goal)
        ctx = super().get_context_data(**kwargs)
        ctx.update(progress)
        ctx["contribution_form"] = GoalContributionForm()
        return ctx


class GoalEditView(LoginRequiredMixin, _OwnedGoalMixin, FormView):
    template_name = "goals/goal_form.html"
    form_class = GoalForm

    def get_context_data(self, **kwargs):
        self.get_object()
        ctx = super().get_context_data(**kwargs)
        ctx["title"] = "Editar meta"
        return ctx

    def get_initial(self):
        goal = self.get_object()
        return {
            "name": goal.name,
            "target_amount": goal.target_amount,
            "target_date": goal.target_date,
            "priority": goal.priority,
            "notes": goal.notes,
        }

    def form_valid(self, form):
        goal = self.get_object()
        goals_svc.update_goal(
            user=self.request.user,
            goal=goal,
            name=form.cleaned_data["name"],
            target_amount=form.cleaned_data["target_amount"],
            target_date=form.cleaned_data.get("target_date"),
            priority=form.cleaned_data["priority"],
            notes=form.cleaned_data.get("notes") or "",
        )
        messages.success(self.request, "Meta atualizada.")
        return redirect(reverse("goals:goal_detail", args=[goal.pk]))


class GoalContributionView(LoginRequiredMixin, _OwnedGoalMixin, FormView):
    template_name = "goals/goal_detail.html"
    form_class = GoalContributionForm

    def get_context_data(self, **kwargs):
        user = self.request.user
        goal = self.get_object()
        progress = goals_svc.get_goal_progress(user=user, goal=goal)
        ctx = super().get_context_data(**kwargs)
        ctx.update(progress)
        ctx["contribution_form"] = kwargs.get("form") or GoalContributionForm()
        ctx["contribution_error"] = bool(kwargs.get("form"))
        return ctx

    def form_valid(self, form):
        goal = self.get_object()
        try:
            goals_svc.add_goal_contribution(
                user=self.request.user,
                goal=goal,
                amount=form.cleaned_data["amount"],
            )
            messages.success(self.request, "Aporte registrado.")
        except Exception as exc:
            messages.error(self.request, str(exc) or "Não foi possível registrar o aporte.")
        return redirect(reverse("goals:goal_detail", args=[goal.pk]))


class GoalStatusView(LoginRequiredMixin, View):
    """Pausa, reativa ou arquiva uma meta."""

    new_status = None
    label = ""

    def post(self, request, *args, **kwargs):
        goal = get_object_or_404(
            Goal.objects.for_user(request.user), pk=kwargs.get("pk")
        )
        goals_svc.set_goal_status(user=request.user, goal=goal, status=self.new_status)
        messages.success(request, f"Meta {self.label}.")
        return redirect(reverse("goals:goal_list"))


class GoalDeleteView(LoginRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        goal = get_object_or_404(
            Goal.objects.for_user(request.user), pk=kwargs.get("pk")
        )
        goals_svc.delete_goal(user=request.user, goal=goal)
        messages.success(request, "Meta excluída.")
        return redirect(reverse("goals:goal_list"))
