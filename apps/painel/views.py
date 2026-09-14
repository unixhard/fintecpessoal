"""Views do Painel do Dono — administração, telemetria, vendas e relatórios.

Acesso restrito a ``is_superuser`` (o dono da plataforma). As leituras usam
as agregações baratas de ``apps.painel.services``.
"""

import json

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.mixins import UserPassesTestMixin
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View
from django.views.generic import TemplateView

from . import services
from .forms import (
    AccessCodeForm,
    CouponForm,
    GrantSubscriptionForm,
    MonetizationForm,
    PlanForm,
    RecordPaymentForm,
)
from .models import AccessCode, Coupon, Payment, Plan, Subscription

User = get_user_model()


class SuperuserRequiredMixin(UserPassesTestMixin):
    def test_func(self):
        user = self.request.user
        return bool(user.is_authenticated and user.is_superuser)


# --------------------------------------------------------------------------- #
# Dashboard do painel (expandido)
# --------------------------------------------------------------------------- #

class PanelIndexView(SuperuserRequiredMixin, TemplateView):
    template_name = "painel/index.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        days = max(int(self.request.GET.get("days", 30)), 1)
        ctx["days"] = days
        ctx["overview"] = services.overview(days=days)
        ctx["top_features"] = services.top_features(days=days)
        ctx["top_users"] = services.top_users(days=days)
        ctx["daily_series"] = services.daily_series(days=days)
        ctx["monetization"] = services.monetization()
        ctx["revenue"] = services.revenue_summary(days=days)
        ctx["mrr"] = services.mrr()
        ctx["arr"] = services.arr()
        ctx["conversion"] = services.conversion_rate()
        ctx["churn"] = services.churn_rate(days=days)
        return ctx


# --------------------------------------------------------------------------- #
# Usuários
# --------------------------------------------------------------------------- #

class UserListView(SuperuserRequiredMixin, View):
    template_name = "painel/user_list.html"

    def get(self, request):
        q = request.GET.get("q", "").strip()
        status = request.GET.get("status", "")
        qs = User.objects.all()
        if q:
            qs = qs.filter(
                Q(username__icontains=q)
                | Q(email__icontains=q)
                | Q(first_name__icontains=q)
                | Q(last_name__icontains=q)
            )
        if status == "paying":
            qs = qs.filter(is_paying=True)
        elif status == "inactive":
            qs = qs.filter(is_active=False)
        qs = qs.order_by("-date_joined")
        paginator = Paginator(qs, 25)
        page = paginator.get_page(request.GET.get("page"))
        return render(
            request, self.template_name,
            {"users": page, "q": q, "status": status, "paginator": paginator},
        )


class UserDetailView(SuperuserRequiredMixin, View):
    template_name = "painel/user_detail.html"

    def get(self, request, pk):
        user = get_object_or_404(User, pk=pk)
        sub = services.user_subscription(user)
        payments = services.user_payments(user)
        ctx = {
            "target": user,
            "summary": services.user_activity_summary(user),
            "features": services.user_feature_breakdown(user),
            "recent_events": _recent_events(user),
            "subscription": sub,
            "payments": payments,
            "ltv": services.user_ltv(user),
            "plans": list(Plan.objects.filter(is_active=True)),
        }
        return render(request, self.template_name, ctx)


class UserToggleView(SuperuserRequiredMixin, View):
    def post(self, request, pk, field):
        if field not in ("is_active", "is_paying", "staff"):
            return JsonResponse({"error": "invalid"}, status=400)
        user = get_object_or_404(User, pk=pk)
        attr = {"is_active": "is_active", "is_paying": "is_paying", "staff": "is_staff"}[field]
        current = getattr(user, attr)
        if field == "staff":
            user.is_staff = not current
            user.is_superuser = user.is_staff
        else:
            setattr(user, attr, not current)
        user.save(update_fields=[attr, "is_superuser"] if field == "staff" else [attr])
        messages.success(request, "Usuário atualizado.")
        return redirect("painel:user_detail", pk=pk)


# --------------------------------------------------------------------------- #
# Planos
# --------------------------------------------------------------------------- #

class PlanListView(SuperuserRequiredMixin, View):
    template_name = "painel/plan_list.html"

    def get(self, request):
        plans = list(Plan.objects.all())
        return render(request, self.template_name, {"plans": plans})


class PlanCreateView(SuperuserRequiredMixin, View):
    template_name = "painel/plan_form.html"

    def get(self, request):
        return render(request, self.template_name, {"form": PlanForm()})

    def post(self, request):
        form = PlanForm(request.POST)
        if form.is_valid():
            plan = form.save()
            messages.success(request, f"Plano '{plan.name}' criado.")
            return redirect("painel:plan_list")
        return render(request, self.template_name, {"form": form})


