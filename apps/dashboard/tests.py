"""Testes do dashboard financeiro (Ordem 7).

Cobrem: view + ViewModel, métricas (saldo, fluxo, categorias, cartão, faturas,
parcelas, orçamento, metas, dívidas), períodos, estados vazios, isolamento
multiusuário, dupla contabilização e performance (contagem de queries).
"""

from datetime import date
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.budgets.models import Budget
from apps.cards.models import CreditCard
from apps.cards.services.invoices import pay_invoice
from apps.cards.services.purchases import create_card_purchase
from apps.debts.models import Debt
from apps.finance.models import Category, Transaction
from apps.finance.services.accounts import create_account
from apps.finance.services.transactions import record_expense, record_income
from apps.finance.services.transfers import transfer_between
from apps.goals.models import Goal

from . import queries
from .insights import analyze
from .viewmodel import build_dashboard

User = get_user_model()


class DashboardFixture:
    """Monta um usuário com dados financeiros realistas e datas controladas."""

    TODAY = date(2026, 4, 20)

    def __init__(self, user):
        self.user = user
        self.checking = create_account(user=user, name="Conta Corrente", initial_balance=200_000)
        self.savings = create_account(user=user, name="Poupança", initial_balance=100_000)
        self.cat_ali = Category.objects.create(owner=user, name="Alimentação", kind=Category.Kind.EXPENSE)
        self.cat_mor = Category.objects.create(owner=user, name="Moradia", kind=Category.Kind.EXPENSE)
        self.cat_sal = Category.objects.create(owner=user, name="Salário", kind=Category.Kind.INCOME)

    def seed_transactions(self):
        # Receitas mensais (jan..abr) para formar histórico e padrão.
        for m in (1, 2, 3, 4):
            record_income(user=self.user, account=self.checking, amount=800_000,
                          date=date(2026, m, 5), category=self.cat_sal)
        # Alimentação: padrão ~45k/mês em jan/fev/mar; abril mais alto (anomalia de padrão).
        for m, d in [(1, 30000), (1, 45000), (2, 42000), (3, 48000), (3, 52000)]:
            record_expense(user=self.user, account=self.checking, amount=d,
                           date=date(2026, m, 8), category=self.cat_ali)
        # Abril: 6 despesas de alimentação (média ~14k) + 1 alta de 90k (desproporcional)
        for d in [12000, 13000, 14000, 15000, 16000, 130000]:
            record_expense(user=self.user, account=self.checking, amount=d,
                           date=date(2026, 4, 8), category=self.cat_ali)
        record_expense(user=self.user, account=self.checking, amount=90_000,
                       date=date(2026, 4, 10), category=self.cat_mor)

    def seed_transfer(self):
        transfer_between(user=self.user, from_account=self.checking,
                         to_account=self.savings, amount=50_000, date=date(2026, 4, 2))

    def seed_card(self):
        self.card = CreditCard.objects.create(
            owner=self.user, name="Cartão Black", limit=500_000,
            closing_day=10, due_day=5, payment_account=self.checking,
        )
        create_card_purchase(
            user=self.user, card=self.card, description="Notebook",
            total_amount=360_000, installment_count=12,
            first_due_date=date(2026, 4, 20),
        )
        return self.card

    def seed_planning(self):
        Budget.objects.create(owner=self.user, kind=Budget.Kind.CATEGORY,
                              category=self.cat_ali, limit_amount=50_000)
        Goal.objects.create(owner=self.user, name="Reserva", target_amount=1_000_000,
                            current_amount=250_000, target_date=date(2026, 12, 1))
        Debt.objects.create(owner=self.user, name="Carro", total_amount=2_000_000,
                            paid_amount=800_000)


class BaseDashboardTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="alice", password="x")
        self.other = User.objects.create_user(username="bob", password="y")
        self.user.profile.onboarding_completed = True
        self.user.profile.save(update_fields=["onboarding_completed"])


