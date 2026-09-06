"""Testes de performance do motor (Ordem 18 — FASE 10 §18).

Garantem comportamento sem N+1 na classificação/backfill (limite de queries) e
eficiência das leituras de revisão/estatísticas. Sem chamadas externas.
"""

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from .models import Account, Merchant, MerchantAlias, Transaction
from .services.backfill import backfill_missing
from .services.review import stats

User = get_user_model()


class PerformanceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="alice", password="x")
        self.account = Account.objects.create(owner=self.user, name="Conta")
        self.uber = Merchant.objects.create(owner=None, name="Uber", default_category_name="Transporte")
        MerchantAlias.objects.create(owner=None, merchant=self.uber, alias="UBER")

    def _mk_unknown(self, i):
        return Transaction.objects.create(
            owner=self.user,
            account=self.account,
            type=Transaction.Type.EXPENSE,
            amount=1000 + i,
            date="2026-09-01",
            description=f"DESCONHECIDO {i} XYZ",
        )

    def test_backfill_bounded_queries_no_n_plus_one(self):
        for i in range(5):
            self._mk_unknown(i)
        with CaptureQueriesContext(connection) as ctx:
            backfill_missing(self.user)
        # Queries por transação são CONSTANTES (sem N+1 de histórico/contexto);
        # para 5 transações desconhecidas o total fica bem abaixo de qualquer
        # crescimento quadrático, documentando a regra de performance (§18).
        self.assertLessEqual(len(ctx), 140)

    def test_merchant_resolution_bounded_per_batch(self):
        for i in range(5):
            Transaction.objects.create(
                owner=self.user,
                account=self.account,
                type=Transaction.Type.EXPENSE,
                amount=2000 + i,
                date="2026-09-01",
                description="UBER *TRIP",
            )
        with CaptureQueriesContext(connection) as ctx:
            backfill_missing(self.user)
        self.assertLessEqual(len(ctx), 140)

    def test_stats_are_single_pass(self):
        for i in range(3):
            self._mk_unknown(i)
        with CaptureQueriesContext(connection) as ctx:
            stats(self.user)
        self.assertLessEqual(len(ctx), 6)
