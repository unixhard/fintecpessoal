"""Presença diária da IA no aplicativo ("CFO de bolso").

A ideia central de economia: **1 chamada por usuário por dia**. O texto do CFO
(saudação, insights, alerta e dica) é gerado uma única vez, com um prompt curto
+ digest enxuto, e servido do cache pelo resto do dia para TODAS as telas
(dashboard e sino). Se a IA estiver indisponível ou o orçamento do dia acabou,
o PRODUTO NÃO fica mudo: um gerador determinístico produz o mesmo formato com
os mesmos dados, sem custo de token — a presença é contínua por construção.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

from django.core.cache import cache
from django.utils import timezone

from apps.ai import budget
from apps.ai.services import breaker, ledger
from apps.core.services.ai import ai_enabled, generate_json

from .digest import build_digest

_MAX_INSIGHTS = 3

_SYSTEM_PROMPT = (
    "Você é o CFO de bolso do app FINTECPESSOAL: consultor pessoal, direto, caloroso e específico.\n"
    "Você recebe um RESUMO numérico das finanças da pessoa (NUNCA inventa dados).\n"
    f"Responda APENAS com JSON, sem texto fora do JSON, seguindo exatamente esta estrutura:\n"
    '{"saudacao": string curta de 1-2 frases, chamando a pessoa pelo nome,\n'
    f'"insights": array com até {_MAX_INSIGHTS} frases objetivas (valores, prazos) do que merece atenção/celebração hoje,\n'
    '"alerta": string curta sobre o 1 risco mais urgente OU string vazia se nada for urgente,\n'
    '"dica": string curta de 1 ação concreta para hoje}\n'
    "Regras: português do Brasil; 2ª pessoa (\"você\"); nunca use suposições fora dos dados;\n"
    "frases curtas (<120 caracteres); números sempre presentes quando fizer sentido; sem emojis."
)


def _end_of_day_ttl() -> int:
    now = timezone.localtime()
    end_of_day = datetime.combine(
        now.date() + timedelta(days=1),
        datetime.min.time(),
        tzinfo=now.tzinfo,
    )
    return max(60, int((end_of_day - now).total_seconds()))


def _prompt_for(digest: dict) -> str:
    return (
        "Resumo financeiro de hoje (valores em CENTAVOS):\n"
        + json.dumps(digest, ensure_ascii=False, default=str)
    )


def _clean_str(value, default: str = "") -> str:
    if isinstance(value, str):
        return value.strip()
    return default


def _normalize(result: dict) -> dict:
    saudacao = _clean_str(result.get("saudacao")) or "Olá! Seus números estão em dia."
    insights_raw = result.get("insights")
    insights: list[str] = []
    if isinstance(insights_raw, list):
        for item in insights_raw:
            text = _clean_str(item)
            if text and len(insights) < _MAX_INSIGHTS:
                insights.append(text[:160])
    return {
        "saudacao": saudacao[:240],
        "insights": insights,
        "alerta": _clean_str(result.get("alerta"))[:200],
        "dica": _clean_str(result.get("dica"))[:200],
    }


# --------------------------------------------------------------------------- #
# Determinístico (custo zero — garante presença contínua)
# --------------------------------------------------------------------------- #

_TIPS = [
    "Separe 10% da próxima receita antes de gastar — pague-se primeiro.",
    "Revise hoje uma assinatura recorrente: R$ 30/mês viram R$ 360 no ano.",
    "Olhe a previsão dos próximos 30 dias no menu Lembretes e já programe os pagamentos.",
    "Uma meta pequena e concreta (ex.: R$ 100) cria o hábito antes da meta grande.",
    "Confira a fila de revisão: uma categoria certa hoje gera um relatório honesto amanhã.",
    "Use o Assistente Fintec para lançar em 5 segundos: 'Gastei 58 no Uber'.",
    "Combine saldo das contas com o que está comprometido no cartão antes de assumir novo gasto.",
    "Todo lançamento importa: um grande erro normalmente começa como um pequeno esquecimento.",
]


def _money(cents: int) -> str:
    try:
        cents = int(cents or 0)
    except (TypeError, ValueError):
        cents = 0
    sign = "-" if cents < 0 else ""
    v = abs(cents)
    reais, cent = divmod(v, 100)
    return f"{sign}R$ {reais:,}".replace(",", ".") + f",{cent:02d}"


def _fallback(digest: dict) -> dict:
    nome = digest.get("nome") or "você"
    insight_texts: list[str] = []
    for alerta in digest.get("alertas") or []:
        if len(insight_texts) >= _MAX_INSIGHTS:
            break
        titulo = _clean_str(alerta.get("titulo"))
        descricao = _clean_str(alerta.get("descricao"))
        insight_texts.append(f"{titulo}: {descricao}"[:160])

    if not insight_texts and digest.get("spending"):
        top = digest["spending"][0]
        insight_texts.append(
            f"Sua maior categoria é {top['nome']} ({top['pct']}% das despesas do mês, {_money(top['valor_centavos'])})."
        )
    if not insight_texts and digest.get("disponivel_centavos"):
        insight_texts.append(
            f"Seu saldo disponível hoje é {_money(digest['disponivel_centavos'])}."
        )
    if len(insight_texts) < 2 and digest.get("resultado_centavos"):
        resultado = digest["resultado_centavos"]
        if resultado >= 0:
            insight_texts.append(
                f"Nos últimos 30 dias você fechou com resultado positivo de {_money(resultado)} — continue o ritmo."
            )
        else:
            insight_texts.append(
                f"Nos últimos 30 dias você gastou {_money(abs(resultado))} acima do que entrou — atenção."
            )

    alerta = ""
    for item in digest.get("alertas") or []:
        if item.get("severidade") in ("critical", "attention"):
            alerta = _clean_str(item.get("titulo"))
            break

    dica = _pick_tip(digest)
    return {
        "saudacao": f"Olá, {nome}! Seus números de hoje: {_summary_line(digest)}",
        "insights": insight_texts[: _MAX_INSIGHTS],
        "alerta": alerta,
        "dica": dica,
    }


def _summary_line(digest: dict) -> str:
    if digest.get("despesas_centavos") or digest.get("resultado_centavos"):
        return f"resultado de {_money(digest['resultado_centavos'])} nos últimos 30 dias"
    if digest.get("disponivel_centavos"):
        return f"saldo disponível de {_money(digest['disponivel_centavos'])}"
    return "pronto para começar a organizar suas finanças"


def _pick_tip(digest: dict) -> str:
    if not digest.get("despesas_centavos") and not digest.get("receitas_centavos"):
        return (
            "Comece registrando uma despesa ou receita: com o Assistente Fintec "
            "leva 5 segundos (ex.: 'Gastei 58 no Uber')."
        )
    if digest.get("resultado_centavos", 0) < 0:
        return (
            "Prioridade de hoje: encontrar um gasto descartável acima de um valor "
            "fixo mensal e cortá-lo — cada corte recupera seu resultado."
        )
    index = timezone.localdate().toordinal() % len(_TIPS)
    return _TIPS[index]


# --------------------------------------------------------------------------- #
# API pública
# --------------------------------------------------------------------------- #


def daily_presence(user, *, force: bool = False, data: dict | None = None) -> dict:
    """Presença do CFO para hoje (cacheada; determinística se IA não couber).

    ``data`` é o contexto já construído por ``build_dashboard`` (opcional,
    evita recomputar as consultas quando a página do dashboard chama esta função).
    """
    today = timezone.localdate().isoformat()
    key = f"ai:presence:{user.pk}:{today}"
    if not force:
        cached = cache.get(key)
        if cached is not None:
            return cached
    digest = build_digest(user, data=data)
    presence = _try_ai(user, digest) or _fallback(digest)
    cache.set(key, presence, timeout=_end_of_day_ttl())
    return presence


def _try_ai(user, digest: dict) -> dict | None:
    if not ai_enabled():
        return None
    if not breaker.permission_granted():
        return None
    if not ledger.consume("presence", user, budget.PRESENCE_DAILY_CAP):
        return None
    try:
        result = generate_json(
            system_prompt=_SYSTEM_PROMPT,
            user_prompt=_prompt_for(digest),
            max_output_tokens=budget.OUTPUT_TOKENS_PRESENCE,
        )
        breaker.report_success()
    except Exception:  # noqa: BLE001 — qualquer falha desce para o determinístico.
        breaker.report_failure()
        return None
    presence = _normalize(result)
    if not presence["insights"]:
        # IA respondeu vazio: garante algo sempre no mesmo formato.
        presence = _fallback(digest)
    presence["via_ia"] = True
    presence["gerado_em"] = timezone.now().isoformat()
    return presence


def ai_status(user) -> dict:
    """Estado econômico da IA para a interface (não gera chamada)."""
    return {
        "enabled": ai_enabled(),
        "breaker_open": not breaker.permission_granted(),
        "restantes_consultas": ledger.remaining(
            "consult", user, budget.CONSULT_DAILY_CAP
        ),
        "limite_consultas": budget.CONSULT_DAILY_CAP,
    }