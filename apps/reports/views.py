"""Views do app reports (relatórios + exportação).

Reusa a camada de leitura do dashboard (apps.dashboard.queries) — cash_flow,
spending_by_category e monthly_evolution — para não duplicar regras de agregação.
Exportação é 100% local via csv nativo; o relatório imprimível (HTML) pode ser
salvo/impresso em PDF pelo navegador, sem dependência externa.
"""

import csv
import io

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponse
from django.shortcuts import redirect, reverse
from django.views import View
from django.views.generic import TemplateView

from apps.dashboard import queries
from apps.core.services.ai import AIServiceError, ai_enabled

from .services import (
    COOLDOWN_DAYS,
    CooldownError,
    build_manual_report,
    can_generate,
    generate_ai_report,
    latest_report,
    next_available_date,
    render_markdown,
)

PERIODS = ("7d", "30d", "3m", "6m", "12m")


def _period(request, default="30d"):
    key = request.GET.get("period", default)
    if key not in PERIODS:
        key = default
    return queries.resolve_period(key)


class ReportIndexView(LoginRequiredMixin, TemplateView):
    template_name = "reports/report.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        user = self.request.user
        period = _period(self.request)
        kwargs_period = {
            "start": period["start"],
            "end": period["end"],
        }
        ctx["period"] = period
        ctx["periods"] = PERIODS
        ctx["cash_flow"] = queries.cash_flow(user, **kwargs_period)
        ctx["by_category"] = queries.spending_by_category(user, **kwargs_period)
        ctx["evolution"] = queries.monthly_evolution(user, **kwargs_period)
        return ctx


class ReportCsvView(LoginRequiredMixin, TemplateView):
    """Exportação CSV das movimentações do período (abre no Excel)."""

    def get(self, request, *args, **kwargs):
        user = request.user
        period = _period(request)
        rows = _transaction_rows(user, period["start"], period["end"])
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(
            ["Data", "Tipo", "Descrição", "Categoria", "Conta", "Valor (centavos)", "Valor (R$)"]
        )
        for r in rows:
            writer.writerow(
                [
                    r["date"],
                    r["type"],
                    r["description"],
                    r["category"] or "",
                    r["account"],
                    r["amount"],
                    _brl(r["amount"]),
                ]
            )
        filename = f"relatorio-{period['key']}.csv"
        response = HttpResponse(buf.getvalue(), content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response


class ReportPrintableView(LoginRequiredMixin, TemplateView):
    """Relatório limpo para impressão/PDF (Exportador Rápido)."""

    template_name = "reports/printable.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        user = self.request.user
        period = _period(self.request)
        kwargs_period = {"start": period["start"], "end": period["end"]}
        ctx["period"] = period
        ctx["cash_flow"] = queries.cash_flow(user, **kwargs_period)
        ctx["by_category"] = queries.spending_by_category(user, **kwargs_period)
        return ctx


def _transaction_rows(user, start, end):
    from apps.finance.models import Transaction

    txs = (
        Transaction.objects.for_user(user)
        .select_related("account", "category")
        .filter(date__gte=start, date__lte=end)
        .order_by("date")
    )
    return [
        {
            "date": tx.date,
            "type": tx.get_type_display(),
            "description": tx.description or tx.get_type_display(),
            "category": tx.category.name if tx.category_id else "",
            "account": tx.account.name,
            "amount": tx.amount,
        }
        for tx in txs
    ]


def _brl(cents):
    sign = "-" if cents < 0 else ""
    v = abs(cents)
    reais, cent = divmod(v, 100)
    return f"{sign}{reais:,}.{cent:02d}".replace(",", ".")


class AIReportView(LoginRequiredMixin, View):
    """Relatório de análise por IA ("auditor de bolso"), com cooldown configurável.

    GET  -> exibe o último relatório (se houver) e o estado do limite.
    POST -> gera um novo (respeitando o cooldown de ``COOLDOWN_DAYS`` dias). Se a
            IA estiver indisponível, exibe um relatório local sem consumir o limite.
    """

    template_name = "reports/ai_report.html"

    def _context(self, request, *, extra=None, manual_html=None):
        user = request.user
        report = latest_report(user)
        ctx = {
            "report": report,
            "report_html": render_markdown(report.content) if report else None,
            "via_ai": bool(report and report.via_ai),
            "generated_at": report.generated_at if report else None,
            "summary": report.summary if report else None,
            "manual_html": manual_html,
            "can_generate": can_generate(user),
            "next_available": next_available_date(user),
            "ai_available": ai_enabled(),
            "cooldown_days": COOLDOWN_DAYS,
        }
        if extra:
            ctx.update(extra)
        return ctx

    def get(self, request, *args, **kwargs):
        return self.render_to_response(
            request, self._context(request)
        )

    def post(self, request, *args, **kwargs):
        user = request.user
        try:
            report = generate_ai_report(user=user)
        except CooldownError as exc:
            messages.info(
                request,
                "Você já gerou o relatório recentemente. O próximo poderá ser "
                f"criado a partir de {exc.next_allowed:%d/%m/%Y}.",
            )
            return redirect(reverse("reports:ai_report"))
        except AIServiceError:
            manual_html = render_markdown(build_manual_report(user))
            messages.warning(
                request,
                "A IA não está disponível no momento (sem chave configurada ou "
                "sem conexão). Exibindo um relatório local — você poderá gerar "
                "a versão completa com IA mais tarde.",
            )
            return self.render_to_response(
                request,
                self._context(request, manual_html=manual_html),
            )
        msg_cooldown = f"a cada {COOLDOWN_DAYS} dias" if COOLDOWN_DAYS > 0 else "quando quiser"
        messages.success(
            request,
            f"Relatório de análise gerado com IA. Você pode gerar um novo {msg_cooldown}.",
        )
        return redirect(reverse("reports:ai_report"))

    def render_to_response(self, request, ctx, **kwargs):
        from django.shortcuts import render

        return render(request, self.template_name, ctx)