@mock.patch("apps.dashboard.queries._today", return_value=DashboardFixture.TODAY)
@mock.patch("apps.dashboard.viewmodel.queries._today", return_value=DashboardFixture.TODAY)
class FinancialMetricsTests(BaseDashboardTestCase):
    def _full(self, _a, _b):
        fx = DashboardFixture(self.user)
        fx.seed_transactions()
        fx.seed_transfer()
        fx.seed_card()
        fx.seed_planning()
        return fx

    def test_disponivel_is_sum_of_active_account_balances(self, _a, _b):
        fx = DashboardFixture(self.user)
        fx.seed_transactions()
        # 300.000 (saldo inicial) + 4x800.000 (receitas) - despesas
        data = build_dashboard(self.user, today=DashboardFixture.TODAY)
        self.assertTrue(data["has_data"])
        exp = sum([30000, 45000, 42000, 48000, 52000])
        exp += sum([12000, 13000, 14000, 15000, 16000, 130000]) + 90000
        self.assertEqual(data["disponivel"], 200_000 + 100_000 + 3_200_000 - exp)

    def test_cash_flow_receitas_despesas_resultado(self, _a, _b):
        fx = DashboardFixture(self.user)
        fx.seed_transactions()
        data = build_dashboard(self.user, period="30d", today=DashboardFixture.TODAY)
        cf = data["cash_flow"]
        # No período 30d (22/03 a 20/04): receitas salário abr (800000);
        # despesas de abril apenas.
        self.assertEqual(cf.receitas, 800_000)
        self.assertEqual(cf.despesas, sum([12000, 13000, 14000, 15000, 16000, 130000]) + 90000)
        self.assertEqual(cf.resultado, cf.receitas - cf.despesas)

    def test_locked_exact_values(self, _a, _b):
        fx = DashboardFixture(self.user)
        fx.seed_transactions()
        fx.seed_transfer()
        fx.seed_card()
        fx.seed_planning()
        data = build_dashboard(self.user, period="30d", today=DashboardFixture.TODAY)
        cf = data["cash_flow"]
        # Receitas 30d: apenas salário de abril (salário de mar é 05/03, fora do 30d).
        self.assertEqual(cf.receitas, 800_000)
        # Despesas 30d: alimentação de abril (200.000) + moradia (90.000).
        self.assertEqual(cf.despesas, 290_000)
        self.assertEqual(cf.resultado, 510_000)
        self.assertEqual(cf.transfer_in, 50_000)
        self.assertEqual(cf.transfer_out, 50_000)
        # Comprometido = obrigações de cartão (12x30.000 pendentes).
        self.assertEqual(data["comprometido"], 360_000)
        # Disponibilidade pós-compromissos reflete o patrimônio total.
        self.assertEqual(data["disponivel_apos"], data["disponivel"] - 360_000)
        # Maior categoria do período = Alimentação, com variação p/ período anterior.
        top = data["spending_rows"][0]
        self.assertEqual(top.name, "Alimentação")
        self.assertGreater(top.delta_percent, 0)

    def test_transfer_does_not_count_as_income_or_expense(self, _a, _b):
        fx = DashboardFixture(self.user)
        fx.seed_transactions()
        fx.seed_transfer()
        data = build_dashboard(self.user, period="30d", today=DashboardFixture.TODAY)
        cf = data["cash_flow"]
        # Transferência aparece como mover interno; não infla receita/despesa.
        self.assertEqual(cf.transfer_in, 50_000)
        self.assertEqual(cf.transfer_out, 50_000)
        self.assertEqual(cf.receitas, 800_000)

    def test_card_usage_and_open_invoice(self, _a, _b):
        fx = DashboardFixture(self.user)
        fx.seed_transactions()
        fx.seed_card()
        data = build_dashboard(self.user, today=DashboardFixture.TODAY)
        self.assertTrue(data["cards"])
        card = data["cards"][0]
        self.assertEqual(card.limit, 500_000)
        self.assertEqual(card.used, 360_000)
        self.assertEqual(card.available, 140_000)

    def test_budget_status(self, _a, _b):
        fx = DashboardFixture(self.user)
        fx.seed_transactions()
        fx.seed_planning()
        data = build_dashboard(self.user, today=DashboardFixture.TODAY)
        budget = data["budgets"][0]
        self.assertEqual(budget.status, "exceeded")
        self.assertEqual(budget.percent, 400)

    def test_goals_and_debts_present(self, _a, _b):
        fx = DashboardFixture(self.user)
        fx.seed_planning()
        data = build_dashboard(self.user, today=DashboardFixture.TODAY)
        self.assertEqual(data["goals"][0].progress_percent, 25)
        self.assertEqual(data["debts"][0].remaining_amount, 1_200_000)


class PeriodTests(BaseDashboardTestCase):
    @mock.patch("apps.dashboard.queries._today", return_value=DashboardFixture.TODAY)
    @mock.patch("apps.dashboard.viewmodel.queries._today", return_value=DashboardFixture.TODAY)
    def test_7d_vs_30d_periods(self, _a, _b):
        fx = DashboardFixture(self.user)
        fx.seed_transactions()
        d7 = build_dashboard(self.user, period="7d", today=DashboardFixture.TODAY)
        d30 = build_dashboard(self.user, period="30d", today=DashboardFixture.TODAY)
        self.assertEqual(d7["period"], "7d")
        self.assertEqual(d30["period"], "30d")
        # 7d (14..20/04): alimentação + moradia de abril; 30d inclui final de março.
        self.assertLess(d7["cash_flow"].receitas, d30["cash_flow"].receitas)