class PlanEditView(SuperuserRequiredMixin, View):
    template_name = "painel/plan_form.html"

    def get(self, request, pk):
        plan = get_object_or_404(Plan, pk=pk)
        return render(request, self.template_name, {"form": PlanForm(instance=plan), "plan": plan})

    def post(self, request, pk):
        plan = get_object_or_404(Plan, pk=pk)
        form = PlanForm(request.POST, instance=plan)
        if form.is_valid():
            form.save()
            messages.success(request, f"Plano '{plan.name}' atualizado.")
            return redirect("painel:plan_list")
        return render(request, self.template_name, {"form": form, "plan": plan})


class PlanToggleView(SuperuserRequiredMixin, View):
    def post(self, request, pk):
        plan = get_object_or_404(Plan, pk=pk)
        plan.is_active = not plan.is_active
        plan.save(update_fields=["is_active"])
        messages.success(request, f"Plano {plan.name} {'ativado' if plan.is_active else 'desativado'}.")
        return redirect("painel:plan_list")


# --------------------------------------------------------------------------- #
# Cupons
# --------------------------------------------------------------------------- #

class CouponListView(SuperuserRequiredMixin, View):
    template_name = "painel/coupon_list.html"

    def get(self, request):
        coupons = list(Coupon.objects.all())
        return render(request, self.template_name, {"coupons": coupons})


class CouponCreateView(SuperuserRequiredMixin, View):
    template_name = "painel/coupon_form.html"

    def get(self, request):
        return render(request, self.template_name, {"form": CouponForm()})

    def post(self, request):
        form = CouponForm(request.POST)
        if form.is_valid():
            coupon = form.save()
            messages.success(request, f"Cupom '{coupon.code}' criado.")
            return redirect("painel:coupon_list")
        return render(request, self.template_name, {"form": form})


class CouponToggleView(SuperuserRequiredMixin, View):
    def post(self, request, pk):
        coupon = get_object_or_404(Coupon, pk=pk)
        coupon.is_active = not coupon.is_active
        coupon.save(update_fields=["is_active"])
        messages.success(request, f"Cupom {coupon.code} {'ativado' if coupon.is_active else 'desativado'}.")
        return redirect("painel:coupon_list")


# --------------------------------------------------------------------------- #
# Assinaturas
# --------------------------------------------------------------------------- #

class SubscriptionListView(SuperuserRequiredMixin, View):
    template_name = "painel/subscription_list.html"

    def get(self, request):
        status = request.GET.get("status", "")
        qs = Subscription.objects.select_related("user", "plan").all()
        if status:
            qs = qs.filter(status=status)
        paginator = Paginator(qs.order_by("-created_at"), 25)
        page = paginator.get_page(request.GET.get("page"))
        return render(request, self.template_name, {"page": page, "status": status})


class SubscriptionGrantView(SuperuserRequiredMixin, View):
    def post(self, request, pk):
        user = get_object_or_404(User, pk=pk)
        form = GrantSubscriptionForm(request.POST)
        if form.is_valid():
            sub = services.grant_subscription(
                user, form.cleaned_data["plan"],
                notes=form.cleaned_data.get("notes", ""),
            )
            messages.success(request, f"Assinatura criada: {sub.plan}.")
        return redirect("painel:user_detail", pk=pk)


class SubscriptionCancelView(SuperuserRequiredMixin, View):
    def post(self, request, pk):
        sub = get_object_or_404(Subscription, pk=pk)
        services.cancel_subscription(sub)
        messages.success(request, "Assinatura cancelada.")
        return redirect("painel:user_detail", pk=sub.user_id)


# --------------------------------------------------------------------------- #
# Pagamentos
# --------------------------------------------------------------------------- #

class PaymentListView(SuperuserRequiredMixin, View):
    template_name = "painel/payment_list.html"

    def get(self, request):
        status = request.GET.get("status", "")
        qs = Payment.objects.select_related("user", "plan", "coupon").all()
        if status:
            qs = qs.filter(status=status)
        paginator = Paginator(qs.order_by("-created_at"), 25)
        page = paginator.get_page(request.GET.get("page"))
        return render(request, self.template_name, {"page": page, "status": status})


class PaymentCreateView(SuperuserRequiredMixin, View):
    """Registra pagamento para um usuário específico."""

    template_name = "painel/payment_form.html"

    def get(self, request, pk):
        user = get_object_or_404(User, pk=pk)
        form = RecordPaymentForm()
        return render(request, self.template_name, {"form": form, "target": user})

    def post(self, request, pk):
        user = get_object_or_404(User, pk=pk)
        form = RecordPaymentForm(request.POST)
        if form.is_valid():
            coupon = None
            code = form.cleaned_data.get("coupon_code", "").strip()
            if code:
                coupon = Coupon.objects.filter(code__iexact=code, is_active=True).first()
            payment = services.record_payment(
                user,
                amount=form.cleaned_data["amount"],
                method=form.cleaned_data["method"],
                plan=form.cleaned_data.get("plan"),
                coupon=coupon,
                notes=form.cleaned_data.get("notes", ""),
                created_by=request.user,
            )
            messages.success(request, f"Pagamento #{payment.pk} registrado (pendente).")
            return redirect("painel:user_detail", pk=pk)
        return render(request, self.template_name, {"form": form, "target": user})


