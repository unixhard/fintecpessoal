"""Testes do app reports (relatórios + exportação)."""

from django.contrib.auth import get_user_model
from django.urls import reverse
from django.test import TestCase

from apps.finance.services.accounts import create_account
from apps.finance.services.categories import create_category
from apps.finance.services.transactions import record_expense, record_income

User = get_user_model()


class ReportsTestBase(TestCase):
    def setUp(self):
        self.alice = User.objects.create_user(
            username="alice", password="senha123", first_name="Alice"
        )
        self.client.login(username="alice", password="senha123")
        self.account = create_account(
            user=self.alice, name="Conta", initial_balance=0
        )

    def make_data(self):
        from django.utils import timezone

        food = create_category(user=self.alice, name="Alimentação")
        record_income(
            user=self.alice, account=self.account, amount=100000,
            date=timezone.localdate(),
        )
        record_expense(
            user=self.alice, account=self.account, amount=30000,
            category=food, date=timezone.localdate(),
        )


class WebTests(ReportsTestBase):
    def test_index_renders_period(self):
        resp = self.client.get(reverse("reports:index"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Relatórios")

    def test_index_accepts_invalid_period_fallback(self):
        resp = self.client.get(reverse("reports:index"), {"period": "xyz"})
        self.assertEqual(resp.status_code, 200)

    def test_csv_export_returns_csv(self):
        self.make_data()
        resp = self.client.get(reverse("reports:csv"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "text/csv; charset=utf-8")
        body = resp.content.decode("utf-8")
        self.assertIn("Data", body)
        self.assertIn("Receita", body)

    def test_printable_renders(self):
        resp = self.client.get(reverse("reports:print"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Relatório financeiro")

    def test_requires_auth(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse("reports:index")).status_code, 302)
