"""Serviços do relatório de análise por IA (auditor de bolso).

O usuário gera um relatório completo de suas finanças — com sugestões,
cuidados, alertas e planejamento para aumentar o patrimônio — no tom de um
consultor financeiro especialista.

Limitação central: **1 geração a cada 3 dias** (``COOLDOWN_DAYS``). O relatório
é persistido em ``AIReport`` (isolado por usuário).

Fallback gracioso: se a IA estiver indisponível (sem chave / sem internet /
erro), o fluxo NÃO quebra — é exibido um relatório local determinístico a
partir dos mesmos dados, sem consumir o limite de 3 dias (não é persistido).
"""

from __future__ import annotations

import html
import re
from datetime import date, timedelta

from django.utils import timezone

from apps.core.services.ai import AIServiceError, generate_text
from apps.dashboard.viewmodel import build_dashboard
from apps.finance.services.balances import net_worth

from .models import AIReport

COOLDOWN_DAYS = 3


class CooldownError(Exception):
    """Tentativa de gerar relatório dentro do intervalo de 3 dias."""

    def __init__(self, next_allowed: date | None = None):
        self.next_allowed = next_allowed
        super().__init__("Relatório já gerado recentemente.")


# --------------------------------------------------------------------------- #
# Consulta / cooldown
# --------------------------------------------------------------------------- #


def latest_report(user) -> AIReport | None:
    return AIReport.objects.for_user(user).order_by("-generated_at").first()


def next_available_date(user, *, today=None) -> date:
    """Próxima data em que um novo relatório poderá ser gerado."""
    today = today or timezone.localdate()
    latest = latest_report(user)
    if latest is None:
        return today
    return latest.generated_at.date() + timedelta(days=COOLDOWN_DAYS)


def can_generate(user, *, today=None) -> bool:
    today = today or timezone.localdate()
    return next_available_date(user, today=today) <= today


def _remaining_days(user, *, today=None) -> int:
    today = today or timezone.localdate()
    return (next_available_date(user, today=today) - today).days


# --------------------------------------------------------------------------- #
# Contexto (dados) a enviar à IA — apenas números, sem narrativa extra.
# --------------------------------------------------------------------------- #


def _fmt(cents: int) -> str:
    try:
        cents = int(cents or 0)
    except (TypeError, ValueError):
        cents = 0
    sign = "-" if cents < 0 else ""
    v = abs(cents)
    reais, cent = divmod(v, 100)
    return f"{sign}R$ {reais:,}".replace(",", ".") + f",{cent:02d}"


def collect_context(user) -> dict:
    """Coleta as métricas financeiras do usuário para a análise da IA."""
    period = "30d"
    data = build_dashboard(user, period=period)
    insights = data.get("insights", [])
    cf = data.get("cash_flow")

    return {
        "patrimonio_centavos": net_worth(user),
        "disponivel_centavos": data.get("disponivel", 0),
        "comprometido_centavos": data.get("comprometido", 0),
        "disponivel_apos_centavos": data.get("disponivel_apos", 0),
        "receitas_centavos": getattr(cf, "receitas", 0) or 0,
        "despesas_centavos": getattr(cf, "despesas", 0) or 0,
        "resultado_centavos": getattr(cf, "resultado", 0) or 0,
        "spending": [
            {
                "nome": row.name,
                "valor_centavos": row.amount,
                "pct": row.share_percent,
                "variacao_vs_anterior_pct": row.delta_percent,
            }
            for row in data.get("spending_rows", [])
        ],
        "budgets": [
            {
                "nome": row.name,
                "limite_centavos": row.limit,
                "gasto_centavos": row.spent,
                "pct": row.percent,
                "status": row.status,
            }
            for row in data.get("budgets", [])
        ],
        "goals": [
            {
                "nome": row.name,
                "meta_centavos": row.target_amount,
                "acumulado_centavos": row.current_amount,
                "progresso_pct": row.progress_percent,
            }
            for row in data.get("goals", [])
        ],
        "dividas": [
            {
                "nome": row.name,
                "total_centavos": row.total_amount,
                "restante_centavos": row.remaining_amount,
            }
            for row in data.get("debts", [])
        ],
        "cartoes": [
            {
                "nome": row.name,
                "limite_centavos": row.limit,
                "usado_centavos": row.used,
                "uso_pct": row.used_pct,
            }
            for row in data.get("cards", [])
        ],
        "contas": [
            {"nome": row.name, "saldo_centavos": row.balance}
            for row in data.get("accounts", [])
        ],
        "proximos_eventos": [
            {
                "data_iso": str(ev.date),
                "rotulo": ev.label,
                "valor_centavos": ev.amount,
                "tipo": ev.kind,
            }
            for ev in data.get("upcoming_events", [])[:10]
        ],
        "recentes": [
            {
                "data_iso": str(r.date),
                "descricao": r.description,
                "categoria": r.category,
                "valor_centavos": r.amount,
                "tipo": r.type,
            }
            for r in data.get("recent_transactions", [])[:15]
        ],
        "alertas_deterministicos": [
            {
                "severidade": i.severity,
                "titulo": i.title,
                "descricao": i.description,
                "acao": i.action,
            }
            for i in insights
        ],
    }


