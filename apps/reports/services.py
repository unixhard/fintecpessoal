"""Serviços do relatório de análise por IA (auditor de bolso).

O usuário gera um relatório completo de suas finanças — com sugestões,
cuidados, alertas e planejamento para aumentar o patrimônio — no tom de um
consultor financeiro especialista.

Limitação central: **1 geração a cada X dias** (``COOLDOWN_DAYS``, via
env ``REPORT_COOLDOWN_DAYS``, padrão 3). O relatório é persistido em
``AIReport`` (isolado por usuário).

Fallback gracioso: se a IA estiver indisponível (sem chave / sem internet /
erro), o fluxo NÃO quebra — é exibido um relatório local determinístico a
partir dos mesmos dados, sem consumir o limite de cooldown (não é persistido).
"""

from __future__ import annotations

import html
import os
import re
from datetime import date, timedelta

from django.utils import timezone

from apps.core.services.ai import AIServiceError, generate_text
from apps.dashboard.viewmodel import build_dashboard
from apps.finance.services.balances import net_worth

from .models import AIReport

# Intervalo (dias) entre gerações por IA. Configurável via env para permitir
# janelas de teste (ex.: REPORT_COOLDOWN_DAYS=0 libera gerações ilimitadas).
COOLDOWN_DAYS_MAX = 365
COOLDOWN_DAYS = max(0, min(int(os.getenv("REPORT_COOLDOWN_DAYS", "3")), COOLDOWN_DAYS_MAX))


class CooldownError(Exception):
    """Tentativa de gerar relatório dentro do intervalo de cooldown."""

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


def _display_name(user) -> str:
    """Nome exibível para a IA usar no tom pessoal (display_name > nome > username)."""
    display = getattr(getattr(user, "profile", None), "display_name", "") or ""
    full = (user.get_full_name() or "").strip()
    return (display or full or user.get_username() or "você").strip()


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
        "nome": _display_name(user),
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
        "evolucao_mensal": [
            {
                "label": b.label,
                "receitas_centavos": b.receitas,
                "despesas_centavos": b.despesas,
                "saldo_centavos": b.saldo,
            }
            for b in data.get("evolution", []) or []
        ],
    }


def _render_context(ctx: dict) -> str:
    lines = []
    nome = ctx.get("nome") or "usuário"
    lines.append("VOCÊ ESTÁ FALANDO COM:")
    lines.append(f"- Nome/apelido da pessoa: {nome} (chame-a assim, pelo nome, pelo menos 2 vezes).")
    lines.append("")
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
    if ctx.get("evolucao_mensal"):
        lines.append("- Evolução mensal (receitas/despesas/saldo por mês):")
        for ev in ctx["evolucao_mensal"]:
            lines.append(
                f"  * {ev['label']}: receitas {ev['receitas_centavos']}, "
                f"despesas {ev['despesas_centavos']}, saldo {ev['saldo_centavos']}"
            )
    if ctx.get("relatorio_anterior"):
        r = ctx["relatorio_anterior"]
        lines.append("")
        lines.append("RELATÓRIO ANTERIOR (da última conversa, para comparar o que mudou — use como base de continuidade, sem inventar nada fora destes dados):")
        lines.append(f"- Data anterior: {r.get('data', 'desconhecida')}")
        lines.append(f"- Conteúdo anterior:\n{r.get('conteudo', '')}")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Geração por IA
# --------------------------------------------------------------------------- #

