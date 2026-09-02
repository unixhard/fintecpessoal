"""Views de dívidas.

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

from .forms import DebtForm, DebtPaymentForm
from .models import Debt
from .services import debts as debts_svc


class _OwnedDebtMixin(SingleObjectMixin):
    model = Debt
    permission_denied_message = "Recurso não encontrado."

    def get_object(self, queryset=None):
        obj = get_object_or_404(
            Debt.objects.for_user(self.request.user),
            pk=self.kwargs.get("pk"),
        )
        self.object = obj
        return obj


class DebtListView(LoginRequiredMixin, ListView):
    model = Debt
    template_name = "debts/debt_list.html"
    context_object_name = "debts"
    paginate_by = 20

    def get_queryset(self):
        return debts_svc.get_debts(user=self.request.user).order_by("name")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        user = self.request.user
        ctx["rows"] = [
            debts_svc.get_debt_progress(user=user, debt=d) for d in ctx["debts"]
        ]
        ctx["summary"] = debts_svc.get_debt_summary(user=user)
        return ctx


class DebtCreateView(LoginRequiredMixin, FormView):
    template_name = "debts/debt_form.html"
    form_class = DebtForm

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["title"] = "Nova dívida"
        return ctx

    def form_valid(self, form):
        debts_svc.create_debt(
            user=self.request.user,
            name=form.cleaned_data["name"],
            type=form.cleaned_data["type"],
            total_amount=form.cleaned_data["total_amount"],
            interest_rate=form.cleaned_data.get("interest_rate"),
            start_date=form.cleaned_data.get("start_date"),
            end_date=form.cleaned_data.get("end_date"),
            creditor=form.cleaned_data.get("creditor") or "",
        )
        messages.success(self.request, "Dívida criada.")
        return redirect(reverse("debts:debt_list"))

    def form_invalid(self, form):
        return self.render_to_response(self.get_context_data(form=form))


class DebtDetailView(LoginRequiredMixin, _OwnedDebtMixin, TemplateView):
    template_name = "debts/debt_detail.html"

    def get_context_data(self, **kwargs):
        user = self.request.user
        debt = self.get_object()
        progress = debts_svc.get_debt_progress(user=user, debt=debt)
        ctx = super().get_context_data(**kwargs)
        ctx.update(progress)
        ctx["pay_form"] = DebtPaymentForm(user=user) if debt.remaining_amount > 0 else None
        return ctx


class DebtEditView(LoginRequiredMixin, _OwnedDebtMixin, FormView):
    template_name = "debts/debt_form.html"
    form_class = DebtForm

    def get_context_data(self, **kwargs):
        self.get_object()
        ctx = super().get_context_data(**kwargs)
        ctx["title"] = "Editar dívida"
        return ctx

    def get_initial(self):
        debt = self.get_object()
        return {
            "name": debt.name,
            "type": debt.type,
            "total_amount": debt.total_amount,
            "interest_rate": debt.interest_rate,
            "start_date": debt.start_date,
            "end_date": debt.end_date,
            "creditor": debt.creditor,
        }

    def form_valid(self, form):
        debt = self.get_object()
        debts_svc.update_debt(
            user=self.request.user,
            debt=debt,
            name=form.cleaned_data["name"],
            total_amount=form.cleaned_data["total_amount"],
            type=form.cleaned_data["type"],
            interest_rate=form.cleaned_data.get("interest_rate"),
            start_date=form.cleaned_data.get("start_date"),
            end_date=form.cleaned_data.get("end_date"),
            creditor=form.cleaned_data.get("creditor") or "",
        )
        messages.success(self.request, "Dívida atualizada.")
        return redirect(reverse("debts:debt_detail", args=[debt.pk]))


class DebtPaymentView(LoginRequiredMixin, _OwnedDebtMixin, FormView):
    template_name = "debts/debt_detail.html"
    form_class = DebtPaymentForm

    def get_context_data(self, **kwargs):
        user = self.request.user
        debt = self.get_object()
        progress = debts_svc.get_debt_progress(user=user, debt=debt)
        ctx = super().get_context_data(**kwargs)
        ctx.update(progress)
        ctx["pay_form"] = kwargs.get("form") or DebtPaymentForm(user=user)
        ctx["payment_error"] = bool(kwargs.get("form"))
        return ctx

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    def form_valid(self, form):
        debt = self.get_object()
        try:
            debts_svc.record_debt_payment(
                user=self.request.user,
                debt=debt,
                account=form.cleaned_data["account"],
                amount=form.cleaned_data["amount"],
                date=form.cleaned_data["date"],
            )
            messages.success(self.request, "Pagamento registrado.")
        except Exception as exc:
            messages.error(self.request, str(exc) or "Não foi possível registrar o pagamento.")
        return redirect(reverse("debts:debt_detail", args=[debt.pk]))


class DebtStatusView(LoginRequiredMixin, View):
    """Marca como inadimplente ou reabre / arquiva uma dívida."""

    new_status = None
    label = ""

    def post(self, request, *args, **kwargs):
        debt = get_object_or_404(
            Debt.objects.for_user(request.user), pk=kwargs.get("pk")
        )
        debts_svc.set_debt_status(
            user=request.user, debt=debt, status=self.new_status
        )
        messages.success(request, f"Dívida {self.label}.")
        return redirect(reverse("debts:debt_list"))


class DebtDeleteView(LoginRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        debt = get_object_or_404(
            Debt.objects.for_user(request.user), pk=kwargs.get("pk")
        )
        debts_svc.delete_debt(user=request.user, debt=debt)
        messages.success(request, "Dívida excluída.")
        return redirect(reverse("debts:debt_list"))
