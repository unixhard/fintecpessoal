"""Views de cartão de crédito: cartões, compras e faturas.

Views coordenam `request -> form -> service -> redirect/render`, delegando
regras financeiras à camada de serviços (apps.cards.services), jamais às views.
Toda consulta é isolada por usuário via ``for_user``.
"""

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views import View
from django.views.generic import FormView, ListView, TemplateView
from django.views.generic.detail import SingleObjectMixin

from apps.cards.services import (
    cards as cards_svc,
    invoices as invoices_svc,
    purchases as purchases_svc,
    reads as reads_svc,
)

from .forms import CardCreateForm, CardEditForm, InvoicePayForm, PurchaseForm
from .models import CreditCard, CreditCardInvoice, InstallmentPurchase


class _OwnedCardMixin(SingleObjectMixin):
    model = CreditCard

    def get_object(self, queryset=None):
        obj = get_object_or_404(
            self.model.objects.for_user(self.request.user),
            pk=self.kwargs.get("pk"),
        )
        self.object = obj
        return obj


# --------------------------------------------------------------------------- #
# Cartões
# --------------------------------------------------------------------------- #


class CardListView(LoginRequiredMixin, ListView):
    model = CreditCard
    template_name = "cards/card_list.html"
    context_object_name = "cards"

    def get_queryset(self):
        return CreditCard.objects.for_user(self.request.user).select_related(
            "payment_account"
        ).order_by("-status", "name")


class CardDetailView(LoginRequiredMixin, _OwnedCardMixin, TemplateView):
    template_name = "cards/card_detail.html"

    def get_context_data(self, **kwargs):
        user = self.request.user
        card = self.get_object()
        ctx = super().get_context_data(**kwargs)
        ctx["card"] = card
        ctx.update(reads_svc.card_summary(user, card))
        invoices = (
            CreditCardInvoice.objects.for_user(user)
            .filter(card=card)
            .order_by("-due_date")
        )
        ctx["invoices"] = invoices[:12]
        purchases = (
            InstallmentPurchase.objects.for_user(user)
            .filter(card=card)
            .order_by("-first_due_date")
        )
        ctx["purchases"] = purchases[:12]
        return ctx


class CardCreateView(LoginRequiredMixin, FormView):
    template_name = "cards/card_form.html"
    form_class = CardCreateForm

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["title"] = "Novo cartão"
        return ctx

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    def form_valid(self, form):
        card = CreditCard.objects.create(
            owner=self.request.user,
            name=form.cleaned_data["name"],
            institution=form.cleaned_data.get("institution") or "",
            limit=form.cleaned_data.get("limit") or 0,
            closing_day=form.cleaned_data["closing_day"],
            due_day=form.cleaned_data["due_day"],
            payment_account=form.cleaned_data.get("payment_account"),
            status=CreditCard.Status.ACTIVE,
        )
        messages.success(self.request, "Cartão criado.")
        return redirect(reverse("cards:card_detail", args=[card.pk]))

    def form_invalid(self, form):
        return self.render_to_response(self.get_context_data(form=form))


class CardEditView(LoginRequiredMixin, _OwnedCardMixin, FormView):
    template_name = "cards/card_form.html"
    form_class = CardEditForm

    def get_context_data(self, **kwargs):
        self.get_object()
        ctx = super().get_context_data(**kwargs)
        ctx["title"] = "Editar cartão"
        return ctx

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    def get_initial(self):
        card = self.get_object()
        return {
            "name": card.name,
            "institution": card.institution,
            "limit": card.limit,
            "closing_day": card.closing_day,
            "due_day": card.due_day,
            "payment_account": card.payment_account,
        }

    def form_valid(self, form):
        card = self.get_object()
        cards_svc.update_card(
            user=self.request.user,
            card=card,
            name=form.cleaned_data["name"],
            institution=form.cleaned_data.get("institution") or "",
            limit=form.cleaned_data.get("limit") or 0,
            closing_day=form.cleaned_data["closing_day"],
            due_day=form.cleaned_data["due_day"],
            payment_account=form.cleaned_data.get("payment_account"),
        )
        messages.success(self.request, "Cartão atualizado.")
        return redirect(reverse("cards:card_detail", args=[card.pk]))


