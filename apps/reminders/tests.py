"""Testes do app reminders (agenda de vencimentos)."""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.debts.services.debts import create_debt

from . import services

User = get_user_model()


class RemindersTestBase(TestCase):
    def setUp(self):
        self.alice = User.objects.create_user(
            username="alice", password="senha123", first_name="Alice"
        )
        self.client.login(username="alice", password="senha123")


class TimelineTests(RemindersTestBase):
    def test_timeline_includes_upcoming_debt(self):
        end_date = timezone.localdate() + timedelta(days=5)
        create_debt(
            user=self.alice, name="Fatura de energia",
            total_amount=5000, end_date=end_date,
        )
        tl = services.timeline(self.alice, days=30)
        self.assertTrue(any("energia" in it["label"] for it in tl["items"]))
        self.assertEqual(tl["total_amount"], 5000)

    def test_no_items_returns_empty(self):
        tl = services.timeline(self.alice, days=7)
        self.assertEqual(tl["items"], [])


class WebTests(RemindersTestBase):
    def test_index_renders_with_horizon(self):
        resp = self.client.get(reverse("reminders:index"), {"days": 7})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Agenda de contas a pagar/receber")

    def test_invalid_horizon_falls_back(self):
        resp = self.client.get(reverse("reminders:index"), {"days": 999})
        self.assertEqual(resp.status_code, 200)

    def test_requires_auth(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse("reminders:index")).status_code, 302)