def _render_context(ctx: dict) -> str:
    lines = []
    lines.append("CONTEXTO (valores em CENTAVOS, salvo indicação).")
    lines.append(f"- Patrimônio total (todas as contas): {ctx['patrimonio_centavos']}")
    lines.append(f"- Saldo disponível (contas ativas): {ctx['disponivel_centavos']}")
    lines.append(f"- Comprometido em cartões: {ctx['comprometido_centavos']}")
    lines.append(f"- Disponível após compromissos: {ctx['disponivel_apos_centavos']}")
    lines.append(f"- Receitas (30d): {ctx['receitas_centavos']}")
    lines.append(f"- Despesas (30d): {ctx['despesas_centavos']}")
    lines.append(f"- Resultado (30d): {ctx['resultado_centavos']}")
    if ctx["spending"]:
        lines.append("- Gastos por categoria (30d):")
        for s in ctx["spending"]:
            var = f", variação {s['variacao_vs_anterior_pct']}%" if s["variacao_vs_anterior_pct"] is not None else ""
            lines.append(f"  * {s['nome']}: {s['valor_centavos']} ({s['pct']}%{var})")
    if ctx["budgets"]:
        lines.append("- Orçamentos (mês atual):")
        for b in ctx["budgets"]:
            lines.append(f"  * {b['nome']}: {b['gasto_centavos']} de {b['limite_centavos']} ({b['pct']}%, status {b['status']})")
    if ctx["goals"]:
        lines.append("- Metas:")
        for g in ctx["goals"]:
            lines.append(f"  * {g['nome']}: {g['acumulado_centavos']} de {g['meta_centavos']} ({g['progresso_pct']}%)")
    if ctx["dividas"]:
        lines.append("- Dívidas ativas:")
        for d in ctx["dividas"]:
            lines.append(f"  * {d['nome']}: restam {d['restante_centavos']} de {d['total_centavos']}")
    if ctx["cartoes"]:
        lines.append("- Cartões:")
        for c in ctx["cartoes"]:
            lines.append(f"  * {c['nome']}: usado {c['usado_centavos']} de {c['limite_centavos']} ({c['uso_pct']}%)")
    if ctx["contas"]:
        lines.append("- Contas:")
        for a in ctx["contas"]:
            lines.append(f"  * {a['nome']}: {a['saldo_centavos']}")
    if ctx["proximos_eventos"]:
        lines.append("- Próximos eventos (30 dias):")
        for e in ctx["proximos_eventos"]:
            lines.append(f"  * {e['data_iso']} - {e['rotulo']}: {e['valor_centavos']} ({e['tipo']})")
    if ctx["recentes"]:
        lines.append("- Últimas movimentações (destaque):")
        for r in ctx["recentes"]:
            lines.append(f"  * {r['data_iso']} [{r['tipo']}] {r['descricao']} (cat: {r['categoria']}): {r['valor_centavos']}")
    if ctx["alertas_deterministicos"]:
        lines.append("- Alertas determinísticos já identificados:")
        for a in ctx["alertas_deterministicos"]:
            lines.append(f"  * [{a['severidade']}] {a['titulo']}: {a['descricao']}. Ação: {a['acao']}")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Geração por IA
# --------------------------------------------------------------------------- #

