"""Views do Painel do Dono — administração, telemetria e monetização.

Acesso restrito a ``is_superuser`` (o dono da plataforma). As leituras usam
as agregações baratas de ``apps.painel.services``.
"""

import json

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.mixins import UserPassesTestMixin
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View
from django.views.generic import TemplateView

from . import services
from .forms import MonetizationForm

User = get_user_model()


class SuperuserRequiredMixin(UserPassesTestMixin):
    def test_func(self):
        user = self.request.user
        return bool(user.is_authenticated and user.is_superuser)


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
        return ctx


class UserListView(SuperuserRequiredMixin, View):
    template_name = "painel/user_list.html"

    def get(self, request):
        q = request.GET.get("q", "").strip()
        qs = User.objects.all()
        if q:
            qs = qs.filter(
                Q(username__icontains=q)
                | Q(email__icontains=q)
                | Q(first_name__icontains=q)
                | Q(last_name__icontains=q)
            )
        qs = qs.order_by("-date_joined")
        paginator = Paginator(qs, 25)
        page = paginator.get_page(request.GET.get("page"))
        return render(
            request,
            self.template_name,
            {"users": page, "q": q, "paginator": paginator},
        )


class UserDetailView(SuperuserRequiredMixin, View):
    template_name = "painel/user_detail.html"

    def get(self, request, pk):
        user = get_object_or_404(User, pk=pk)
        ctx = {
            "target": user,
            "summary": services.user_activity_summary(user),
            "features": services.user_feature_breakdown(user),
            "recent_events": _recent_events(user),
        }
        return render(request, self.template_name, ctx)


class UserToggleView(SuperuserRequiredMixin, View):
    """Altera um atributo simples ({is_active, is_paying}) de um usuário."""

    def post(self, request, pk, field):
        if field not in ("is_active", "is_paying", "staff"):
            return HttpResponse(status=400)
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


class MonetizationView(SuperuserRequiredMixin, View):
    template_name = "painel/monetization.html"

    def get(self, request):
        cfg = services.monetization()
        return render(
            request,
            self.template_name,
            {
                "form": MonetizationForm(instance=cfg),
                "codes": services.AccessCode.objects.all()[:200],
                "config": cfg,
            },
        )

    def post(self, request):
        cfg = services.monetization()
        form = MonetizationForm(request.POST)
        if form.is_valid():
            cfg.signup_requires_payment = form.cleaned_data["signup_requires_payment"]
            cfg.price_label = form.cleaned_data["price_label"]
            cfg.payment_instructions = form.cleaned_data["payment_instructions"]
            cfg.save()
            messages.success(request, "Configuração de monetização salva.")
        else:
            messages.error(request, "Não foi possível salvar a configuração.")
        return redirect("painel:monetization")


class AccessCodeCreateView(SuperuserRequiredMixin, View):
    def post(self, request):
        try:
            quantity = max(min(int(request.POST.get("quantity", 1)), 100), 1)
        except ValueError:
            quantity = 1
        note = request.POST.get("note", "").strip()[:120]
        codes = services.create_access_codes(quantity, note=note, created_by=request.user)
        messages.success(request, f"{len(codes)} código(s) de acesso criado(s).")
        return redirect("painel:monetization")


class AccessCodeRevokeView(SuperuserRequiredMixin, View):
    def post(self, request, pk):
        code = get_object_or_404(services.AccessCode, pk=pk)
        code.revoked = True
        code.save(update_fields=["revoked"])
        messages.success(request, f"Código {code.code} revogado.")
        return redirect("painel:monetization")


class TrackView(View):
    """Beacon de telemetria — recebe slugs de features usadas pelo usuário.

    Apenas usuários autenticados; aceita corpo JSON ``{"features": [...]}``
    ou ``feature`` simples (form-urlencoded). Escrita agregada e barata.
    """

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


def _recent_events(user):
    from .models import FeatureEvent

    return list(
        FeatureEvent.objects.filter(user=user)
        .order_by("-date")[:14]
        .values("feature", "date", "count")
    )