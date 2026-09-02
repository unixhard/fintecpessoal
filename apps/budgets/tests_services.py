"""Testes da camada de serviços de orçamentos (Budget).

Cobrem criação/atualização/exclusão com ownership validado, cálculo de
"realizado" a partir das despesas (sem duplicar contabilidade), classificação
de situação (healthy/attention/exceeded) e resumo agregado.
"""

from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.finance.models import Account, Category, Transaction
from apps.finance.services.base import require_owned
from apps.finance.services.errors import ForbiddenResourceError, InvalidAmountError, InvalidStateError

from .models import Budget
from .services.budgets import (
    budget_spent,
    create_budget,
    delete_budget,
    get_budget_progress,
    get_budget_summary,
    update_budget,
)

User = get_user_model()


class BudgetServiceBase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="alice", password="x")
        self.other = User.objects.create_user(username="bob", password="y")
        self.account = Account.objects.create(owner=self.user, name="Conta")
        self.food = Category.objects.create(
            owner=self.user, name="Alimentação", kind=Category.Kind.EXPENSE
        )
        self.sub_food = Category.objects.create(
            owner=self.user, name="Mercado", kind=Category.Kind.EXPENSE
        )
        self.food.subcategories.add(self.sub_food)


class BudgetCreateTests(BudgetServiceBase):
    def test_creates_global_budget(self):
        budget = create_budget(
            user=self.user, kind=Budget.Kind.GLOBAL, limit_amount=300000
        )
        self.assertEqual(budget.owner_id, self.user.id)
        self.assertEqual(budget.kind, Budget.Kind.GLOBAL)
        self.assertEqual(budget.limit_amount, 300000)
        self.assertTrue(budget.is_active)

    def test_creates_category_budget(self):
        budget = create_budget(
            user=self.user, kind=Budget.Kind.CATEGORY,
            limit_amount=80000, category=self.food,
        )
        self.assertEqual(budget.category_id, self.food.id)

    def test_category_budget_rejects_other_users_category(self):
        other_cat = Category.objects.create(
            owner=self.other, name="Outro", kind=Category.Kind.EXPENSE
        )
        with self.assertRaises(ForbiddenResourceError):
            create_budget(
                user=self.user, kind=Budget.Kind.CATEGORY,
                limit_amount=100, category=other_cat,
            )

    def test_rejects_negative_limit(self):
        with self.assertRaises(InvalidAmountError):
            create_budget(
                user=self.user, kind=Budget.Kind.GLOBAL, limit_amount=-1
            )

    def test_rejects_non_integer_limit(self):
        with self.assertRaises(InvalidAmountError):
            create_budget(
                user=self.user, kind=Budget.Kind.GLOBAL, limit_amount=100.5
            )


class BudgetUpdateDeleteTests(BudgetServiceBase):
    def test_update_rejects_other_users_budget(self):
        budget = create_budget(
            user=self.user, kind=Budget.Kind.GLOBAL, limit_amount=100
        )
        with self.assertRaises(ForbiddenResourceError):
            update_budget(user=self.other, budget=budget, limit_amount=200)

    def test_update_changes_limit(self):
        budget = create_budget(
            user=self.user, kind=Budget.Kind.GLOBAL, limit_amount=100
        )
        updated = update_budget(user=self.user, budget=budget, limit_amount=250)
        self.assertEqual(updated.limit_amount, 250)

    def test_delete_other_users_budget_rejected(self):
        budget = create_budget(
            user=self.user, kind=Budget.Kind.GLOBAL, limit_amount=100
        )
        with self.assertRaises(ForbiddenResourceError):
            delete_budget(user=self.other, budget=budget)

    def test_delete_removes_budget(self):
        budget = create_budget(
            user=self.user, kind=Budget.Kind.GLOBAL, limit_amount=100
        )
        delete_budget(user=self.user, budget=budget)
        with self.assertRaises(ForbiddenResourceError):
            get_for_id = require_owned(
                Budget.objects, self.user, model_label="Orçamento",
                object_id=budget.pk,
            )

    def test_get_budget_other_user_rejected(self):
        budget = create_budget(
            user=self.user, kind=Budget.Kind.GLOBAL, limit_amount=100
        )
        with self.assertRaises(ForbiddenResourceError):
            from .services.budgets import get_budget

            get_budget(user=self.other, budget_id=budget.pk)


