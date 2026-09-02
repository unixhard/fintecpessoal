"""Testes do app budgets."""

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.finance.models import Category

from .models import Budget

User = get_user_model()


class BudgetTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="alice", password="x")
        self.category = Category.objects.create(
            owner=self.user, name="Alimentação", kind=Category.Kind.EXPENSE
        )

    def test_category_budget_requires_category(self):
        budget = Budget(
            owner=self.user, kind=Budget.Kind.CATEGORY,
            limit_amount=80000,
        )
        with self.assertRaises(ValidationError):
            budget.save()

    def test_global_budget_cannot_have_category(self):
        budget = Budget(
            owner=self.user, kind=Budget.Kind.GLOBAL,
            limit_amount=300000, category=self.category,
        )
        with self.assertRaises(ValidationError):
            budget.save()

    def test_budget_rejects_negative_limit(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Budget.objects.bulk_create(
                    [Budget(owner=self.user, kind=Budget.Kind.GLOBAL, limit_amount=-1)]
                )

    def test_budget_cannot_use_other_users_category(self):
        other = User.objects.create_user(username="bob", password="y")
        other_cat = Category.objects.create(owner=other, name="Outro")
        budget = Budget(
            owner=self.user, kind=Budget.Kind.CATEGORY,
            category=other_cat, limit_amount=100,
        )
        with self.assertRaises(ValidationError):
            budget.save()