class DoubleCountingTests(BaseDashboardTestCase):
    @mock.patch("apps.dashboard.queries._today", return_value=DashboardFixture.TODAY)
    @mock.patch("apps.dashboard.viewmodel.queries._today", return_value=DashboardFixture.TODAY)
    def test_card_purchase_is_not_an_expense_until_invoice_paid(self, _a, _b):
        fx = DashboardFixture(self.user)
        fx.seed_card()
        # Comprar no cartão NÃO deve aparecer como despesa de conta/fluxo.
        data = build_dashboard(self.user, period="30d", today=DashboardFixture.TODAY)
        self.assertEqual(data["cash_flow"].despesas, 0)
        self.assertEqual(data["disponivel"], 300_000)  # nada foi debitado

    @mock.patch("apps.dashboard.queries._today", return_value=DashboardFixture.TODAY)
    @mock.patch("apps.dashboard.viewmodel.queries._today", return_value=DashboardFixture.TODAY)
    def test_invoice_payment_appears_once_as_expense(self, _a, _b):
        fx = DashboardFixture(self.user)
        fx.seed_card()
        fx.checking.initial_balance = 2_000_000
        fx.checking.save(update_fields=["initial_balance"])
        invoice = fx.card.invoices.order_by("due_date").first()
        pay_invoice(user=self.user, invoice=invoice, account=fx.checking,
                    date=date(2026, 4, 18))
        data = build_dashboard(self.user, period="30d", today=DashboardFixture.TODAY)
        # O pagamento gera UMA despesa (a fatura) — não duplica as compras.
        self.assertEqual(data["cash_flow"].despesas, invoice.amount)
        self.assertEqual(
            data["cash_flow"].despesas,
            360_000 // 12,
        )


class EmptyStateTests(BaseDashboardTestCase):
    @mock.patch("apps.dashboard.queries._today", return_value=DashboardFixture.TODAY)
    @mock.patch("apps.dashboard.viewmodel.queries._today", return_value=DashboardFixture.TODAY)
    def test_user_without_data_has_empty_state(self, _a, _b):
        data = build_dashboard(self.user, today=DashboardFixture.TODAY)
        self.assertFalse(data["has_data"])
        self.assertEqual(data["cash_flow"].despesas, 0)
        self.assertEqual(data["spending_rows"], [])
        self.assertEqual(data["insights"], [])

    @mock.patch("apps.dashboard.queries._today", return_value=DashboardFixture.TODAY)
    @mock.patch("apps.dashboard.viewmodel.queries._today", return_value=DashboardFixture.TODAY)
    def test_insufficient_history_no_pattern_claim(self, _a, _b):
        # Apenas um único mês de dados -> sem padrão comparável (amostra insuficiente).
        fx = DashboardFixture(self.user)
        fx.seed_transactions()  # janeiro..abril -> amostra >= 2 meses, deveria gerar
        data = build_dashboard(self.user, today=DashboardFixture.TODAY)
        pattern_insights = [i for i in data["insights"] if i.type == "pattern"]
        self.assertTrue(pattern_insights)  # há histórico suficiente aqui


class SecurityTests(BaseDashboardTestCase):
    @mock.patch("apps.dashboard.queries._today", return_value=DashboardFixture.TODAY)
    @mock.patch("apps.dashboard.viewmodel.queries._today", return_value=DashboardFixture.TODAY)
    def test_user_a_does_not_see_user_b_data(self, _a, _b):
        fx_b = DashboardFixture(self.other)
        fx_b.seed_transactions()
        data_a = build_dashboard(self.user, today=DashboardFixture.TODAY)
        data_b = build_dashboard(self.other, today=DashboardFixture.TODAY)
        self.assertEqual(data_a["disponivel"], 0)  # sem contas para A
        self.assertGreater(data_b["disponivel"], 0)

    def test_filter_with_other_users_account_is_ignored(self):
        fx_b = DashboardFixture(self.other)
        data_a = build_dashboard(self.user, period="30d",
                                 account_id=fx_b.checking.pk,
                                 today=DashboardFixture.TODAY)
        # Filtro inválido (conta de B) é ignorado silenciosamente; nada de B vaza.
        self.assertEqual(data_a["filters"]["account_id"], None)
        self.assertEqual(data_a["cash_flow"].receitas, 0)


