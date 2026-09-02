"""Testes do app networth (patrimônio consolidado)."""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.debts.services.debts import create_debt
from apps.finance.services.accounts import create_account
from apps.goals.services.goals import create_goal

from . import services
from .models import NetWorthSnapshot

User = get_user_model()


class NetWorthTestBase(TestCase):
    def setUp(self):
        self.alice = User.objects.create_user(
            username="alice", password="senha123", first_name="Alice"
        )
        self.bob = User.objects.create_user(
            username="bob", password="senha123", first_name="Bob"
        )
        self.client.login(username="alice", password="senha123")


class ComposeTests(NetWorthTestBase):
    def test_net_worth_is_assets_minus_liabilities(self):
        create_account(user=self.alice, name="Conta", initial_balance=100000)
        create_debt(user=self.alice, name="Empréstimo", total_amount=20000)
        c = services.compose(self.alice)
        self.assertEqual(c["assets"], 100000)
        self.assertEqual(c["liabilities"], 20000)
        self.assertEqual(c["net_worth"], 80000)

    def test_reserves_count_goal_current_amount(self):
        create_account(user=self.alice, name="Conta", initial_balance=50000)
        create_goal(
            user=self.alice, name="Reserva", target_amount=100000, current_amount=40000
        )
        c = services.compose(self.alice)
        self.assertEqual(c["reserves"], 40000)

    def test_isolation_between_users(self):
        create_account(user=self.alice, name="Conta Alice", initial_balance=100000)
        create_account(user=self.bob, name="Conta Bob", initial_balance=999999)
        c = services.compose(self.alice)
        self.assertEqual(c["assets"], 100000)


class SnapshotTests(NetWorthTestBase):
    def test_register_snapshot_is_idempotent_per_day(self):
        create_account(user=self.alice, name="Conta", initial_balance=100000)
        services.register_snapshot(self.alice)
        services.register_snapshot(self.alice)
        self.assertEqual(
            NetWorthSnapshot.objects.for_user(self.alice).count(), 1
        )

    def test_latest_snapshot_and_history(self):
        create_account(user=self.alice, name="Conta", initial_balance=100000)
        services.register_snapshot(self.alice)
        latest = services.latest_snapshot(self.alice)
        self.assertIsNotNone(latest)
        self.assertEqual(latest["net_worth"], 100000)
        self.assertEqual(len(services.get_history(self.alice)), 1)


class WebTests(NetWorthTestBase):
    def test_index_renders_and_requires_auth(self):
        resp = self.client.get(reverse("networth:index"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Patrimônio líquido")
        self.client.logout()
        anon = self.client.get(reverse("networth:index"))
        self.assertEqual(anon.status_code, 302)

    def test_register_post_creates_snapshot(self):
        self.client.post(reverse("networth:register"))
        self.assertEqual(
            NetWorthSnapshot.objects.for_user(self.alice).count(), 1
        )
