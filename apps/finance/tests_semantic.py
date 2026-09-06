"""Testes do classificador semântico opcional (FASE 11).

Regras verificadas:
  - Desligado por padrão -> usa o determinístico.
  - Provider mock resolve apenas ambiguidade; nunca chamado por transação
    já resolvida por fontes determinísticas de valor.
  - Nunca sobrescreve correção do usuário / regra / merchant / movimento.
  - Isolamento multiusuário.
  - Falha do provider cai de volta ao determinístico sem quebrar.
"""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from .models import Account, Category, Merchant, MerchantAlias, Transaction, TransactionAnalysis
from .services.classifier import apply_user_correction
from .services.semantic import apply_semantic, semantic_classify, is_enabled

User = get_user_model()


class MockProvider:
    """Provider fake — nenhuma chamada externa real."""

    def __init__(self, pins=None):
        self.pins = pins or {}
        self.calls = []

    def classify_text(self, description, direction):
        self.calls.append(description)
        return self.pins.get(description)


def _enabled():
    return override_settings(FINANCE_SEMANTIC_ENABLED=True, FINANCE_SEMANTIC_PROVIDER="")


class SemanticClassifierTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="ana", password="x")
        self.other = User.objects.create_user(username="bob", password="y")
        self.account = Account.objects.create(owner=self.user, name="Conta")
        self.food = Category.objects.create(owner=self.user, name="Alimentação", kind=Category.Kind.EXPENSE)
        self.padaria = Category.objects.create(owner=self.user, name="Padaria", kind=Category.Kind.EXPENSE)
        self.uber = Merchant.objects.create(owner=None, name="Uber", default_category_name="Transporte")
        MerchantAlias.objects.create(owner=None, merchant=self.uber, alias="UBER")

    def _tx(self, desc, type_=Transaction.Type.EXPENSE, account=None):
        return Transaction.objects.create(
            owner=self.user,
            account=account or self.account,
            type=type_,
            amount=50,
            date="2026-09-01",
            description=desc,
        )

    # --- Desligado por padrão ------------------------------------------ #
    def test_disabled_by_default(self):
        from django.conf import settings
        self.assertFalse(getattr(settings, "FINANCE_SEMANTIC_ENABLED", False))
        self.assertFalse(is_enabled())

    def test_disabled_uses_deterministic(self):
        # Com o semântico desligado, o determinístico decide. Na FASE 1,
        # "PAGAMENTO DE FATURA" vira "Transferência para cartão" (NATURE),
        # não consumo comum — e o provider NÃO deve ser chamado.
        financas = Category.objects.create(owner=self.user, name="Finanças", kind=Category.Kind.EXPENSE)
        Category.objects.create(owner=self.user, name="Transferência para cartão", kind=Category.Kind.EXPENSE, parent=financas)
        tx = self._tx("PAGAMENTO DE FATURA CARTAO")
        with _enabled():
            provider = MockProvider()
            apply_semantic(self.user, tx, provider=provider)
        self.assertEqual(tx.analysis.classification_source, TransactionAnalysis.Source.NATURE)
        self.assertEqual(tx.analysis.category_name, "Finanças")
        self.assertEqual(provider.calls, [])

    # --- Resolve ambiguidade -------------------------------------------- #
    def test_resolves_none_with_mock_provider(self):
        tx = self._tx("MERCADO SAO JOSE")
        with _enabled():
            provider = MockProvider(pins={"MERCADO JOSE": ("Alimentação", "0.88")})
            apply_semantic(self.user, tx, provider=provider)
        self.assertIsNotNone(tx.analysis)
        self.assertEqual(tx.analysis.classification_source, TransactionAnalysis.Source.SEMANTIC)
        self.assertEqual(tx.analysis.category_name, "Alimentação")
        self.assertTrue(tx.category and tx.category.name == "Alimentação")
        self.assertEqual(provider.calls, ["MERCADO JOSE"])

    # --- Nunca sobrescreve fontes de valor ------------------------------ #
    def test_never_overrides_user_correction(self):
        tx = self._tx("ESTRANHO LOJA X")
        apply_user_correction(user=self.user, transaction=tx, category=self.food)
        with _enabled():
            provider = MockProvider(pins={"STRANHO LOJA X": ("Transporte", "0.9")})
            apply_semantic(self.user, tx, provider=provider)
        self.assertEqual(tx.analysis.classification_source, TransactionAnalysis.Source.USER_CORRECTION)
        self.assertEqual(tx.category, self.food)
        self.assertEqual(provider.calls, [])

    def test_never_called_on_resolved_by_context(self):
        # "PADARIA ..." resolve deterministicamente p/ categoria Padaria do
        # usuário -> não é ambiguidade -> provider NÃO é chamado.
        tx = self._tx("PADARIA SAO JOSE")
        with _enabled():
            provider = MockProvider()
            apply_semantic(self.user, tx, provider=provider)
        self.assertEqual(tx.analysis.classification_source, TransactionAnalysis.Source.CONTEXT)
        self.assertEqual(tx.analysis.category_name, "Padaria")
        self.assertEqual(provider.calls, [])

    def test_never_overrides_movement(self):
        tx = self._tx("TRANSFERENCIA ENTRE CONTAS")
        with _enabled():
            provider = MockProvider(pins={})
            apply_semantic(self.user, tx, provider=provider)
        self.assertEqual(tx.analysis.classification_source, TransactionAnalysis.Source.MOVEMENT)

    # --- Isolamento multiusuário ---------------------------------------- #
    def test_isolation_suggestion_for_other_users_taxonomy_rejected(self):
        # Categoria que só EXISTE no taxonomy de OUTRO usuário não é aceitável.
        other_cat = Category.objects.create(owner=self.other, name="Categoria do Bob", kind=Category.Kind.EXPENSE)
        tx = self._tx("LOJA SEM REGISTRO")
        with _enabled():
            provider = MockProvider(pins={"LOJA SEM REGISTRO": (other_cat.name, "0.88")})
            apply_semantic(self.user, tx, provider=provider)
        # sugestão de categoria alheia é descartada -> cai ao determinístico
        self.assertEqual(tx.analysis.classification_source, TransactionAnalysis.Source.NONE)
        self.assertIsNone(tx.category)

    # --- Falha do provider ---------------------------------------------- #
    def test_provider_failure_falls_back(self):
        tx = self._tx("LOJA SEM REGISTRO")
        with _enabled():
            class BadProvider:
                def classify_text(self, description, direction):
                    raise RuntimeError("boom")
            apply_semantic(self.user, tx, provider=BadProvider())
        self.assertEqual(tx.analysis.classification_source, TransactionAnalysis.Source.NONE)

    # --- semantic_classify direto --------------------------------------- #
    def test_semantic_classify_direct(self):
        with _enabled():
            provider = MockProvider(pins={"MERCADO JOSE": ("Alimentação", "0.88")})
            result = semantic_classify(
                user=self.user,
                description="MERCADO SAO JOSE",
                direction="expense",
                provider=provider,
            )
        self.assertEqual(result.method, TransactionAnalysis.Source.SEMANTIC)
        self.assertEqual(result.category.name, "Alimentação")

    def test_low_confidence_needs_review(self):
        with _enabled():
            provider = MockProvider(pins={"LOJA MISTERIOSA XYZ": ("Alimentação", "0.50")})
            result = semantic_classify(
                user=self.user,
                description="LOJA MISTERIOSA XYZ",
                direction="expense",
                provider=provider,
            )
        self.assertEqual(result.method, TransactionAnalysis.Source.SEMANTIC)
        self.assertTrue(result.needs_review)
