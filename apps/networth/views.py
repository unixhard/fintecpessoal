"""Views do app networth (patrimônio consolidado)."""

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect, reverse
from django.views import View
from django.views.generic import TemplateView

from . import services


class NetWorthIndexView(LoginRequiredMixin, TemplateView):
    template_name = "networth/networth.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        user = self.request.user
        ctx.update(
            {
                "compose": services.compose(user),
                "history": services.get_history(user),
                "latest": services.latest_snapshot(user),
            }
        )
        return ctx


class NetWorthRegisterView(LoginRequiredMixin, View):
    """Registra um ponto de patrimônio hoje (POST, sem efeito colateral em GET)."""

    def post(self, request, *args, **kwargs):
        services.register_snapshot(request.user)
        messages.success(
            request, "Ponto de patrimônio de hoje registrado."
        )
        return redirect(reverse("networth:index"))