class CardStatusView(LoginRequiredMixin, View):
    """Bloqueia, fecha ou reativa um cartão."""

    new_status = None

    def post(self, request, *args, **kwargs):
        card = get_object_or_404(
            CreditCard.objects.for_user(request.user), pk=kwargs.get("pk")
        )
        cards_svc.set_card_status(
            user=request.user, card=card, status=self.new_status
        )
        labels = {
            CreditCard.Status.ACTIVE: "ativado",
            CreditCard.Status.BLOCKED: "bloqueado",
            CreditCard.Status.CLOSED: "fechado",
        }
        messages.success(request, f"Cartão {labels.get(self.new_status, 'atualizado')}.")
        return redirect(reverse("cards:card_list"))


# --------------------------------------------------------------------------- #
# Compras
# --------------------------------------------------------------------------- #


class PurchaseCreateView(LoginRequiredMixin, FormView):
    template_name = "cards/purchase_form.html"
    form_class = PurchaseForm

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["title"] = "Nova compra no cartão"
        return ctx

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    def form_valid(self, form):
        purchases_svc.create_card_purchase(
            user=self.request.user,
            card=form.cleaned_data["card"],
            description=form.cleaned_data["description"],
            total_amount=form.cleaned_data["total_amount"],
            installment_count=form.cleaned_data["installment_count"],
            first_due_date=form.cleaned_data["first_due_date"],
        )
        messages.success(self.request, "Compra registrada no cartão.")
        return redirect(reverse("cards:purchase_list"))

    def form_invalid(self, form):
        return self.render_to_response(self.get_context_data(form=form))


class PurchaseListView(LoginRequiredMixin, ListView):
    model = InstallmentPurchase
    template_name = "cards/purchase_list.html"
    context_object_name = "purchases"
    paginate_by = 20

    def get_queryset(self):
        return InstallmentPurchase.objects.for_user(self.request.user).select_related(
            "card"
        ).order_by("-first_due_date")


# --------------------------------------------------------------------------- #
# Faturas
# --------------------------------------------------------------------------- #


class InvoiceListView(LoginRequiredMixin, ListView):
    model = CreditCardInvoice
    template_name = "cards/invoice_list.html"
    context_object_name = "invoices"

    def get_queryset(self):
        return CreditCardInvoice.objects.for_user(self.request.user).select_related(
            "card"
        ).order_by("due_date")


class InvoiceDetailView(LoginRequiredMixin, View):
    def get(self, request, *args, **kwargs):
        invoice = get_object_or_404(
            CreditCardInvoice.objects.for_user(request.user), pk=kwargs.get("pk")
        )
        installments = (
            invoice.installments.select_related("purchase").order_by("due_date")
        )
        pay_form = InvoicePayForm(user=request.user)
        ctx = {
            "invoice": invoice,
            "installments": installments,
            "pay_form": pay_form,
            "cards_active_nav": True,
        }
        return render(request, "cards/invoice_detail.html", ctx)


class InvoicePayView(LoginRequiredMixin, FormView):
    template_name = "cards/invoice_detail.html"
    form_class = InvoicePayForm

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        invoice = get_object_or_404(
            CreditCardInvoice.objects.for_user(self.request.user),
            pk=self.kwargs.get("pk"),
        )
        ctx["invoice"] = invoice
        ctx["installments"] = invoice.installments.select_related("purchase").order_by(
            "due_date"
        )
        ctx["pay_form"] = kwargs.get("form") or InvoicePayForm(user=self.request.user)
        return ctx

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    def form_valid(self, form):
        invoice = get_object_or_404(
            CreditCardInvoice.objects.for_user(self.request.user),
            pk=self.kwargs.get("pk"),
        )
        try:
            invoices_svc.pay_invoice(
                user=self.request.user,
                invoice=invoice,
                account=form.cleaned_data["account"],
                date=form.cleaned_data["date"],
            )
            messages.success(self.request, "Fatura paga com sucesso.")
        except Exception as exc:
            messages.error(self.request, str(exc) or "Não foi possível pagar a fatura.")
            return self.render_to_response(self.get_context_data(form=form))
        return redirect(reverse("cards:invoice_detail", args=[invoice.pk]))

    def form_invalid(self, form):
        return self.render_to_response(self.get_context_data(form=form))
