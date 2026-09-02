"""Motor de INSIGHTS DETERMINÍSTICOS do dashboard (sem IA/LLM).

Transforma os dados financeiros do usuário em objetos estruturados ``Insight``,
cada um com:
    type, severity, title, description, metric, period, action

Regras 100% determinísticas (estatística simples e explicável). Uma regra só
produz uma afirmação quando há amostra suficiente — caso contrário NÃO emite
nada (nunca inventa/estima).

Prioridade de exibição (sistema de prioridade):
    critical > attention > info
e, dentro do mesmo nível, por impacto monetário / urgência.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from apps.cards.models import CreditCardInvoice
from apps.finance.models import Transaction

SEVERITY_ORDER = {"critical": 0, "attention": 1, "info": 2}
_SEVERITY_LABEL = {
    "critical": "Crítico",
    "attention": "Atenção",
    "info": "Informação",
}


@dataclass
class Insight:
    type: str
    severity: str  # critical | attention | info
    title: str
    description: str
    metric: str = ""
    period: str = ""
    action: str = ""

    @property
    def severity_label(self) -> str:
        return _SEVERITY_LABEL.get(self.severity, self.severity)

    @property
    def sort_key(self) -> tuple:
        return (SEVERITY_ORDER.get(self.severity, 9),)


# --------------------------------------------------------------------------- #
# Constantes das regras (documentadas em docs/DASHBOARD.md)
# --------------------------------------------------------------------------- #

# Amostra mínima: uma categoria precisa ter gasto em >= 2 dos 3 meses anteriores
# para que seu "padrão" seja comparado.
MIN_PATTERN_MONTHS = 3
MIN_PATTERN_SAMPLE = 2
# Acima de X% do padrão próprio personal => alerta de atenção.
PATTERN_OVERRUN_PCT = 30
# Despesa é "excepcional" quando >= 3x o gasto médio da categoria/do usuário.
ANOMALY_MULTIPLE = 3
# Concentração: top categoria >= 50% das despesas do período.
CONCENTRATION_PCT = 50
# Limite do cartão considerado "próximo do limite".
LIMIT_ALERT_PCT = 80
# Horizonte (dias) para considerar fatura "próxima".
INVOICE_NEAR_DAYS = 3
INVOICE_SOON_DAYS = 7
# Mínimo absoluto (centavos) para uma despesa ser classificada como excepcional.
ANOMALY_FLOOR = 50_000  # R$ 500,00


# --------------------------------------------------------------------------- #
# Motor
# --------------------------------------------------------------------------- #


def analyze(*, user, data) -> list[Insight]:
    """Gera e ordena insights a partir do ViewModel ``data``.

    Recebe ``data`` (DashboardData) já montado; NÃO consulta o banco aqui —
    evita duplicar leitura e mantém o motor puro/testável.
    """
    insights: list[Insight] = []
    _liquidity_risk(data, insights)
    _invoice_insufficient_balance(data, insights)
    _category_pattern(data, insights)
    _anomalous_expense(data, insights)
    _spending_concentration(data, insights)
    _largest_category(data, insights)
    _limits_warning(data, insights)
    _budget_alerts(data, insights)
    _goal_alerts(data, insights)
    _debt_overview(data, insights)

    insights.sort(key=lambda i: i.sort_key)
    return insights


# ---- Regras --------------------------------------------------------------- #


def _liquidity_risk(data, insights) -> None:
    disp = data["disponivel"]
    comp = data["comprometido"]
    if comp <= 0:
        return
    if disp - comp < 0:
        insights.append(
            Insight(
                type="liquidity",
                severity="critical",
                title="Saldo projetado pode ficar negativo",
                description=(
                    "Somando suas obrigações de cartão não liquidadas, o valor "
                    "disponível ficaria negativo. Revise gastos e pagamentos nas "
                    "próximas semanas."
                ),
                metric=f"{data['money'](comp)} comprometidos",
                period="projeção imediata",
                action="Pague ou renegocie faturas e reduza novas compras no cartão.",
            )
        )
    elif disp - comp < data["money_floor_low"]:
        insights.append(
            Insight(
                type="liquidity",
                severity="attention",
                title="Margem de liquidez apertada",
                description=(
                    "Após descontar as obrigações de cartão pendentes, resta uma "
                    "margem financeira pequena. Evite novos compromissos por ora."
                ),
                metric=data["money"](comp),
                period="projeção imediata",
                action="Acompanhe seus compromissos dos próximos dias.",
            )
        )


def _invoice_insufficient_balance(data, insights) -> None:
    disp = data["disponivel"]
    today = data["today"]
    for inv in data.get("invoice_events", []):
        days = (inv.date - today).days
        if 0 <= days <= INVOICE_NEAR_DAYS and inv.amount > disp:
            insights.append(
                Insight(
                    type="invoice_liquidity",
                    severity="critical",
                    title="Fatura próxima acima do saldo",
                    description=(
                        f"{inv.label} vence em breve e seu saldo atual não cobre "
                        "o valor. Garanta recursos antes do vencimento."
                    ),
                    metric=data["money"](inv.amount),
                    period=inv.date.strftime("%d/%m"),
                    action="Verifique seu saldo e programe o pagamento.",
                )
            )
            return


def _category_pattern(data, insights) -> None:
    """Gasto por categoria acima do PADRÃO PESSOAL (trailing meses)."""
    today = data["today"]
    current = data.get("month_category_spend", {})  # {cat_id: amount}
    if not current:
        return
    pattern = data.get("category_pattern", {})  # {cat_id: (avg_monthly, sample_count)}
    for cat_id, amount in current.items():
        entry = pattern.get(cat_id)
        if not entry:
            continue
        avg_monthly, sample = entry
        if sample < MIN_PATTERN_SAMPLE:
            continue  # amostra insuficiente -> não faz afirmação
        if avg_monthly <= 0:
            continue
        overrun = (amount - avg_monthly) / avg_monthly * 100
        if overrun >= PATTERN_OVERRUN_PCT:
            name = data.get("category_names", {}).get(cat_id, "Esta categoria")
            insights.append(
                Insight(
                    type="pattern",
                    severity="attention",
                    title=f"Gasto acima do seu padrão em {name}",
                    description=(
                        f"Você gastou {int(round(overrun))}% acima da sua média em "
                        f"{name}. Sendo {data['money'](avg_monthly)} a média mensal "
                        f"e {data['money'](amount)} neste mês."
                    ),
                    metric=data["money"](amount),
                    period="mês atual vs média anterior",
                    action=f"Revise os lançamentos em {name}.",
                )
            )


def _anomalous_expense(data, insights) -> None:
    today = data["today"]
    avg = data.get("average_expense")  # valor médio da despesa (amostra >= 5)
    recent = data.get("recent_expenses", [])  # últimas despesas do período
    if avg is None or avg <= 0:
        return
    for tx in recent:
        if tx.amount >= avg * ANOMALY_MULTIPLE and tx.amount >= ANOMALY_FLOOR:
            insights.append(
                Insight(
                    type="anomaly",
                    severity="attention",
                    title="Despesa excepcionalmente alta",
                    description=(
                        f"{tx.description or 'Lançamento'} de "
                        f"{data['money'](tx.amount)} destoa do seu valor típico "
                        f"de despesa ({data['money'](avg)})."
                    ),
                    metric=data["money"](tx.amount),
                    period=tx.date.strftime("%d/%m"),
                    action="Confira se o valor está correto.",
                )
            )
            return


def _spending_concentration(data, insights) -> None:
    rows = data.get("spending_rows", [])
    total = sum(r.amount for r in rows)
    if total <= 0 or not rows:
        return
    top = rows[0]
    top_share = int(round(top.amount / total * 100))
    if top_share >= CONCENTRATION_PCT:
        insights.append(
            Insight(
                type="concentration",
                severity="attention",
                title="Gastos concentrados em uma categoria",
                description=(
                    f"{top.name} concentra {top_share}% das suas despesas no "
                    "período, o que aumenta a sensibilidade a variações."
                ),
                metric=f"{top_share}% em {top.name}",
                period=data.get("period_label", ""),
                action="Avalie se essa concentração é esperada ou se vale distribuir.",
            )
        )


def _largest_category(data, insights) -> None:
    rows = data.get("spending_rows", [])
    if not rows or rows[0].amount <= 0:
        return
    insights.append(
        Insight(
            type="top_category",
            severity="info",
            title=f"Sua maior categoria é {rows[0].name}",
            description=(
                f"{rows[0].name} responde por {rows[0].share_percent}% das suas "
                "despesas deste período."
            ),
            metric=data["money"](rows[0].amount),
            period=data.get("period_label", ""),
            action="",
        )
    )


def _limits_warning(data, insights) -> None:
    for card in data.get("cards", []):
        if card.limit > 0 and card.used / card.limit * 100 >= LIMIT_ALERT_PCT:
            insights.append(
                Insight(
                    type="limit",
                    severity="attention",
                    title=f"{card.name} próximo do limite",
                    description=(
                        f"Uso de {int(round(card.used / card.limit * 100))}% do "
                        "seu limite de crédito. Perto do teto, compras podem ser "
                        "negadas e o custo de juros aumenta."
                    ),
                    metric=data["money"](card.used),
                    period="atual",
                    action=f"Libere limite em {card.name} pagando faturas.",
                )
            )


def _budget_alerts(data, insights) -> None:
    for row in data.get("budgets", []):
        if row.status == "exceeded":
            insights.append(
                Insight(
                    type="budget",
                    severity="attention",
                    title=f"Orçamento de {row.name} excedido",
                    description=(
                        f"Você gastou {row.percent}% do limite de "
                        f"{data['money'](row.limit)} em {row.name}."
                    ),
                    metric=data["money"](row.spent),
                    period="mês atual",
                    action=f"Revise os gastos de {row.name}.",
                )
            )
        elif row.status == "attention":
            insights.append(
                Insight(
                    type="budget",
                    severity="info",
                    title=f"Orçamento de {row.name} quase no limite",
                    description=(
                        f"Uso de {row.percent}% do orçamento de "
                        f"{data['money'](row.limit)}."
                    ),
                    metric=f"{row.percent}%",
                    period="mês atual",
                    action="",
                )
            )


def _goal_alerts(data, insights) -> None:
    today = data["today"]
    for goal in data.get("goals", []):
        if goal.status == "paused":
            continue
        if (
            goal.target_date
            and goal.target_date < today
            and goal.current_amount < goal.target_amount
        ):
            insights.append(
                Insight(
                    type="goal",
                    severity="attention",
                    title=f"Meta '{goal.name}' com prazo vencido",
                    description=(
                        f"Meta de {data['money'](goal.target_amount)} venceu e "
                        f"você acumulou {data['money'](goal.current_amount)} "
                        f"({goal.progress_percent}%)."
                    ),
                    metric=f"{goal.progress_percent}%",
                    period="prazo vencido",
                    action=f"Revise os prazos ou o valor da meta '{goal.name}'.",
                )
            )


def _debt_overview(data, insights) -> None:
    total_remaining = sum(d.remaining_amount for d in data.get("debts", []))
    if total_remaining <= 0:
        return
    insights.append(
        Insight(
            type="debt",
            severity="info",
            title=f"{len(data['debts'])} dívida(s) ativa(s)",
            description=(
                f"Resta {data['money'](total_remaining)} a pagar em "
                "dívidas ativas. Priorize as de maior custo."
            ),
            metric=data["money"](total_remaining),
            period="atual",
            action="Monte um plano de quitação para as dívidas.",
        )
    )
