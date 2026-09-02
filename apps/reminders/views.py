"""Views do app reminders (agenda de vencimentos)."""

from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import TemplateView

from .services import HORIZON_CHOICES, timeline


class ReminderIndexView(LoginRequiredMixin, TemplateView):
    template_name = "reminders/reminders.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        days = self.request.GET.get("days", 30)
        try:
            days = int(days)
        except (TypeError, ValueError):
            days = 30
        if days not in HORIZON_CHOICES:
            days = 30
        ctx["days"] = days
        ctx["horizon_choices"] = HORIZON_CHOICES
        ctx["timeline"] = timeline(self.request.user, days=days)
        return ctx
