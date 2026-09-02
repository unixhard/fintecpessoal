"""Testes do app debts."""

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase

from .models import Debt

User = get_user_model()


class DebtTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="alice", password="x")

    def test_debt_rejects_negative_total(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Debt.objects.bulk_create(
                    [Debt(owner=self.user, name="Empréstimo", total_amount=-1)]
                )

    def test_debt_paid_cannot_exceed_total(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Debt.objects.bulk_create(
                    [
                        Debt(
                            owner=self.user, name="Dívida",
                            total_amount=1000, paid_amount=2000,
                        )
                    ]
                )

    def test_remaining_amount(self):
        debt = Debt.objects.create(
            owner=self.user, name="Financiamento",
            total_amount=30000, paid_amount=12000,
        )
        self.assertEqual(debt.remaining_amount, 18000)
