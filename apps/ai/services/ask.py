"""Consultoria do CFO ("Pergunte ao CFO"): responda sobre o dinheiro da pessoa.

Economia de tokens: contexto = o mesmo digest enxuto (nunca o extrato). O chat
tem limite diário de chamadas de IA; quando acaba (ou a IA está fora), um motor
determinístico responde com os mesmos dados — a consultoria nunca fica muda e
não custa um token.
"""

from __future__ import annotations

import json

from apps.ai import budget
from apps.ai.services import breaker, ledger
from apps.core.services.ai import ai_enabled, generate_json

from .digest import build_digest
from .presence import _money

_SYSTEM_PROMPT = """Você é o CFO de bolso do FINTECPESSOAL. A pessoa te pergunta algo sobre o PRÓPRIO dinheiro.
Você recebe um resumo numérico (valores em CENTAVOS) e a pergunta dela.
Responda APENAS JSON, sem texto fora, com a estrutura:
{"resposta": string de 2-4 frases diretas com números e um próximo passo concreto}
Regras: português do Brasil; 2ª pessoa ("você"); use SOMENTE os dados do resumo;
não invente projeções nem produtos; se faltar dado, diga exatamente o que ajudaria;
nunca dê uma resposta sem número ou ação."""


def _fallback_response(digest: dict, message: str) -> str:
    """Motor determinístico: mapeia a intenção para um conselho com números."""
    text = (message or "").strip().lower()
    nome = digest.get("nome") or "você"

    if any(p in text for p in ("gasto", "corte", "cortar", "onde", "economia")):
        rows = digest.get("spending") or []
        if rows:
            top = rows[0]
            return (
                f"{nome}, sua maior despesa é {top['nome']} "
                f"({_money(top['valor_centavos'])} no mês, {top['pct']}% do total). "
                f"Reduzir 10% dela já renderia {_money(int(top['valor_centavos'] * 0.1))} por mês. "
                f"Cadastre os lançamentos nessa categoria para ver exatamente o que cortar."
            )
        return "Ainda faltam lançamentos para esse diagnóstico — registre suas despesas e me pergunte de novo."

    if any(p in text for p in ("posso", "quanto", "disponiv", "sobra", "liberado", "fim do mes")):
        disp = digest.get("disponivel_apos_centavos", 0)
        return (
            f"{nome}, seu saldo disponível é {_money(digest.get('disponivel_centavos', 0))} "
            f"e, descontando o comprometido em cartões, sobram {_money(disp)}. "
            f"Regra prática: não assuma compromissos acima desse valor até a próxima receita."
        )

    if any(p in text for p in ("divida", "divid", "quitar", "parcel", "juros")):
        dividas = digest.get("dividas") or []
        total = sum(int(d.get("restante_centavos", 0) or 0) for d in dividas)
        if total > 0:
            targets = ", ".join(f"{d['nome']} ({_money(d['restante_centavos'])})" for d in dividas[:2])
            return (
                f"{nome}, você tem {_money(total)} em dívidas ativas ({targets}). "
                f"Priorize quitar a de maior custo primeiro e quite com o excedente de "
                f"{_money(digest.get('disponivel_apos_centavos', 0))} quando ele existir."
            )
        return "Boa notícia: você não tem dívidas ativas registradas. Continue assim."

    if any(p in text for p in ("guardar", "reserva", "poupar", "meta", "emergencia")):
        metas = digest.get("goals") or []
        if metas:
            g = metas[0]
            return (
                f"{nome}, sua meta '{g['nome']}' está em {g['progresso_pct']}% "
                f"({_money(g['acumulado_centavos'])} de {_money(g['meta_centavos'])}). "
                f"Redirecione {_money(max(int(g['meta_centavos'] * 0.01), 100))} "
                f"antes do fim do dia para acelerar."
            )
        return (
            f"{nome}, comece por uma meta pequena: guarde R$ 100 ainda esta semana "
            f"e registre em Metas. O hábito vale mais que o valor."
        )

    if any(p in text for p in ("fatura", "cartao", "cartão", "limite")):
        cartoes = digest.get("cartoes") or []
        if cartoes:
            c = max(cartoes, key=lambda x: x.get("uso_pct", 0) or 0)
            return (
                f"{nome}, o cartão {c['nome']} está em {c['uso_pct']}% do limite "
                f"({_money(c['usado_centavos'])} de {_money(c['limite_centavos'])}). "
                f"Libere limite pagando a fatura antes do vencimento."
            )
        return "Você ainda não cadastrou cartões — adicione em Cartões para acompanhar a fatura."

    if any(p in text for p in ("patrimonio", "patrimônio", "tenho", "riqueza", "crescendo")):
        return (
            f"{nome}, seu patrimônio total hoje é {_money(digest.get('patrimonio_centavos', 0))}. "
            f"Ele é a soma de todas as contas menos o comprometido em cartões e dívidas."
        )

    # Resposta geral com base no resumo.
    if digest.get("resultado_centavos", 0) >= 0:
        return (
            f"{nome}, seu resultado dos últimos 30 dias foi positivo em "
            f"{_money(digest['resultado_centavos'])}. "
            f"Próximo passo: separe uma parte disso para uma meta antes de aumentar gastos."
        )
    return (
        f"{nome}, você está gastando {_money(abs(digest.get('resultado_centavos', 0)))} "
        f"mais do que entra a cada 30 dias. Foco de hoje: cortar um gasto recorrente e "
        f"criar seu primeiro orçamento em Planejamento."
    )