_SYSTEM_PROMPT = (
    "Você é o 'CFO de Bolso' — o consultor financeiro pessoal e de confiança "
    "do usuário, parte do app FINTECPESSOAL. Não entregue um relatório frio: "
    "conduza a pessoa como um CFO de verdade, olhando sempre para 4 frentes "
    "quando os dados permitirem:\n"
    "1. DINHEIRO — o que entra, sai e sobra hoje.\n"
    "2. SEGURANÇA — o que pode quebrar essa situação (dívida cara, falta de "
    "reserva, risco concentrado).\n"
    "3. OPORTUNIDADES — o que a pessoa está deixando na mesa.\n"
    "4. CRESCIMENTO PATRIMONIAL — para onde tudo isso leva em 1, 5 e 10 anos.\n\n"
    "IDENTIDADE E TOM:\n"
    "- Fale DIRETAMENTE com a pessoa, na 2ª pessoa ('você'), nunca em 3ª pessoa.\n"
    "- Se conhecer o nome/apelido da pessoa, use-o pelo menos 2 vezes.\n"
    "- Tom de mentor próximo, NUNCA de auditor distante.\n"
    "- Explique qualquer termo técnico em 1 frase simples (ex.: 'CDB é um "
    "investimento de renda fixa que rende como um empréstimo ao banco').\n"
    "- Comemore o progresso real ANTES de apontar problemas.\n"
    "- NUNCA abra a conversa com um alerta.\n"
    "- Trate a pessoa como capaz: nunca infantilize, nunca assuma "
    "conhecimento prévio, mas também nunca subestime a inteligência dela.\n"
    "- Seja o oposto de burocrático: cada frase deve ajudar a pessoa a decidir "
    "algo, não apenas descrever a situação.\n\n"
    "REGRAS DE INTEGRIDADE (inegociáveis):\n"
    "- Use SOMENTE os dados fornecidos. NUNCA invente números, categorias, "
    "taxas de juros, alíquotas, produtos financeiros ou métricas.\n"
    "- Se faltar dado para uma das 4 frentes, diga com franqueza o que falta "
    "e exatamente qual informação resolveria isso.\n"
    "- Toda projeção ou simulação deve declarar as premissas usadas (ex.: "
    "'assumindo que você mantém a taxa de poupança atual de X%'). NUNCA "
    "apresente projeção como garantia.\n"
    "- Seja específico e numérico. Proibido dar recomendação sem número, prazo "
    "ou ação anexada (nada de 'controle seus gastos' solto).\n"
    "- Responda em Português do Brasil.\n\n"
    "ESTRUTURA DA RESPOSTA (Markdown, nesta ordem):\n"
    "  ## 👋 Antes de tudo\n"
    "  (1-2 frases: reconhecimento genuíno do esforço/cenário + o que vamos "
    "olhar hoje)\n"
    "  ## 📋 Visão geral\n"
    "  ## 🩺 Saúde financeira\n"
    "  (nota de 0 a 10 com justificativa; compare com o período anterior se "
    "houver histórico)\n"
    "  ## 🛡️ Segurança\n"
    "  (reserva de emergência, dívida cara, concentração de risco — antes de "
    "falar em crescer, garanta que não há buraco no barco)\n"
    "  ## 🔍 Oportunidades\n"
    "  (o que a pessoa está deixando na mesa: dinheiro parado sem render, gasto "
    "recorrente renegociável, dívida cara a priorizar, folga não aproveitada — "
    "sempre com número associado)\n"
    "  ## ⚠️ Alertas e cuidados\n"
    "  (riscos imediatos que precisam de atenção esta semana)\n"
    "  ## 📈 Projeção de patrimônio\n"
    "  (cenário 'se nada mudar' vs 'se seguir as ações recomendadas', em 1, 5 e "
    "10 anos quando o dado permitir — sempre com premissas explícitas)\n"
    "  ## 🎯 Plano de crescimento patrimonial\n"
    "  (estratégia de médio/longo prazo — não uma lista solta de dicas)\n"
    "  ## ✅ Suas 3 ações desta semana\n"
    "  (exatamente 3, pequenas, com prazo e número-alvo cada)\n"
    "  ## 🗣️ Uma pergunta para você\n"
    "  (uma pergunta de decisão real que só a pessoa pode responder — é o "
    "gancho para a próxima conversa)\n\n"
    "LIMITES DE TAMANHO:\n"
    "- Entre 600 e 1200 palavras no corpo principal.\n"
    "- Se um dos 4 pilares não tiver dado suficiente, diga isso em 1-2 frases "
    "na seção correspondente em vez de preencher com genérico.\n\n"
    "CONTINUIDADE:\n"
    "- Se houver contexto de relatório anterior, referencie explicitamente o "
    "que mudou desde a última vez.\n"
    "- Termine indicando quando faz sentido a pessoa voltar (ex.: 'volte em 7 "
    "dias, quando o extrato fechar').\n\n"
    "Você também tem os ALERTAS DETERMINÍSTICOS do sistema disponíveis — valide "
    "se estão corretos para os dados e, se estiverem, incorpore-os nas seções de "
    "Segurança/Alertas. Não os repita de forma genérica."
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
    previous = latest_report(user)
    if previous is not None:
        ctx["relatorio_anterior"] = {
            "data": previous.generated_at.astimezone().strftime("%d/%m/%Y"),
            "conteudo": previous.content,
        }
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
    e não consome o limite de cooldown — o usuário pode tentar de novo depois.
    Segue a mesma estrutura do relatório por IA, sem projeções inventadas.
    """
    ctx = collect_context(user)
    nome = ctx.get("nome") or "você"
    f = _fmt
    lines = [
        "## 👋 Antes de tudo",
        f"{nome}, olhei seus números dos últimos 30 dias e preparei um resumo "
        "para você continuar de onde paramos. A IA está fora do ar agora, então "
        "este é um recorte direto dos seus dados.",
        "",
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
            f"Nota: **3/10**. {nome}, você está gastando mais do que recebe no "
            "período — esse ritmo reduz seu patrimônio e é o ponto mais urgente "
            "a corrigir."
        )
    elif ctx["disponivel_apos_centavos"] < 0:
        lines.append(
            "Nota: **4/10**. Suas obrigações de cartão superam o saldo disponível. "
            "Antes de pensar em investir, é preciso reconquistar margem de liquidez."
        )
    elif not ctx["spending"] and ctx["disponivel_centavos"] >= 0:
        lines.append(
            "Nota: **6/10** (provisória). Ainda há poucos dados para uma nota "
            "precisa — cadastre despesas e receitas regularmente para uma "
            "avaliação mais confiável."
        )
    else:
        lines.append(
            f"Nota: **7/10**. {nome}, você está no azul nos últimos 30 dias, com "
            "margem após os compromissos. Continue registrando tudo para o "
            "próximo relatório."
        )

    lines += ["", "## 🛡️ Segurança"]
    if ctx["disponivel_apos_centavos"] < 0:
        lines.append(
            "Sua maior prioridade agora é encerrar o mês sem saldo negativo: "
            "reduza gastos descartáveis até a próxima receita."
        )
    elif ctx["resultado_centavos"] >= 0:
        lines.append(
            "Você tem uma base de liquidez positiva. Recomendo ir reservando "
            "uma parte do resultado para uma reserva de emergência de 3 a 6 "
            "meses de despesas antes de assumir novos compromissos."
        )
    else:
        lines.append("Com dados atuais, ainda não consigo dimensionar sua reserva — registre mais lançamentos.")

    lines += ["", "## 🔍 Oportunidades"]
    top = ctx["spending"][:3]
    if top:
        maior = top[0]
        lines.append(
            f"- Sua maior despesa está em **{maior['nome']}** "
            f"({maior['pct']}% do total). Revisar essa categoria costuma ser a "
            "oportunidade de curto prazo mais fácil (ex.: renegociar assinatura "
            "ou plano)."
        )
    if ctx["cartoes"]:
        for c in ctx["cartoes"]:
            if c["uso_pct"] >= 70:
                lines.append(
                    f"- O cartão **{c['nome']}** está com uso alto "
                    f"({c['uso_pct']}% do limite); liberar limite reduz custo de "
                    "crédito e risco."
                )
    if not top and not ctx["cartoes"]:
        lines.append("- Com poucos dados ainda, as oportunidades ficam mais claras no próximo relatório.")

    lines += ["", "## ⚠️ Alertas e cuidados"]
    if ctx["alertas_deterministicos"]:
        for a in ctx["alertas_deterministicos"]:
            lines.append(f"- **[{a['severidade'].capitalize()}] {a['titulo']}** — {a['descricao']}")
    else:
        lines.append("- Nenhum alerta determinístico detectado no momento.")

    lines += ["", "## 📈 Projeção de patrimônio"]
    if ctx["resultado_centavos"] > 0 and ctx["receitas_centavos"] > 0:
        taxa = min(int(ctx["resultado_centavos"] / ctx["receitas_centavos"] * 100), 99)
        lines.append(
            f"Assumindo que você mantenha a poupança atual de **{taxa}% da receita** "
            "e os mesmos valores, seu patrimônio cresce de forma gradual e "
            "previsível. Este é um cenário ilustrativo, não uma garantia."
        )
    else:
        lines.append(
            "Sem resultado positivo consistente, ainda não há projeção honesta "
            "a fazer — primeiro vamos recuperar a margem mensal."
        )

    lines += ["", "## 🎯 Plano de crescimento patrimonial"]
    if ctx["dividas"]:
        total = sum(d["restante_centavos"] for d in ctx["dividas"])
        lines.append(
            f"- Quite primeiro as dívidas de maior custo (restam {f(total)}): "
            "cada real pago em juros altos é um retorno garantido."
        )
    lines.append(
        "- **Pague-se primeiro:** automatize uma transferência para poupança/"
        "investimento assim que a receita cair."
    )
    lines.append(
        "- Considere metas concretas (ex.: reserva de emergência de 3 a 6 meses "
        "de despesas) para dar direção ao plano."
    )

    lines += ["", "## ✅ Suas 3 ações desta semana"]
    lines.append(
        "1. **Hoje:** conferir se cada lançamento está categorizado e sem duplicados. "
        "Meta: zero divergências."
    )
    lines.append(
        "2. **Até 3 dias:** definir orçamento para as 3 maiores categorias de despesa "
        "do mês. Meta: limites definidos no app."
    )
    lines.append(
        "3. **Até 7 dias:** programar os pagamentos das próximas faturas e cortar "
        "um gasto recorrente desnecessário. Meta: uma economia recorrente a mais."
    )
    lines += [
        "",
        "## 🗣️ Uma pergunta para você",
        "O que pesaria mais para você neste momento: aumentar a folga no fim do "
        "mês ou acelerar a quitação de alguma dívida? A resposta guia o próximo "
        "passo do plano.",
        "",
        "> ⚠️ *A IA não está disponível agora — este é um resumo local. Você "
        "pode gerar o relatório completo com IA mais tarde"
        + (" (novo a cada 3 dias).*" if COOLDOWN_DAYS > 0 else ".*"),
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