_SYSTEM_PROMPT = (
    "Você é um 'auditor de bolso': consultor financeiro sênior e especialista "
    "em finanças pessoais. Seu trabalho é analisar os dados fornecidos e "
    "produzir um relatório completo, honesto e acionável, no tom de um mentor "
    "que ajuda a pessoa a aumentar o patrimônio e ter melhores resultados.\n\n"
    "REGRAS:\n"
    "- Use SOMENTE os dados fornecidos. NUNCA invente números, categorias ou métricas.\n"
    "- Se faltar amostra ou dados, diga com franqueza que não há informação "
    "suficiente e recomende cadastrar mais dados.\n"
    "- Seja específico, prático e dê números sempre que possível; evite clichês.\n"
    "- Responda em Português do Brasil.\n"
    "- Produza Markdown com estas seções, nesta ordem:\n"
    "  ## 📋 Visão geral\n"
    "  ## 🩺 Saúde financeira\n"
    "  ## ⚠️ Alertas e cuidados\n"
    "  ## 💡 Sugestões de melhoria\n"
    "  ## 🎯 Planejamento para aumentar o patrimônio\n"
    "  ## ✅ Ações concretas\n"
    "- Em 'Saúde financeira' dê uma nota de 0 a 10 com justificativa.\n"
    "- Em 'Ações concretas' liste exatamente 3 ações para a semana.\n"
    "- Mantenha o relatório entre 400 e 800 palavras."
)


def _extract_summary(content: str) -> str:
    """Pega a primeira frase não vazia como resumo."""
    for line in (content or "").splitlines():
        clean = line.strip().lstrip("#*-").strip()
        if clean:
            return clean[:200]
    return "Relatório de análise financeira"


def generate_ai_report(*, user, today=None) -> AIReport:
    """Gera, persiste e retorna o relatório por IA (respeitando o cooldown).

    Se o usuário gerou relatório nos últimos ``COOLDOWN_DAYS`` dias, lança
    ``CooldownError``. Falha de IA propaga ``AIServiceError`` — o chamador
    decide o fallback local.
    """
    today = today or timezone.localdate()
    latest = latest_report(user)
    if latest is not None:
        delta = (today - latest.generated_at.date()).days
        if delta < COOLDOWN_DAYS:
            raise CooldownError(
                next_allowed=latest.generated_at.date() + timedelta(days=COOLDOWN_DAYS)
            )

    ctx = collect_context(user)
    content = generate_text(
        system_prompt=_SYSTEM_PROMPT,
        user_prompt=_render_context(ctx),
    )
    return AIReport.objects.create(
        owner=user,
        content=content,
        via_ai=True,
        summary=_extract_summary(content),
    )


# --------------------------------------------------------------------------- #
# Fallback local (sem IA) — não persiste e não consome o cooldown.
# --------------------------------------------------------------------------- #


def build_manual_report(user) -> str:
    """Relatório determinístico a partir dos mesmos dados, sem chamar a IA.

    É o fallback gracioso quando a IA está indisponível. Não é salvo no banco
    e não consome o limite de 3 dias — o usuário pode tentar de novo depois.
    """
    ctx = collect_context(user)
    f = _fmt
    lines = [
        "## 📋 Visão geral",
        f"- Saldo disponível (contas ativas): **{f(ctx['disponivel_centavos'])}**",
        f"- Patrimônio total: {f(ctx['patrimonio_centavos'])}",
        f"- Comprometido em cartões: {f(ctx['comprometido_centavos'])}",
        f"- Disponível após compromissos: **{f(ctx['disponivel_apos_centavos'])}**",
        f"- Resultado nos últimos 30 dias: **{f(ctx['resultado_centavos'])}** "
        f"(receitas {f(ctx['receitas_centavos'])} - despesas {f(ctx['despesas_centavos'])})",
        "",
        "## 🩺 Saúde financeira",
    ]
    if ctx["resultado_centavos"] < 0:
        lines.append(
            "Você está gastando mais do que recebe nos últimos 30 dias. Esse "
            "ritmo reduz seu patrimônio — é o ponto mais urgente a corrigir."
        )
    elif ctx["disponivel_apos_centavos"] < 0:
        lines.append(
            "Suas obrigações de cartão superam o saldo disponível. Antes de "
            "pensar em investir, é preciso reconquistar margem de liquidez."
        )
    elif not ctx["spending"] and ctx["disponivel_centavos"] >= 0:
        lines.append(
            "Ainda há poucos dados para uma nota precisa. Cadastre despesas e "
            "receitas regularmente para uma avaliação mais confiável."
        )
    else:
        lines.append(
            "Você está no azul nos últimos 30 dias, com margem após os "
            "compromissos. Continue registrando tudo para o próximo relatório."
        )

    lines += ["", "## ⚠️ Alertas e cuidados"]
    if ctx["alertas_deterministicos"]:
        for a in ctx["alertas_deterministicos"]:
            lines.append(f"- **[{a['severidade'].capitalize()}] {a['titulo']}** — {a['descricao']}")
    else:
        lines.append("- Nenhum alerta determinístico detectado no momento.")

    lines += ["", "## 💡 Sugestões de melhoria"]
    top = ctx["spending"][:3]
    if top:
        maior = top[0]
        lines.append(
            f"- Sua maior despesa está em **{maior['nome']}** "
            f"({maior['pct']}% do total). Revise essa categoria para "
            "encontrar oportunidades de redução."
        )
    if ctx["cartoes"]:
        for c in ctx["cartoes"]:
            if c["uso_pct"] >= 70:
                lines.append(
                    f"- O cartão **{c['nome']}** está com uso alto "
                    f"({c['uso_pct']}% do limite). Mantenha abaixo de 30% para "
                    "proteger seu score e o custo do crédito."
                )
    if not ctx["goals"]:
        lines.append("- Crie metas (ex.: reserva de emergência de 3 a 6 meses de despesas).")

    lines += ["", "## 🎯 Planejamento para aumentar o patrimônio"]
    if ctx["dividas"]:
        total = sum(d["restante_centavos"] for d in ctx["dividas"])
        lines.append(
            f"- Quite as dívidas de maior custo primeiro (restam {f(total)}). "
            "Cada real pago em juros altos é um retorno garantido."
        )
    lines.append(
        "- **Pague-se primeiro:** automatize uma transferência para poupança/"
        "investimento logo que a receita cair."
    )
    if ctx["resultado_centavos"] > 0:
        taxa = min(int(ctx["resultado_centavos"] / max(ctx["receitas_centavos"], 1) * 100), 99)
        lines.append(
            f"- Você poupou cerca de {taxa}% da receita em 30 dias. Suba esse "
            "percentual aos poucos (ex.: +2%) para acelerar o patrimônio."
        )

    lines += ["", "## ✅ Ações concretas"]
    lines.append(
        "- **Revisar hoje:** confirmar que cada lançamento está categorizado "
        "e nenhum está duplicado."
    )
    lines.append(
        "- **Nesta semana:** definir orçamentos para as 3 maiores categorias "
        "de despesa."
    )
    lines.append(
        "- **Nos próximos 3 dias:** programar pagamentos das faturas próximas "
        "e remover qualquer gasto supérfluo."
    )
    lines += [
        "",
        "> ⚠️ *A IA não está disponível agora — este é um resumo local. Você "
        "pode gerar o relatório completo com IA mais tarde (novo a cada 3 dias).*",
    ]
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Renderização leve de Markdown (sem dependências externas)
# --------------------------------------------------------------------------- #


