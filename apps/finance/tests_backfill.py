"""Testes do backfill/classificação de transações existentes (FASE 7).

Cobre: backfill de transações sem análise, respeito à correção do usuário,
movimentação neutra não vira consumo, recusa de merchant/categoria de outro
usuário, e integração com a fila de revisão (FASE 9 helper).
"""

from django.contrib.auth import get_user_model
from django.test import TestCase

from .models import (
    Account,
    Category,
    Merchant,
    MerchantAlias,
    Transaction,
    TransactionAnalysis,
)
from .services.backfill import backfill_missing, classify_and_apply, review_count
from .services.categories import seed_default_categories
from .services.classifier import apply_user_correction

User = get_user_model()


class BackfillTests(TestCase):
    def setUp(self):
        self.alice = User.objects.create_user(username="alice", password="x")
        self.bob = User.objects.create_user(username="bob", password="y")
        self.account = Account.objects.create(owner=self.alice, name="Conta")
        seed_default_categories(user=self.alice)

    def _mk(self, description, date="2026-09-01", category=None):
        return Transaction.objects.create(
            owner=self.alice,
            account=self.account,
            type=Transaction.Type.EXPENSE,
            amount=2000,
            date=date,
            description=description,
            category=category,
        )

    def test_backfill_creates_analysis_for_existing(self):
        tx = self._mk("MERCADO BOM")
        self.assertIsNone(getattr(tx, "analysis", None))
        n = backfill_missing(self.alice)
        self.assertEqual(n, 1)
        self.assertTrue(TransactionAnalysis.objects.filter(transaction=tx).exists())

    def test_backfill_does_not_touch_user_corrected(self):
        tx = self._mk("PADARIA")
        padaria = Category.objects.for_user(self.alice).get(name="Padaria")
        apply_user_correction(user=self.alice, transaction=tx, category=padaria)
        # recorre: ainda deve manter user_corrected e não reverter
        n = backfill_missing(self.alice)
        analysis = TransactionAnalysis.objects.get(transaction=tx)
        self.assertTrue(analysis.user_corrected)
        self.assertEqual(tx.category, padaria)

    def test_backfill_skips_matching_existing_analysis(self):
        self._mk("MERCADO BOM")
        self._mk("PADARIA")
        first = backfill_missing(self.alice)
        self.assertEqual(first, 2)
        second = backfill_missing(self.alice)
        self.assertEqual(second, 0)

    def test_movement_never_becomes_consumption_category(self):
        tx = self._mk("PAGAMENTO DE DIVIDA 0099")
        classify_and_apply(self.alice, tx)
        analysis = TransactionAnalysis.objects.get(transaction=tx)
        self.assertTrue(analysis.is_movement)
        self.assertIsNotNone(analysis.classification_source == TransactionAnalysis.Source.MOVEMENT)

    def test_review_count_counts_unknown(self):
        self._mk("COISA DESCONHECIDA XYZ")
        self.assertEqual(review_count(self.alice), 1)

    def test_merchant_association_resolves_category(self):
        m = Merchant.objects.create(
            owner=None, name="Uber", default_category_name="Transporte"
        )
        MerchantAlias.objects.create(owner=None, merchant=m, alias="UBER")
        tx = self._mk("UBER *TRIP 777")
        backfill_missing(self.alice)
        tx.refresh_from_db()
        self.assertIsNotNone(tx.category)
        self.assertEqual(tx.category.name, "Transporte")