class PaymentMarkPaidView(SuperuserRequiredMixin, View):
    def post(self, request, pk):
        payment = get_object_or_404(Payment, pk=pk)
        services.mark_payment_paid(payment)
        messages.success(request, f"Pagamento #{payment.pk} marcado como pago.")
        return redirect("painel:user_detail", pk=payment.user_id)


class PaymentRefundView(SuperuserRequiredMixin, View):
    def post(self, request, pk):
        payment = get_object_or_404(Payment, pk=pk)
        services.refund_payment(payment)
        messages.success(request, f"Pagamento #{payment.pk} reembolsado.")
        return redirect("painel:user_detail", pk=payment.user_id)


# --------------------------------------------------------------------------- #
# Relatórios de vendas
# --------------------------------------------------------------------------- #

class ReportsView(SuperuserRequiredMixin, View):
    template_name = "painel/reports.html"

    def get(self, request):
        days = max(int(request.GET.get("days", 30)), 1)
        ctx = {
            "days": days,
            "revenue": services.revenue_summary(days=days),
            "revenue_by_plan": services.revenue_by_plan(days=days),
            "revenue_by_method": services.revenue_by_method(days=days),
            "mrr": services.mrr(),
            "arr": services.arr(),
            "churn": services.churn_rate(days=days),
            "conversion": services.conversion_rate(),
            "top_customers": services.top_customers(days=days),
            "subscribers_series": services.new_subscribers_series(days=days),
        }
        return render(request, self.template_name, ctx)


# --------------------------------------------------------------------------- #
# Monetização + Códigos de acesso (EXPANDIDO com plano vinculado)
# --------------------------------------------------------------------------- #

class MonetizationView(SuperuserRequiredMixin, View):
    template_name = "painel/monetization.html"

    def get(self, request):
        cfg = services.monetization()
        return render(
            request, self.template_name,
            {
                "form": MonetizationForm(instance=cfg),
                "codes": AccessCode.objects.all()[:200],
                "config": cfg,
            },
        )

    def post(self, request):
        cfg = services.monetization()
        form = MonetizationForm(request.POST)
        if form.is_valid():
            cfg.signup_requires_payment = form.cleaned_data["signup_requires_payment"]
            cfg.default_plan = form.cleaned_data.get("default_plan")
            cfg.price_label = form.cleaned_data["price_label"]
            cfg.payment_instructions = form.cleaned_data["payment_instructions"]
            cfg.support_contact = form.cleaned_data.get("support_contact", "")
            cfg.save()
            messages.success(request, "Configuração de monetização salva.")
        else:
            messages.error(request, "Não foi possível salvar a configuração.")
        return redirect("painel:monetization")


class AccessCodeCreateView(SuperuserRequiredMixin, View):
    def post(self, request):
        form = AccessCodeForm(request.POST)
        if form.is_valid():
            plan = form.cleaned_data.get("plan")
            codes = services.create_access_codes(
                form.cleaned_data["quantity"],
                note=form.cleaned_data.get("note", ""),
                created_by=request.user,
                plan=plan,
            )
            messages.success(request, f"{len(codes)} código(s) criado(s).")
        else:
            messages.error(request, "Dados inválidos.")
        return redirect("painel:monetization")


class AccessCodeRevokeView(SuperuserRequiredMixin, View):
    def post(self, request, pk):
        code = get_object_or_404(AccessCode, pk=pk)
        code.revoked = True
        code.save(update_fields=["revoked"])
        messages.success(request, f"Código {code.code} revogado.")
        return redirect("painel:monetization")


# --------------------------------------------------------------------------- #
# Telemetria
# --------------------------------------------------------------------------- #

class TrackView(View):
    http_method_names = ["post"]

    def post(self, request):
        user = request.user
        if not user.is_authenticated:
            return JsonResponse({}, status=204)
        features = []
        try:
            payload = json.loads(request.body or b"{}")
        except Exception:
            payload = request.POST
        raw = payload.get("features") or payload.get("feature")
        if isinstance(raw, str):
            features = [raw]
        elif isinstance(raw, list):
            features = [str(f) for f in raw[:32]]
        services.track_features(user, features)
        return JsonResponse({}, status=204)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _recent_events(user):
    from .models import FeatureEvent
    return list(
        FeatureEvent.objects.filter(user=user)
        .order_by("-date")[:14]
        .values("feature", "date", "count")
    )
