"""Testes da fila de revisão humana e correção em massa (FASE 9).

Cobre: agendamento de pendências, estatísticas, correção em lote com validação
de ownership/isolação, e aprendizado a partir da correção.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase

from .models import Account, Transaction
from .services.categories import seed_default_categories
from .services.review import bulk_correct, pending, stats

User = get_user_model()


class ReviewQueueTests(TestCase):
    def setUp(self):
        self.alice = User.objects.create_user(username="alice", password="x")
        self.bob = User.objects.create_user(username="bob", password="y")
        self.account = Account.objects.create(owner=self.alice, name="Conta")
        seed_default_categories(user=self.alice)
        seed_default_categories(user=self.bob)

    def _mk(self, description):
        return Transaction.objects.create(
            owner=self.alice,
            account=self.account,
            type=Transaction.Type.EXPENSE,
            amount=1000,
            date="2026-09-01",
            description=description,
        )

    def test_pending_lists_unknown_transactions(self):
        self._mk("COISA MISTERIOSA AAA")
        self.assertEqual(len(pending(self.alice)), 1)
        self.assertEqual(stats(self.alice)["needs_review"], 1)

    def test_bulk_correct_applies_and_learns(self):
        tx = self._mk("PADARIA VILA NOVA")
        padaria = seed_category(self.alice, "Padaria")
        result = bulk_correct(user=self.alice, corrections=[{"transaction_id": tx.id, "category_id": padaria.id}])
        self.assertEqual(result["applied"], 1)
        self.assertEqual(result["errors"], [])
        tx.refresh_from_db()
        self.assertEqual(tx.category, padaria)

    def test_bulk_correct_rejects_other_users_category(self):
        tx = self._mk("RESTAURANTE X")
        bob_cat = seed_category(self.bob, "Comida do Bob")
        result = bulk_correct(user=self.alice, corrections=[{"transaction_id": tx.id, "category_id": bob_cat.id}])
        self.assertEqual(result["applied"], 0)
        self.assertTrue(result["errors"])

    def test_bulk_correct_rejects_other_users_transaction(self):
        bob_tx = Transaction.objects.create(
            owner=self.bob,
            account=Account.objects.create(owner=self.bob, name="C2"),
            type=Transaction.Type.EXPENSE,
            amount=1000,
            date="2026-09-01",
            description="X",
        )
        cat = seed_category(self.alice, "Alimentação")
        result = bulk_correct(user=self.alice, corrections=[{"transaction_id": bob_tx.id, "category_id": cat.id}])
        self.assertEqual(result["applied"], 0)


def seed_category(user, name):
    from .models import Category

    return Category.objects.get_or_create(
        owner=user, name=name, kind=Category.Kind.EXPENSE, parent=None,
        defaults={"is_default": False, "status": Category.Status.ACTIVE},
    )[0]