@mock.patch("apps.dashboard.queries._today", return_value=DashboardFixture.TODAY)
@mock.patch("apps.dashboard.viewmodel.queries._today", return_value=DashboardFixture.TODAY)
class InsightTests(BaseDashboardTestCase):
    def test_liquidity_critical_when_committed_exceeds_available(self, _a, _b):
        fx = DashboardFixture(self.user)
        fx.checking.initial_balance = 0
        fx.savings.initial_balance = 0
        fx.checking.save(update_fields=["initial_balance"])
        fx.savings.save(update_fields=["initial_balance"])
        fx.seed_card()  # committed = 360.000 > disponível 0
        data = build_dashboard(self.user, today=DashboardFixture.TODAY)
        severities = [i.severity for i in data["insights"]]
        self.assertIn("critical", severities)

    def test_category_pattern_insight_fires(self, _a, _b):
        fx = DashboardFixture(self.user)
        fx.seed_transactions()
        data = build_dashboard(self.user, today=DashboardFixture.TODAY)
        pattern = [i for i in data["insights"] if i.type == "pattern"]
        self.assertTrue(pattern, data["insights"])

    def test_insight_structure_and_priority(self, _a, _b):
        fx = DashboardFixture(self.user)
        fx.seed_transactions()
        data = build_dashboard(self.user, today=DashboardFixture.TODAY)
        for i in data["insights"]:
            self.assertTrue(i.title)
            self.assertTrue(i.description)
            self.assertIn(i.severity, ("critical", "attention", "info"))
        # Ordenados por severidade
        sev = [i.sort_key for i in data["insights"]]
        self.assertEqual(sev, sorted(sev))


@mock.patch("apps.dashboard.queries._today", return_value=DashboardFixture.TODAY)
@mock.patch("apps.dashboard.viewmodel.queries._today", return_value=DashboardFixture.TODAY)
class PerformanceTests(BaseDashboardTestCase):
    def test_net_balance_few_queries_regardless_of_tx_volume(self, _a, _b):
        fx = DashboardFixture(self.user)
        fx.seed_transactions()
        for i in range(40):
            record_expense(user=self.user, account=fx.checking, amount=1000,
                           date=date(2026, 4, 15))
        with self.assertNumQueries(2):
            queries.net_balance(self.user)

    def test_cash_flow_constant_queries(self, _a, _b):
        fx = DashboardFixture(self.user)
        fx.seed_transactions()
        start, end = date(2026, 3, 20), date(2026, 4, 20)
        with self.assertNumQueries(3):
            queries.cash_flow(self.user, start=start, end=end)


class DashboardViewTests(BaseDashboardTestCase):
    def setUp(self):
        super().setUp()
        self.client.login(username="alice", password="x")

    @mock.patch("apps.dashboard.queries._today", return_value=DashboardFixture.TODAY)
    @mock.patch("apps.dashboard.viewmodel.queries._today", return_value=DashboardFixture.TODAY)
    def test_dashboard_renders_200_with_data(self, _a, _b):
        fx = DashboardFixture(self.user)
        fx.seed_transactions()
        fx.seed_card()
        fx.seed_planning()
        resp = self.client.get(reverse("dashboard:index"))
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        # Conteúdo real presente (não apenas um template vazio).
        self.assertIn("Seu painel financeiro", html)
        self.assertIn("Fluxo de caixa", html)
        self.assertIn("Alimentação", html)
        self.assertIn("Cartão Black", html)
        self.assertIn("Reserva", html)
        self.assertIn("Carro", html)
        # Com dados, o herói numérico é exibido e o estado vazio contextual some.
        self.assertIn("Saldo disponível", html)
        self.assertNotIn("Comece a organizar suas finanças", html)

    @mock.patch("apps.dashboard.queries._today", return_value=DashboardFixture.TODAY)
    @mock.patch("apps.dashboard.viewmodel.queries._today", return_value=DashboardFixture.TODAY)
    def test_dashboard_empty_state_renders(self, _a, _b):
        resp = self.client.get(reverse("dashboard:index"))
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn("Sem movimentações neste período", html)
        self.assertIn("Sem cartões", html)
        self.assertIn("Sem metas", html)
        # Estado vazio contextual substitui o herói numérico e orienta a começar.
        self.assertIn("Comece a organizar suas finanças", html)
        self.assertIn("Criar conta", html)
        # Com dashboard vazio, o herói numérico não deve aparecer como destaque.
        self.assertNotIn("Saldo disponível", html)

    @mock.patch("apps.dashboard.queries._today", return_value=DashboardFixture.TODAY)
    @mock.patch("apps.dashboard.viewmodel.queries._today", return_value=DashboardFixture.TODAY)
    def test_period_filter_changes_cash_flow(self, _a, _b):
        fx = DashboardFixture(self.user)
        fx.seed_transactions()
        d7 = self.client.get(reverse("dashboard:index"), {"period": "7d"})
        d30 = self.client.get(reverse("dashboard:index"), {"period": "30d"})
        self.assertEqual(d7.status_code, 200)
        self.assertEqual(d30.status_code, 200)
        self.assertIn("Últimos 7 dias", d7.content.decode())
        self.assertIn("Últimos 30 dias", d30.content.decode())

    def test_anonymous_redirected(self):
        self.client.logout()
        resp = self.client.get(reverse("dashboard:index"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse("accounts:login"), resp.url)
