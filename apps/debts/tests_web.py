"""Testes web do módulo de dívidas (views, ownership e pagamento).

Cobrem o fluxo: listar/criar/editar/detalhar, registrar pagamento (cria UMA
expense real), transições de status, isolamento multiusuário e redirecionamento
de anônimos — sempre via services.
"""

from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils.timezone import localdate

from apps.finance.models import Account, Transaction

from .models import Debt
from .services.debts import create_debt, record_debt_payment

User = get_user_model()


class DebtWebTestBase(TestCase):
    def setUp(self):
        self.alice = User.objects.create_user(
            username="alice", password="senha123", first_name="Alice"
        )
        self.bob = User.objects.create_user(
            username="bob", password="senha123", first_name="Bob"
        )
        self.account_a = Account.objects.create(
            owner=self.alice, name="Conta Alice", initial_balance=1000000
        )
        Account.objects.create(
            owner=self.bob, name="Conta Bob", initial_balance=1000000
        )
        self.login_as(self.alice)

    def login_as(self, user):
        self.client.login(username=user.username, password="senha123")

    def make_debt(self, owner=None, **kwargs):
        owner = owner or self.alice
        defaults = {"name": "Empréstimo", "total_amount": 50000}
        defaults.update(kwargs)
        return create_debt(user=owner, **defaults)


class DebtListViewTests(DebtWebTestBase):
    def test_anonymous_redirected_to_login(self):
        self.client.logout()
        resp = self.client.get(reverse("debts:debt_list"))
        self.assertEqual(resp.status_code, 302)

    def test_authenticated_lists_only_own_debts(self):
        self.make_debt(owner=self.alice, name="Minha Dívida")
        self.make_debt(owner=self.bob, name="Dívida do Bob")
        resp = self.client.get(reverse("debts:debt_list"))
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode()
        self.assertIn("Minha Dívida", content)
        self.assertNotIn("Dívida do Bob", content)


class DebtCreateEditTests(DebtWebTestBase):
    def test_create_debt(self):
        resp = self.client.post(
            reverse("debts:debt_create"),
            {
                "name": "Empréstimo do banco",
                "type": Debt.Type.LOAN,
                "total_amount": "5000",
                "interest_rate": "1.99",
                "start_date": "",
                "end_date": "",
                "creditor": "Banco X",
            },
            follow=True,
        )
        self.assertEqual(resp.status_code, 200)
        debt = Debt.objects.get(owner=self.alice, name="Empréstimo do banco")
        self.assertEqual(debt.total_amount, 500000)
        self.assertEqual(debt.status, Debt.Status.ACTIVE)
        self.assertEqual(debt.creditor, "Banco X")

    def test_edit_debt_updates_amount(self):
        debt = self.make_debt(owner=self.alice, name="Empréstimo", total_amount=50000)
        self.client.post(
            reverse("debts:debt_edit", args=[debt.pk]),
            {
                "name": "Empréstimo",
                "type": Debt.Type.LOAN,
                "total_amount": "9000",
                "interest_rate": "",
                "start_date": "",
                "end_date": "",
                "creditor": "",
            },
        )
        debt.refresh_from_db()
        self.assertEqual(debt.total_amount, 900000)

    def test_edit_other_user_debt_returns_404(self):
        debt = self.make_debt(owner=self.bob, name="Empréstimo", total_amount=50000)
        resp = self.client.post(
            reverse("debts:debt_edit", args=[debt.pk]),
            {
                "name": "Empréstimo",
                "type": Debt.Type.LOAN,
                "total_amount": "1",
                "interest_rate": "",
                "start_date": "",
                "end_date": "",
                "creditor": "",
            },
        )
        self.assertEqual(resp.status_code, 404)

    def test_detail_other_user_debt_returns_404(self):
        debt = self.make_debt(owner=self.bob, name="Empréstimo", total_amount=50000)
        resp = self.client.get(reverse("debts:debt_detail", args=[debt.pk]))
        self.assertEqual(resp.status_code, 404)


class DebtPaymentWebTests(DebtWebTestBase):
    def setUp(self):
        super().setUp()
        self.debt = self.make_debt(owner=self.alice, name="Empréstimo", total_amount=1000000)

    def test_payment_creates_expense_and_accumulates(self):
        resp = self.client.post(
            reverse("debts:debt_pay", args=[self.debt.pk]),
            {
                "account": self.account_a.pk,
                "amount": "4000",
                "date": "2026-09-10",
            },
            follow=True,
        )
        self.assertEqual(resp.status_code, 200)
        self.debt.refresh_from_db()
        self.assertEqual(self.debt.paid_amount, 400000)
        # UMA transação real de despesa (rastreabilidade via contas).
        expenses = Transaction.objects.filter(
            owner=self.alice, type=Transaction.Type.EXPENSE
        )
        self.assertEqual(expenses.count(), 1)
        self.assertEqual(expenses.first().amount, 400000)

    def test_payment_other_user_debt_404(self):
        other_debt = self.make_debt(owner=self.bob, name="Do Bob", total_amount=10000)
        resp = self.client.post(
            reverse("debts:debt_pay", args=[other_debt.pk]),
            {
                "account": self.account_a.pk,
                "amount": "100",
                "date": "2026-09-10",
            },
        )
        self.assertEqual(resp.status_code, 404)

    def test_payment_with_other_user_account_rejected(self):
        bob_account = Account.objects.get(owner=self.bob)
        resp = self.client.post(
            reverse("debts:debt_pay", args=[self.debt.pk]),
            {
                "account": bob_account.pk,
                "amount": "100",
                "date": "2026-09-10",
            },
        )
        # Conta do Bob fora do queryset do form => form inválido; nada muda.
        self.debt.refresh_from_db()
        self.assertEqual(self.debt.paid_amount, 0)
        self.assertEqual(resp.status_code, 200)


class DebtStatusWebTests(DebtWebTestBase):
    def test_default_activate_archive(self):
        debt = self.make_debt(owner=self.alice, name="Empréstimo", total_amount=10000)
        self.client.post(reverse("debts:debt_default", args=[debt.pk]))
        debt.refresh_from_db()
        self.assertEqual(debt.status, Debt.Status.DEFAULTED)

        self.client.post(reverse("debts:debt_activate", args=[debt.pk]))
        debt.refresh_from_db()
        self.assertEqual(debt.status, Debt.Status.ACTIVE)

        self.client.post(reverse("debts:debt_archive", args=[debt.pk]))
        debt.refresh_from_db()
        self.assertEqual(debt.status, Debt.Status.ARCHIVED)

    def test_status_change_other_user_debt_404(self):
        debt = self.make_debt(owner=self.bob, name="Empréstimo", total_amount=10000)
        resp = self.client.post(reverse("debts:debt_default", args=[debt.pk]))
        self.assertEqual(resp.status_code, 404)

    def test_delete_other_user_debt_404(self):
        debt = self.make_debt(owner=self.bob, name="Empréstimo", total_amount=10000)
        resp = self.client.post(reverse("debts:debt_delete", args=[debt.pk]))
        self.assertEqual(resp.status_code, 404)