class BudgetSpentTests(BudgetServiceBase):
    def setUp(self):
        super().setUp()
        self.budget = create_budget(
            user=self.user, kind=Budget.Kind.CATEGORY,
            limit_amount=80000, category=self.food,
        )

    def _expense(self, category, amount, day):
        return Transaction.objects.create(
            owner=self.user,
            account=self.account,
            category=category,
            type=Transaction.Type.EXPENSE,
            amount=amount,
            date=date(2026, 9, day),
            description="Despesa",
        )

    def test_spent_includes_category_and_subcategories(self):
        self._expense(self.food, 10000, 5)
        self._expense(self.sub_food, 5000, 6)
        ref = date(2026, 9, 15)
        self.assertEqual(budget_spent(user=self.user, budget=self.budget, ref_date=ref), 15000)

    def test_spent_excludes_other_categories(self):
        other_cat = Category.objects.create(
            owner=self.user, name="Lazer", kind=Category.Kind.EXPENSE
        )
        self._expense(self.food, 10000, 5)
        self._expense(other_cat, 9000, 6)
        ref = date(2026, 9, 15)
        self.assertEqual(budget_spent(user=self.user, budget=self.budget, ref_date=ref), 10000)

    def test_spent_ignores_income(self):
        Transaction.objects.create(
            owner=self.user, account=self.account, category=self.food,
            type=Transaction.Type.INCOME, amount=50000,
            date=date(2026, 9, 1), description="Receita",
        )
        ref = date(2026, 9, 15)
        self.assertEqual(budget_spent(user=self.user, budget=self.budget, ref_date=ref), 0)

    def test_spent_excludes_other_users_transactions(self):
        other_cat = Category.objects.create(
            owner=self.other, name="Comida", kind=Category.Kind.EXPENSE
        )
        other_account = Account.objects.create(owner=self.other, name="Conta B")
        Transaction.objects.create(
            owner=self.other, account=other_account, category=other_cat,
            type=Transaction.Type.EXPENSE, amount=99999,
            date=date(2026, 9, 10), description="Despesa do Bob",
        )
        ref = date(2026, 9, 15)
        self.assertEqual(budget_spent(user=self.user, budget=self.budget, ref_date=ref), 0)


class BudgetProgressTests(BudgetServiceBase):
    def test_healthy_when_below_attention(self):
        budget = create_budget(
            user=self.user, kind=Budget.Kind.GLOBAL, limit_amount=10000,
        )
        Transaction.objects.create(
            owner=self.user, account=self.account,
            type=Transaction.Type.EXPENSE, amount=1000,
            date=date(2026, 9, 5), description="D",
        )
        p = get_budget_progress(
            user=self.user, budget=budget, ref_date=date(2026, 9, 15)
        )
        self.assertEqual(p["status"], "healthy")
        self.assertEqual(p["percent"], 10)
        self.assertEqual(p["remaining"], 9000)

    def test_attention_at_threshold(self):
        budget = create_budget(
            user=self.user, kind=Budget.Kind.GLOBAL, limit_amount=1000,
        )
        Transaction.objects.create(
            owner=self.user, account=self.account,
            type=Transaction.Type.EXPENSE, amount=800,
            date=date(2026, 9, 5), description="D",
        )
        p = get_budget_progress(
            user=self.user, budget=budget, ref_date=date(2026, 9, 15)
        )
        self.assertEqual(p["status"], "attention")

    def test_exceeded_when_over_limit(self):
        budget = create_budget(
            user=self.user, kind=Budget.Kind.GLOBAL, limit_amount=1000,
        )
        Transaction.objects.create(
            owner=self.user, account=self.account,
            type=Transaction.Type.EXPENSE, amount=1200,
            date=date(2026, 9, 5), description="D",
        )
        p = get_budget_progress(
            user=self.user, budget=budget, ref_date=date(2026, 9, 15)
        )
        self.assertEqual(p["status"], "exceeded")
        self.assertEqual(p["remaining"], 0)


class BudgetSummaryTests(BudgetServiceBase):
    def test_empty_summary(self):
        s = get_budget_summary(user=self.user)
        self.assertEqual(s["total_planned"], 0)
        self.assertEqual(s["budgets"], [])
        self.assertEqual(s["exceeded"], [])
        self.assertEqual(s["attention"], [])

    def test_summary_totals_and_classifications(self):
        ok = create_budget(
            user=self.user, kind=Budget.Kind.GLOBAL, limit_amount=10000,
        )
        over = create_budget(
            user=self.user, kind=Budget.Kind.GLOBAL, limit_amount=1000,
        )
        Transaction.objects.create(
            owner=self.user, account=self.account,
            type=Transaction.Type.EXPENSE, amount=1200,
            date=date(2026, 9, 5), description="D",
        )
        ref = date(2026, 9, 15)
        s = get_budget_summary(user=self.user, ref_date=ref)
        self.assertEqual(s["total_planned"], 11000)
        # Cada orçamento global conta a mesma despesa (escopo global sobreposto).
        self.assertEqual(s["total_realized"], 2400)
        self.assertEqual(len(s["exceeded"]), 1)
        self.assertEqual(s["exceeded"][0]["budget"].pk, over.pk)