_last_via_ia = False


def ai_status(user) -> dict:
    """Estado econômico da consultoria (sem gerar chamada de IA)."""
    enabled = ai_enabled()
    return {
        "enabled": enabled,
        "breaker_open": not breaker.permission_granted(),
        "budget_exhausted": enabled
        and not ledger.remaining("consult", user, budget.CONSULT_DAILY_CAP)
        if enabled
        else False,
    }


def answer(user, message: str) -> dict:
    """Responde a pergunta com IA (se couber no orçamento) ou determinado."""
    message = (message or "").strip()[:500]
    if not message:
        return {
            "resposta": "Me pergunte qualquer coisa sobre seu dinheiro!",
            "via_ia": False,
            "restantes": None,
            "limite": False,
        }

    digest = build_digest(user)
    resposta = _try_ai(user, message, digest)
    status = ai_status(user)
    limite = resposta is None and status["enabled"] and status["budget_exhausted"]
    if resposta is None:
        resposta = _fallback_response(digest, message)

    if not status["enabled"] or status["breaker_open"]:
        restantes = None
    elif limite:
        restantes = 0
    else:
        restantes = ledger.remaining("consult", user, budget.CONSULT_DAILY_CAP)
    return {
        "resposta": resposta,
        "via_ia": _last_via_ia,
        "restantes": restantes,
        "limite": limite,
    }


def _try_ai(user, message: str, digest: dict) -> str | None:
    global _last_via_ia
    _last_via_ia = False
    if not ai_enabled():
        return None
    if not breaker.permission_granted():
        return None
    if not ledger.consume("consult", user, budget.CONSULT_DAILY_CAP):
        return None
    try:
        result = generate_json(
            system_prompt=_SYSTEM_PROMPT,
            user_prompt=(
                f"Resumo (valores em CENTAVOS):\n"
                + json.dumps(digest, ensure_ascii=False, default=str)
                + f"\n\nPergunta: {message}"
            ),
            max_output_tokens=budget.OUTPUT_TOKENS_CONSULT,
        )
        breaker.report_success()
    except Exception:  # noqa: BLE001 — qualquer falha desce para o determinístico.
        breaker.report_failure()
        return None
    resposta = (result or {}).get("resposta")
    if not isinstance(resposta, str) or not resposta.strip():
        return None
    _last_via_ia = True
    return resposta.strip()[:800]