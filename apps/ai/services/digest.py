from __future__ import annotations

from django.utils import timezone

from apps.finance.services.balances import net_worth
from apps.dashboard.viewmodel import build_dashboard


def _display_name(user) -> str:
    display = getattr(getattr(user, "profile", None), "display_name", "") or ""
    full = (user.get_full_name() or "").strip()
    return (display or full or user.get_username() or "você").strip()


def build_digest(user, *, data: dict | None = None) -> dict:
    """Agregado ENXUTO das finanças do usuário (economia de tokens + privacidade).

    Nunca envia descrições de movimentações, merchants ou a base completa —
    apenas totais, categorias e eventos próximos. É a ÚNICA coisa que vira
    contexto para a IA ("interpreta o resumo, não lê o extrato").
    ``data`` aceita o dicionário já construído por ``build_dashboard`` para que
    a página do dashboard não compute tudo duas vezes.
    """
    data = data or build_dashboard(user, period="30d")
    cf = data.get("cash_flow")
    insights = data.get("insights", [])

    return {
        "nome": _display_name(user),
        "patrimonio_centavos": int(net_worth(user) or 0),
        "disponivel_centavos": int(data.get("disponivel", 0) or 0),
        "comprometido_centavos": int(data.get("comprometido", 0) or 0),
        "disponivel_apos_centavos": int(data.get("disponivel_apos", 0) or 0),
        "receitas_centavos": int(getattr(cf, "receitas", 0) or 0),
        "despesas_centavos": int(getattr(cf, "despesas", 0) or 0),
        "resultado_centavos": int(getattr(cf, "resultado", 0) or 0),
        "spending": [
            {"nome": row.name, "valor_centavos": int(row.amount), "pct": row.share_percent}
            for row in (data.get("spending_rows") or [])[:5]
        ],
        "budgets": [
            {
                "nome": row.name,
                "limite_centavos": int(row.limit),
                "gasto_centavos": int(row.spent),
                "pct": row.percent,
                "status": row.status,
            }
            for row in (data.get("budgets") or [])[:3]
        ],
        "goals": [
            {
                "nome": row.name,
                "meta_centavos": int(row.target_amount),
                "acumulado_centavos": int(row.current_amount),
                "progresso_pct": row.progress_percent,
            }
            for row in (data.get("goals") or [])[:2]
        ],
        "dividas": [
            {"nome": row.name, "restante_centavos": int(row.remaining_amount)}
            for row in (data.get("debts") or [])[:2]
        ],
        "cartoes": [
            {"nome": row.name, "usado_centavos": int(row.used), "limite_centavos": int(row.limit), "uso_pct": row.used_pct}
            for row in (data.get("cards") or [])[:3]
        ],
        "eventos": [
            {
                "dias": int((ev.date - timezone.localdate()).days),
                "rotulo": ev.label,
                "valor_centavos": int(ev.amount),
            }
            for ev in (data.get("upcoming_events") or [])[:5]
        ],
        "alertas": [
            {"severidade": i.severity, "titulo": i.title, "descricao": i.description}
            for i in (insights or [])[:3]
        ],
    }