def render_markdown(text: str) -> str:
    """Converte um subconjunto de Markdown para HTML sanitizado.

    Suporta: títulos (#/##/###), listas (-/*, 1.), itálico e negrito,
    parágrafos separados por linha em branco, e citação (>). Sem libs externas.
    """
    if not text:
        return ""

    def _escape(s: str) -> str:
        return html.escape(s, quote=False)

    def _inline(s: str) -> str:
        s = _escape(s)
        # **bold** (depois *italic* para não quebrar o bold)
        s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
        s = re.sub(r"\*(.+?)\*", r"<em>\1</em>", s)
        return s

    lines = (text or "").splitlines()
    out: list[str] = []
    para: list[str] = []
    in_list = None  # 'ul' | 'ol'

    def flush_para():
        nonlocal para
        if para:
            out.append("<p>" + _inline(" ".join(para).strip()) + "</p>")
            para = []

    def close_list():
        nonlocal in_list
        if in_list:
            out.append(f"</{in_list}>")
            in_list = None

    for raw in lines:
        line = raw.rstrip()
        stripped = line.strip()
        header = re.match(r"^(#{1,3})\s+(.*)$", stripped)
        quote = re.match(r"^>\s?(.*)$", stripped)
        bullet = re.match(r"^[-*]\s+(.*)$", stripped)
        numbered = re.match(r"^\d+[.)]\s+(.*)$", stripped)

        if not stripped:
            flush_para()
            continue

        if header:
            flush_para()
            close_list()
            level = min(len(header.group(1)) + 1, 6)
            out.append(f"<h{level}>{_inline(header.group(2))}</h{level}>")
        elif quote:
            flush_para()
            close_list()
            out.append(f"<p class='ai-quote'>{_inline(quote.group(1))}</p>")
        elif bullet:
            flush_para()
            if in_list != "ul":
                close_list()
                out.append("<ul>")
                in_list = "ul"
            out.append(f"<li>{_inline(bullet.group(1))}</li>")
        elif numbered:
            flush_para()
            if in_list != "ol":
                close_list()
                out.append("<ol>")
                in_list = "ol"
            out.append(f"<li>{_inline(numbered.group(1))}</li>")
        else:
            close_list()
            para.append(stripped)

    flush_para()
    close_list()
    return "\n".join(out)
