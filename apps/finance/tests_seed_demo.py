"""Testes do comando ``seed_demo`` — conta de demonstração completa.

Garante que o comando cria dados em todos os domínios (contas, cartão,
transações, faturas, metas, orçamentos, dívidas, recorrências) e é
idempotente (re-executar não duplica lançamentos).
"""

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase

from apps.budgets.models import Budget
from apps.cards.models import CreditCard, CreditCardInvoice, Installment
from apps.debts.models import Debt
from apps.finance.models import Account, Category, RecurringRule, Transaction
from apps.goals.models import Goal

User = get_user_model()


class SeedDemoCommandTests(TestCase):
    def test_creates_complete_demo_account(self):
        call_command("seed_demo", username="demo", email="demo@fintec.app")

        user = User.objects.get(username="demo")
        self.assertTrue(user.profile.onboarding_completed)
        self.assertGreater(Category.objects.for_user(user).count(), 0)
        self.assertGreater(Account.objects.for_user(user).count(), 0)
        self.assertGreater(Transaction.objects.for_user(user).count(), 0)
        self.assertGreater(CreditCard.objects.filter(owner=user).count(), 0)
        self.assertGreater(CreditCardInvoice.objects.filter(owner=user).count(), 0)
        self.assertGreater(Installment.objects.filter(owner=user).count(), 0)
        self.assertGreater(Goal.objects.for_user(user).count(), 0)
        self.assertGreater(Budget.objects.for_user(user).count(), 0)
        self.assertGreater(Debt.objects.for_user(user).count(), 0)
        self.assertGreater(RecurringRule.objects.for_user(user).count(), 0)

    def test_is_idempotent(self):
        call_command("seed_demo", username="demo", email="demo@fintec.app")
        tx_after_first = Transaction.objects.filter(
            owner=User.objects.get(username="demo")
        ).count()
        cat_after_first = Category.objects.filter(
            owner=User.objects.get(username="demo")
        ).count()

        call_command("seed_demo", username="demo", email="demo@fintec.app")

        user = User.objects.get(username="demo")
        self.assertEqual(
            Transaction.objects.filter(owner=user).count(), tx_after_first
        )
        self.assertEqual(
            Category.objects.filter(owner=user).count(), cat_after_first
        )
        self.assertEqual(Account.objects.for_user(user).count(), 2)

    def test_reset_deleta_dados_antigos_e_recria(self):
        call_command("seed_demo", username="demo", email="demo@fintec.app")
        user = User.objects.get(username="demo")
        tx_before = Transaction.objects.filter(owner=user).count()
        self.assertGreater(tx_before, 0)

        call_command("seed_demo", username="demo", email="demo@fintec.app", reset=True)

        user = User.objects.get(username="demo")
        self.assertGreater(
            Transaction.objects.filter(owner=user).count(), 0,
            "após --reset o usuário demo é recriado com novos dados",
        )