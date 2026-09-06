"""Testes da camada de estabelecimentos (Ordem 18 — FASE 4).

Cobre: normalização (preservação da original), alias, matching, Merchant
global/pessoal, isolamento entre usuários, estabelecimento desconhecido/ambíguo,
prioridade de regras (pessoal > global), aprendizado por correção, duplicidade
e integração importação -> staging -> identificação.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase

from .models import Account, Merchant, MerchantAlias, Transaction
from .services.merchants import (
    learn_alias,
    normalize_description,
    resolve_merchant,
)

User = get_user_model()


class MerchantModelTests(TestCase):
    def setUp(self):
        self.alice = User.objects.create_user(username="alice", password="x")
        self.bob = User.objects.create_user(username="bob", password="y")

    def test_global_merchant_visible_to_every_user(self):
        m = Merchant.objects.create(owner=None, name="Uber")
        self.assertIn(m, list(Merchant.objects.for_user(self.alice)))
        self.assertIn(m, list(Merchant.objects.for_user(self.bob)))

    def test_personal_merchant_isolated_between_users(self):
        ma = Merchant.objects.create(owner=self.alice, name="Restaurante Favorito")
        Merchant.objects.create(owner=self.bob, name="Restaurante Favorito")
        self.assertEqual(list(Merchant.objects.owned(self.alice)), [ma])
        self.assertEqual(
            list(Merchant.objects.for_user(self.alice)),
            [ma],
        )
        self.assertEqual(
            list(Merchant.objects.for_user(self.bob)),
            list(Merchant.objects.owned(self.bob)),
        )

    def test_unique_per_owner_allows_global_and_personal_same_name(self):
        Merchant.objects.create(owner=None, name="Uber")
        Merchant.objects.create(owner=self.alice, name="Uber")  # não conflita
        self.assertEqual(Merchant.objects.filter(name="Uber").count(), 2)

    def test_alias_unique_per_owner(self):
        m = Merchant.objects.create(owner=None, name="Uber")
        MerchantAlias.objects.create(merchant=m, owner=None, alias="UBER")
        MerchantAlias.objects.create(merchant=m, owner=self.alice, alias="UBER")
        self.assertEqual(
            MerchantAlias.objects.filter(alias="UBER", owner__isnull=True).count(), 1
        )
        self.assertEqual(
            MerchantAlias.objects.filter(alias="UBER", owner=self.alice).count(), 1
        )

    def test_personal_alias_via_learning_gets_user_source(self):
        m = Merchant.objects.create(owner=self.alice, name="iFood")
        a = learn_alias(user=self.alice, alias="IFD", merchant=m)
        self.assertEqual(a.source, MerchantAlias.Source.USER)
        self.assertEqual(a.owner, self.alice)


class NormalizeTests(TestCase):
    def test_normalize_preserves_original_semantics(self):
        raw = "UBER *TRIP 839201 SAO PAULO SP"
        norm = normalize_description(raw)
        self.assertIn("UBER", norm)
        self.assertNotIn("839201", norm)
        self.assertTrue(norm == norm.upper())

    def test_original_never_used_as_normalized(self):
        # O serviço de normalização nunca deveria retornar o cru como norm.
        raw = "ifood.   com  - 1234"
        norm = normalize_description(raw)
        self.assertNotIn(".", norm)

    def test_distinct_merchants_not_merged(self):
        # Conservador: não funde estabelecimentos distintos num só nome.
        a = normalize_description("LOJAS RENNER")
        b = normalize_description("LOJAS AMERICANAS")
        self.assertNotEqual(a, b)


class ResolveTests(TestCase):
    def setUp(self):
        self.alice = User.objects.create_user(username="alice", password="x")
        self.bob = User.objects.create_user(username="bob", password="y")

    def test_unknown_merchant(self):
        res = resolve_merchant(self.alice, "PADARIA DO ZE 123")
        self.assertFalse(res.matched)
        self.assertIsNone(res.merchant)
        self.assertEqual(res.confidence, 0.0)

    def test_matches_global_alias(self):
        m = Merchant.objects.create(owner=None, name="Uber")
        MerchantAlias.objects.create(owner=None, merchant=m, alias="UBER")
        res = resolve_merchant(self.alice, "UBER *TRIP 839201")
        self.assertTrue(res.matched)
        self.assertEqual(res.merchant, m)
        self.assertEqual(res.method, "catalog_alias")

    def test_matches_global_merchant_by_name(self):
        m = Merchant.objects.create(owner=None, name="iFood")
        res = resolve_merchant(self.alice, "IFOOD *PEDIDO 55")
        self.assertTrue(res.matched)
        self.assertEqual(res.merchant, m)
        self.assertEqual(res.method, "merchant_name")

    def test_personal_alias_takes_precedence_over_global(self):
        global_m = Merchant.objects.create(owner=None, name="Uber")
        MerchantAlias.objects.create(owner=None, merchant=global_m, alias="UBER")
        personal_m = Merchant.objects.create(owner=self.alice, name="Meu Uber Pessoal")
        learn_alias(user=self.alice, alias="UBER", merchant=personal_m)
        res = resolve_merchant(self.alice, "UBER *TRIP 1")
        self.assertEqual(res.merchant, personal_m)
        self.assertEqual(res.method, "user_alias")
        self.assertGreaterEqual(res.confidence, 0.95)

    def test_isolation_personal_alias_not_visible_to_other_user(self):
        m = Merchant.objects.create(owner=None, name="Uber")
        MerchantAlias.objects.create(owner=None, merchant=m, alias="UBER")
        pm = Merchant.objects.create(owner=self.alice, name="Uber Alice")
        learn_alias(user=self.alice, alias="UBER", merchant=pm)
        # Bob não enxerga o alias pessoal da Alice -> cai no alias global.
        res = resolve_merchant(self.bob, "UBER *TRIP 1")
        self.assertEqual(res.merchant, m)
        self.assertEqual(res.method, "catalog_alias")

    def test_ambiguous_merchants_selects_most_specific(self):
        # Dois mercados possuem alias 'UBER'; um também possui 'UBER TRIP'.
        m1 = Merchant.objects.create(owner=None, name="Uber")
        m2 = Merchant.objects.create(owner=None, name="Uber Eats")
        MerchantAlias.objects.create(owner=None, merchant=m1, alias="UBER", confidence="0.98")
        MerchantAlias.objects.create(owner=None, merchant=m2, alias="UBER EATS", confidence="0.95")
        res = resolve_merchant(self.alice, "UBER EATS")
        # 'UBER EATS' é o alias mais específico (subconjunto dos dois, mas
        # 'UBER EATS' == descrição -> escolhe m2).
        self.assertEqual(res.merchant, m2)

    def test_confidence_objective_rule_exact(self):
        m = Merchant.objects.create(owner=None, name="Uber")
        MerchantAlias.objects.create(owner=None, merchant=m, alias="UBER")
        res = resolve_merchant(self.alice, "UBER")
        self.assertEqual(res.confidence, 1.0)

    def test_matched_alias_use_count(self):
        m = Merchant.objects.create(owner=None, name="Uber")
        alias = MerchantAlias.objects.create(owner=None, merchant=m, alias="UBER")
        resolve_merchant(self.alice, "UBER")
        alias.refresh_from_db()
        # resolve_merchant não incrementa por padrão (only via record_use);
        # garantimos que o contador permanece 0 aqui e não quebra.
        self.assertEqual(alias.use_count, 0)


class LearningTests(TestCase):
    def setUp(self):
        self.alice = User.objects.create_user(username="alice", password="x")

    def test_learn_alias_reused_on_next_resolution(self):
        m = Merchant.objects.create(owner=self.alice, name="Mercado")
        learn_alias(user=self.alice, alias="MERCADO BOM", merchant=m)
        res = resolve_merchant(self.alice, "MERCADO BOM - PEDIDO 42")
        self.assertTrue(res.matched)
        self.assertEqual(res.merchant, m)
        self.assertEqual(res.method, "user_alias")

    def test_learn_alias_rejects_other_user_merchant(self):
        bob = User.objects.create_user(username="bob", password="y")
        m = Merchant.objects.create(owner=bob, name="Bob Shop")
        with self.assertRaises(ValueError):
            learn_alias(user=self.alice, alias="BOB", merchant=m)


class ImportIntegrationTests(TestCase):
    def setUp(self):
        self.alice = User.objects.create_user(username="alice", password="x")
        self.account = Account.objects.create(owner=self.alice, name="Conta")

    def _ingest_csv(self, content: bytes):
        from apps.imports.services.importer import ingest

        return ingest(
            user=self.alice,
            file_type="csv",
            file_name="mov.csv",
            content=content,
            default_account=self.account,
        )

    def test_import_staging_identifies_merchant(self):
        m = Merchant.objects.create(owner=None, name="Uber")
        MerchantAlias.objects.create(owner=None, merchant=m, alias="UBER")
        from apps.imports.models import StagedTransaction

        batch = self._ingest_csv(
            b"data,descricao,valor\n"
            b"01/09/2026,UBER *TRIP 1111,-25,90\n"
        )
        staged = StagedTransaction.objects.get(batch=batch)
        self.assertEqual(staged.merchant, m)
        self.assertEqual(staged.normalized_description, "UBER")
        self.assertEqual(staged.metadata.get("merchant_method"), "catalog_alias")

    def test_confirm_creates_transaction_with_merchant(self):
        m = Merchant.objects.create(owner=None, name="Uber")
        MerchantAlias.objects.create(owner=None, merchant=m, alias="UBER")
        from apps.imports.services.commit import commit_batch

        batch = self._ingest_csv(
            b"data,descricao,valor\n"
            b"01/09/2026,UBER *TRIP 2222,-15,00\n"
        )
        result = commit_batch(user=self.alice, batch=batch, account=self.account)
        self.assertEqual(result.imported, 1)
        tx = Transaction.objects.get(owner=self.alice)
        self.assertEqual(tx.merchant, m)
        self.assertEqual(tx.normalized_description, "UBER")

    def test_original_description_preserved_in_transaction(self):
        # Import CSV: description é a normalizada do parser; a original deve
        # estar preservada na descrição usada (não destruída pelo normalizador).
        m = Merchant.objects.create(owner=None, name="Uber")
        MerchantAlias.objects.create(owner=None, merchant=m, alias="UBER")
        from apps.imports.services.commit import commit_batch
        from apps.imports.models import StagedTransaction

        batch = self._ingest_csv(
            b"data,descricao,valor\n"
            b"01/09/2026,UBER *TRIP 3333,-18,00\n"
        )
        staged = StagedTransaction.objects.get(batch=batch)
        self.assertEqual(staged.original_description, "UBER *TRIP 3333")
        commit_batch(user=self.alice, batch=batch, account=self.account)
        tx = Transaction.objects.get(owner=self.alice)
        self.assertEqual(tx.description, "UBER *TRIP 3333")
