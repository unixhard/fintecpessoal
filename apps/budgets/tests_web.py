"""Testes web do módulo de orçamentos (views, ownership e navegação).

Cobrem o fluxo: listar/criar/editar/alternar/excluir orçamento e isolamento
multiusuário (usuário B não acessa orçamento de A) e redirecionamento de
anônimos — sempre via services.
"""

from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils.timezone import localdate

from apps.finance.models import Account, Category, Transaction

from .models import Budget
from .services.budgets import create_budget

User = get_user_model()


class BudgetWebTestBase(TestCase):
    def setUp(self):
        self.alice = User.objects.create_user(
            username="alice", password="senha123", first_name="Alice"
        )
        self.bob = User.objects.create_user(
            username="bob", password="senha123", first_name="Bob"
        )
        self.account_a = Account.objects.create(
            owner=self.alice, name="Conta Alice", initial_balance=100000
        )
        self.category_a = Category.objects.create(
            owner=self.alice, name="Alimentação", kind=Category.Kind.EXPENSE
        )
        self.login_as(self.alice)

    def login_as(self, user):
        self.client.login(username=user.username, password="senha123")

    def make_budget(self, owner=None, **kwargs):
        owner = owner or self.alice
        defaults = {
            "kind": Budget.Kind.GLOBAL,
            "limit_amount": 300000,
        }
        defaults.update(kwargs)
        return create_budget(user=owner, **defaults)


class BudgetListViewTests(BudgetWebTestBase):
    def test_anonymous_redirected_to_login(self):
        self.client.logout()
        resp = self.client.get(reverse("budgets:budget_list"))
        self.assertEqual(resp.status_code, 302)

    def test_authenticated_lists_only_own_budgets(self):
        self.make_budget(owner=self.alice, kind=Budget.Kind.GLOBAL, limit_amount=100000)
        self.make_budget(owner=self.bob, kind=Budget.Kind.GLOBAL, limit_amount=999000)
        resp = self.client.get(reverse("budgets:budget_list"))
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode()
        self.assertNotIn("999000", content)


class BudgetCreateEditTests(BudgetWebTestBase):
    def _post_budget(self, url, data):
        return self.client.post(url, data, follow=True)

    def test_create_global_budget(self):
        resp = self._post_budget(
            reverse("budgets:budget_create"),
            {
                "kind": Budget.Kind.GLOBAL,
                "category": "",
                "period": Budget.Period.MONTHLY,
                "limit_amount": "3000",
                "start_date": "",
                "end_date": "",
                "is_active": "on",
            },
        )
        self.assertEqual(resp.status_code, 200)
        budget = Budget.objects.get(owner=self.alice, kind=Budget.Kind.GLOBAL)
        self.assertEqual(budget.limit_amount, 300000)

    def test_create_category_budget(self):
        resp = self._post_budget(
            reverse("budgets:budget_create"),
            {
                "kind": Budget.Kind.CATEGORY,
                "category": self.category_a.pk,
                "period": Budget.Period.MONTHLY,
                "limit_amount": "800",
            },
        )
        self.assertEqual(resp.status_code, 200)
        budget = Budget.objects.get(
            owner=self.alice, kind=Budget.Kind.CATEGORY, category=self.category_a
        )
        self.assertEqual(budget.limit_amount, 80000)

    def test_category_budget_without_category_invalid(self):
        resp = self.client.post(
            reverse("budgets:budget_create"),
            {
                "kind": Budget.Kind.CATEGORY,
                "category": "",
                "period": Budget.Period.MONTHLY,
                "limit_amount": "800",
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Budget.objects.filter(owner=self.alice).count(), 0)

    def test_edit_budget_updates_limit(self):
        budget = self.make_budget(owner=self.alice, kind=Budget.Kind.GLOBAL, limit_amount=100000)
        self.client.post(
            reverse("budgets:budget_edit", args=[budget.pk]),
            {
                "kind": Budget.Kind.GLOBAL,
                "category": "",
                "period": Budget.Period.MONTHLY,
                "limit_amount": "2500",
            },
        )
        budget.refresh_from_db()
        self.assertEqual(budget.limit_amount, 250000)

    def test_edit_other_user_budget_returns_404(self):
        budget = self.make_budget(owner=self.bob, kind=Budget.Kind.GLOBAL, limit_amount=100000)
        resp = self.client.post(
            reverse("budgets:budget_edit", args=[budget.pk]),
            {
                "kind": Budget.Kind.GLOBAL,
                "category": "",
                "period": Budget.Period.MONTHLY,
                "limit_amount": "1",
            },
        )
        self.assertEqual(resp.status_code, 404)

    def test_detail_other_user_budget_returns_404(self):
        budget = self.make_budget(owner=self.bob, kind=Budget.Kind.GLOBAL, limit_amount=100000)
        resp = self.client.get(reverse("budgets:budget_detail", args=[budget.pk]))
        self.assertEqual(resp.status_code, 404)


class BudgetToggleDeleteTests(BudgetWebTestBase):
    def test_toggle_inactivates_and_reactivates(self):
        budget = self.make_budget(owner=self.alice, kind=Budget.Kind.GLOBAL, limit_amount=100000)
        self.client.post(reverse("budgets:budget_toggle", args=[budget.pk]))
        budget.refresh_from_db()
        self.assertFalse(budget.is_active)

        self.client.post(reverse("budgets:budget_toggle", args=[budget.pk]))
        budget.refresh_from_db()
        self.assertTrue(budget.is_active)

    def test_toggle_other_user_budget_404(self):
        budget = self.make_budget(owner=self.bob, kind=Budget.Kind.GLOBAL, limit_amount=100000)
        resp = self.client.post(reverse("budgets:budget_toggle", args=[budget.pk]))
        self.assertEqual(resp.status_code, 404)

    def test_delete_other_user_budget_404(self):
        budget = self.make_budget(owner=self.bob, kind=Budget.Kind.GLOBAL, limit_amount=100000)
        resp = self.client.post(reverse("budgets:budget_delete", args=[budget.pk]))
        self.assertEqual(resp.status_code, 404)

    def test_detail_shows_over_limit_as_exceeded(self):
        budget = self.make_budget(owner=self.alice, kind=Budget.Kind.GLOBAL, limit_amount=100000)
        Transaction.objects.create(
            owner=self.alice, account=self.account_a,
            category=self.category_a, type=Transaction.Type.EXPENSE,
            amount=120000, date=localdate(), description="D",
        )
        resp = self.client.get(reverse("budgets:budget_detail", args=[budget.pk]))
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode()
        self.assertIn("120%", content)
        self.assertIn("ultrapassou", content)
