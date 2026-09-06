"""Testes do Motor de Classificação Financeira (Ordem 18 — FASE 5).

Cobre (itens §20):
  - classificação básica (Merchant/alias -> categoria);
  - prioridade/ordem determinística (§3);
  - aprendizado por correção (memória determinística) e reversibilidade;
  - ambiguidade / sem evidência -> revisão humana;
  - movimentações neutras (fatura/dívida não vira consumo comum);
  - isolamento multiusuário (memória nunca vaza entre usuários);
  - regra global e regra pessoal;
  - persistência da decisão (TransactionAnalysis) no caminho de importação;
  - correção manual e re-aplicação da categoria na Transaction.
"""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from .models import (
    Account,
    Category,
    ClassificationRule,
    Merchant,
    MerchantAlias,
    Transaction,
    TransactionAnalysis,
)
from .services.categories import create_category, seed_default_categories
from .services.classifier import (
    apply_user_correction,
    classify,
    classify_transaction,
)
from .services.memory import forget, learn
from .services.merchants import learn_alias, normalize_description, resolve_merchant

User = get_user_model()


class ClassifierBase(TestCase):
    def setUp(self):
        self.alice = User.objects.create_user(username="alice", password="x")
        self.bob = User.objects.create_user(username="bob", password="y")
        self.account = Account.objects.create(owner=self.alice, name="Conta")
        seed_default_categories(user=self.alice)
        seed_default_categories(user=self.bob)
        self.get_cat = lambda name: Category.objects.for_user(self.alice).filter(
            name__iexact=name, kind=Category.Kind.EXPENSE, status=Category.Status.ACTIVE
        ).first()


class BasicClassificationTests(ClassifierBase):
    def test_merchant_default_category_maps_to_real_category(self):
        m = Merchant.objects.create(
            owner=None, name="Uber", default_category_name="Transporte"
        )
        MerchantAlias.objects.create(owner=None, merchant=m, alias="UBER")
        res = classify(user=self.alice, description="UBER *TRIP 1234", direction="expense", merchant=m)
        self.assertEqual(res.method, TransactionAnalysis.Source.MERCHANT)
        self.assertEqual(res.category.name, "Transporte")
        self.assertFalse(res.needs_review)

    def test_context_maps_supermarket_to_home_food_category(self):
        # "MERCADO" é resolvido por contexto, categoria de despesa de alimentação.
        res = classify(user=self.alice, description="MERCADO BOM SUPERMERCADO", direction="expense")
        self.assertEqual(res.category.name, "Supermercado")
        self.assertEqual(res.method, TransactionAnalysis.Source.CONTEXT)

    def test_unknown_price_needs_review(self):
        res = classify(user=self.alice, description="PAGAMENTO AVULSO X9Q4", direction="expense")
        self.assertEqual(res.method, TransactionAnalysis.Source.NONE)
        self.assertTrue(res.needs_review)
        self.assertEqual(res.confidence, Decimal("0.00"))

    def test_direction_income_resolves_income_kind(self):
        res = classify(user=self.alice, description="SALARIO EMPRESA X", direction="income")
        self.assertIn(
            res.method,
            (TransactionAnalysis.Source.NATURE, TransactionAnalysis.Source.CONTEXT),
        )
        self.assertEqual(res.category.kind, Category.Kind.INCOME)

    def test_bank_prefix_is_stripped_from_normalization(self):
        # "PAG*Carrefour 0041" (PagSeguro) deve normalizar para "CARREFOUR",
        # preservando o merchant e removendo o prefixo/código numérico.
        self.assertEqual(normalize_description("PAG*Carrefour 0041"), "CARREFOUR")
        self.assertEqual(normalize_description("COMPRA CREDITO 09/03 NETFLIX.COM"), "NETFLIX")
        self.assertEqual(normalize_description("NXPG*IFOOD.COM"), "IFOOD")
        self.assertEqual(normalize_description("C6S*NETFLIX"), "NETFLIX")

    def test_resolved_merchant_from_prefixed_description_classifies(self):
        # Fluxo real de importação: resolve o merchant de uma descrição com
        # prefixo de banco e classifica pela associação do catálogo.
        m = Merchant.objects.create(
            owner=None, name="Carrefour", default_category_name="Supermercado"
        )
        MerchantAlias.objects.create(owner=None, merchant=m, alias="CARREFOUR")
        res_merchant = resolve_merchant(self.alice, "PAG*Carrefour 0041")
        self.assertTrue(res_merchant.matched)
        self.assertEqual(res_merchant.merchant, m)
        res = classify(
            user=self.alice,
            description="PAG*Carrefour 0041",
            direction="expense",
            merchant=res_merchant.merchant,
        )
        self.assertEqual(res.method, TransactionAnalysis.Source.MERCHANT)
        self.assertEqual(res.category.name, "Supermercado")
        self.assertFalse(res.needs_review)


class PriorityTests(ClassifierBase):
    def test_user_correction_beats_merchant(self):
        # Merchant indica Transporte, mas usuário corrigiu para Combustível.
        m = Merchant.objects.create(
            owner=None, name="Posto", default_category_name="Transporte"
        )
        MerchantAlias.objects.create(owner=None, merchant=m, alias="POSTO")
        gas = self.get_cat("Combustível")
        learn(user=self.alice, key="POSTO", category=gas, kind="expense")
        res = classify(user=self.alice, description="POSTO", direction="expense", merchant=m)
        self.assertEqual(res.method, TransactionAnalysis.Source.USER_CORRECTION)
        self.assertEqual(res.category.name, "Combustível")
        self.assertFalse(res.needs_review)

    def test_user_rule_beats_merchant_association(self):
        m = Merchant.objects.create(
            owner=None, name="Posto", default_category_name="Transporte"
        )
        MerchantAlias.objects.create(owner=None, merchant=m, alias="POSTO")
        gas = self.get_cat("Combustível")
        ClassificationRule.objects.create(
            owner=self.alice,
            name="Regra posto",
            condition_type=ClassificationRule.ConditionType.CONTAINS,
            pattern="POSTO",
            category=gas,
            kind=ClassificationRule.Kind.EXPENSE,
            priority=10,
        )
        res = classify(user=self.alice, description="POSTO AX", direction="expense", merchant=m)
        self.assertEqual(res.method, TransactionAnalysis.Source.USER_RULE)
        self.assertEqual(res.category.name, "Combustível")

    def test_global_rule_applies_when_no_personal_evidence(self):
        ClassificationRule.objects.create(
            owner=None,
            name="Regra global restaurante",
            condition_type=ClassificationRule.ConditionType.CONTAINS,
            pattern="LANCHONETE",
            category_name="Restaurante",
            kind=ClassificationRule.Kind.EXPENSE,
            priority=5,
        )
        res = classify(user=self.alice, description="LANCHONETE CENTRO", direction="expense")
        self.assertEqual(res.method, TransactionAnalysis.Source.GLOBAL_RULE)

    def test_global_rule_never_overrides_user_correction(self):
        ClassificationRule.objects.create(
            owner=None,
            name="global",
            condition_type=ClassificationRule.ConditionType.CONTAINS,
            pattern="PADARIA",
            category_name="Restaurante",
            kind=ClassificationRule.Kind.EXPENSE,
            priority=5,
        )
        padaria = self.get_cat("Padaria")
        learn(user=self.alice, key="PADARIA", category=padaria, kind="expense")
        res = classify(user=self.alice, description="PADARIA", direction="expense")
        self.assertEqual(res.method, TransactionAnalysis.Source.USER_CORRECTION)
        self.assertEqual(res.category.name, "Padaria")


class LearningTests(ClassifierBase):
    def test_learning_reused_and_isolated(self):
        padaria = self.get_cat("Padaria")
        learn(user=self.alice, key="PADARIA", category=padaria, kind="expense")
        res = classify(user=self.alice, description="PADARIA", direction="expense")
        self.assertEqual(res.method, TransactionAnalysis.Source.USER_CORRECTION)
        # Bob nunca aprendeu -> cai no contexto (Padaria por palavra), não memória.
        res_bob = classify(user=self.bob, description="PADARIA", direction="expense")
        self.assertNotEqual(res_bob.method, TransactionAnalysis.Source.USER_CORRECTION)

    def test_forget_reverts_learning(self):
        padaria = self.get_cat("Padaria")
        learn(user=self.alice, key="PADARIA VILA", category=padaria, kind="expense")
        self.assertEqual(
            classify(user=self.alice, description="PADARIA VILA", direction="expense").method,
            TransactionAnalysis.Source.USER_CORRECTION,
        )
        forget(user=self.alice, key="PADARIA VILA")
        res = classify(user=self.alice, description="PADARIA VILA", direction="expense")
        self.assertNotEqual(res.method, TransactionAnalysis.Source.USER_CORRECTION)

    def test_isolation_memory_never_crosses_users(self):
        via = self.get_cat("Streaming de vídeo")
        learn(user=self.alice, key="NETFLIX", category=via, kind="expense")
        res_bob = classify(user=self.bob, description="NETFLIX", direction="expense")
        # Bob não tem memória NETFLIX; cai em contexto -> Streaming de vídeo tb,
        # mas o METHOD não deve ser user_correction.
        self.assertNotEqual(res_bob.method, TransactionAnalysis.Source.USER_CORRECTION)


class MovementTests(ClassifierBase):
    def test_card_invoice_payment_is_transfer_not_consumption(self):
        # Pagamento de fatura NÃO é consumo comum: vira "Transferência para
        # cartão" (FASE 1) e é roteado como transferência no commit — sem
        # dupla contabilidade de consumo.
        res = classify(user=self.alice, description="PAGAMENTO DE FATURA 0012", direction="expense")
        self.assertFalse(res.is_movement)
        self.assertEqual(res.method, TransactionAnalysis.Source.NATURE)
        self.assertEqual(res.category.name, "Transferência para cartão")
        self.assertFalse(res.needs_review)

    def test_debt_payment_is_movement_not_consumption(self):
        res = classify(user=self.alice, description="PAGAMENTO DE DIVIDA EMPRESTIMO", direction="expense")
        self.assertTrue(res.is_movement)
        self.assertEqual(res.method, TransactionAnalysis.Source.MOVEMENT)
        self.assertIsNone(res.category)


class CorrectionApplicationTests(ClassifierBase):
    def _make_tx(self):
        return Transaction.objects.create(
            owner=self.alice,
            account=self.account,
            type=Transaction.Type.EXPENSE,
            amount=1500,
            date="2026-09-01",
            description="UBER TRIP",
        )

    def test_apply_user_correction_updates_category_and_analysis(self):
        tx = self._make_tx()
        transporte = self.get_cat("Transporte")
        apply_user_correction(
            user=self.alice, transaction=tx, category=transporte
        )
        tx.refresh_from_db()
        self.assertEqual(tx.category, transporte)
        analysis = TransactionAnalysis.objects.get(transaction=tx)
        self.assertEqual(analysis.user_corrected, True)
        self.assertEqual(
            analysis.classification_source, TransactionAnalysis.Source.USER_CORRECTION
        )

    def test_apply_user_correction_learns(self):
        tx = self._make_tx()
        transporte = self.get_cat("Transporte")
        apply_user_correction(user=self.alice, transaction=tx, category=transporte)
        res = classify(user=self.alice, description="UBER TRIP", direction="expense")
        self.assertEqual(res.method, TransactionAnalysis.Source.USER_CORRECTION)
        self.assertEqual(res.category, transporte)

    def test_correction_rejects_other_users_category(self):
        tx = self._make_tx()
        bob_cat = create_category(user=self.bob, name="Outro", kind="expense")
        with self.assertRaises(ValueError):
            apply_user_correction(user=self.alice, transaction=tx, category=bob_cat)


class CommitAnalysisTests(ClassifierBase):
    def _ingest_csv(self, content: bytes):
        from apps.imports.services.importer import ingest

        return ingest(
            user=self.alice,
            file_type="csv",
            file_name="mov.csv",
            content=content,
            default_account=self.account,
        )

    def test_commit_creates_transaction_analysis(self):
        m = Merchant.objects.create(
            owner=None, name="iFood", default_category_name="Alimentação"
        )
        MerchantAlias.objects.create(owner=None, merchant=m, alias="IFOOD")
        from apps.imports.services.commit import commit_batch

        batch = self._ingest_csv(
            b"data,descricao,valor\n"
            b"01/09/2026,IFOOD *PEDIDO 88,-35,00\n"
        )
        res = commit_batch(user=self.alice, batch=batch, account=self.account)
        self.assertEqual(res.imported, 1)
        tx = Transaction.objects.get(owner=self.alice)
        analysis = TransactionAnalysis.objects.get(transaction=tx)
        self.assertEqual(analysis.merchant, m)
        self.assertEqual(analysis.classification_source, TransactionAnalysis.Source.MERCHANT)
        self.assertEqual(analysis.confidence, Decimal("0.92"))
        self.assertFalse(analysis.needs_review)


class NatureLayerTests(ClassifierBase):
    """Camada de NATUREZA da transação (agnóstica de banco)."""

    def _inc(self, name):
        return Category.objects.for_user(self.alice).filter(
            name__iexact=name, kind=Category.Kind.INCOME, status=Category.Status.ACTIVE
        ).first()

    def test_salary_nature_resolved(self):
        for desc in (
            "Empresa Tech LTDA - Pagamento Salarial",
            "Pagamento Salarial - Empresa X",
            "Salário Mensal - Banco Y",
        ):
            res = classify(user=self.alice, description=desc, direction="income")
            self.assertEqual(res.method, TransactionAnalysis.Source.NATURE, desc)
            self.assertEqual(res.category.name, "Salário")
            self.assertFalse(res.needs_review)

    def test_tarifa_nature_resolved(self):
        for desc in ("Tarifa de manutenção de conta", "Tarifa bancária mensal"):
            res = classify(user=self.alice, description=desc, direction="expense")
            self.assertEqual(res.method, TransactionAnalysis.Source.NATURE, desc)
            self.assertEqual(res.category.name, "Tarifas bancárias")
            self.assertFalse(res.needs_review)

    def test_rendimento_nature_resolved(self):
        res = classify(
            user=self.alice, description="Rendimento Automático NuConta", direction="income"
        )
        self.assertEqual(res.method, TransactionAnalysis.Source.NATURE)
        self.assertEqual(res.category.name, "Retorno de aplicações")
        self.assertFalse(res.needs_review)

    def test_reembolso_is_not_salary(self):
        res = classify(
            user=self.alice, description="PIX Recebido - Reembolso / Amigos", direction="income"
        )
        self.assertEqual(res.method, TransactionAnalysis.Source.NATURE)
        self.assertEqual(res.category.name, "Reembolso")
        self.assertEqual(res.category.kind, Category.Kind.INCOME)
        self.assertFalse(res.needs_review)

    def test_fatura_is_transfer_not_consumption(self):
        res = classify(user=self.alice, description="Pagamento de Fatura 0012", direction="expense")
        self.assertFalse(res.is_movement)
        self.assertEqual(res.category.name, "Transferência para cartão")
        self.assertFalse(res.needs_review)
        self.assertEqual(res.method, TransactionAnalysis.Source.NATURE)

    def test_accented_merchant_not_fragmented(self):
        # Bug: acento quebrava tokenização ("Farmácia" -> "FARM"); "Farmácia
        # São Paulo" casava com a loja "Farm" (Vestuário). Deve ser Farmácia.
        agg = Merchant.objects.create(
            owner=None, name="Açúcar e Cia", default_category_name="Supermercado"
        )
        MerchantAlias.objects.create(owner=None, merchant=agg, alias="ACUCAR CIA")
        # fluxo real de importação: o merchant é resolvido antes de classificar
        res = resolve_merchant(self.alice, "Supermercado Açúcar e Cia")
        self.assertTrue(res.matched)
        self.assertEqual(res.merchant, agg)
        cls = classify(
            user=self.alice,
            description="Supermercado Açúcar e Cia",
            direction="expense",
            merchant=res.merchant,
        )
        self.assertEqual(cls.category.name, "Supermercado")
        self.assertEqual(cls.method, TransactionAnalysis.Source.MERCHANT)
        self.assertFalse(cls.needs_review)


class SuggestedCategoryTests(ClassifierBase):
    """Categoria sugerida pelo arquivo do cliente (coluna do seu formato)."""

    def test_suggested_leaf_category_is_used(self):
        # Sem sinal determinístico, a categoria do arquivo decide (não revisa).
        res = classify(
            user=self.alice,
            description="SUSHI EXPRESS",
            direction="expense",
            suggested_category="Restaurante",
        )
        self.assertEqual(res.method, TransactionAnalysis.Source.SUGGESTED)
        self.assertEqual(res.category.name, "Restaurante")
        self.assertFalse(res.needs_review)

    def test_suggested_parent_category_is_used(self):
        # "Alimentação" é categoria-pai; o leaf "Restaurante" já pertence a ela.
        res = classify(
            user=self.alice,
            description="BURGUER HOUSE",
            direction="expense",
            suggested_category="Alimentação",
        )
        self.assertEqual(res.category.name, "Alimentação")
        self.assertEqual(res.method, TransactionAnalysis.Source.SUGGESTED)
        self.assertFalse(res.needs_review)

    def test_nature_overrides_suggested_category(self):
        # Natureza (Salário) é estrutural e prevalece sobre a sugestão difusa.
        res = classify(
            user=self.alice,
            description="Pagamento Salarial - Empresa X",
            direction="income",
            suggested_category="Outros",
        )
        self.assertEqual(res.method, TransactionAnalysis.Source.NATURE)
        self.assertEqual(res.category.name, "Salário")

    def test_movement_not_overridden_by_suggested(self):
        # Fatura vira "Transferência para cartão" (natureza) na FASE 1;
        # a categoria sugerida NÃO a transforma em consumo (ex: Restaurante).
        res = classify(
            user=self.alice,
            description="Pagamento de Fatura 0012",
            direction="expense",
            suggested_category="Restaurante",
        )
        self.assertEqual(res.method, TransactionAnalysis.Source.NATURE)
        self.assertEqual(res.category.name, "Transferência para cartão")
        self.assertNotEqual(res.category.name, "Restaurante")

    def test_suggested_ignored_when_unknown(self):
        # Categoria sugerida inexistente não deve travar nem revisar.
        res = classify(
            user=self.alice,
            description="LOJA DESCONHECIDA",
            direction="expense",
            suggested_category="Categoria Que Não Existe 999",
        )
        self.assertEqual(res.method, TransactionAnalysis.Source.NONE)


class CatalogContextRegressionTests(ClassifierBase):
    """Os 3 estabelecimentos que caíam em contexto (0.70 = revisão) devem agora
    resolver por Merchant do catálogo (0.92 = automático, sem revisão)."""

    def _seed_catalog(self):
        from django.core.management import call_command

        call_command("seed_merchants", verbosity=0)

    def test_cinema_severiano_resolves_as_merchant(self):
        self._seed_catalog()
        res = resolve_merchant(self.alice, "CINEMA SEVERIANO RIBEIRO")
        self.assertTrue(res.matched)
        self.assertEqual(res.merchant.name, "Cinema Severiano Ribeiro")
        cl = classify(
            user=self.alice,
            description="CINEMA SEVERIANO RIBEIRO",
            direction="expense",
            merchant=res.merchant,
        )
        self.assertEqual(cl.method, TransactionAnalysis.Source.MERCHANT)
        self.assertEqual(cl.category.name, "Cinema")
        self.assertFalse(cl.needs_review)

    def test_companhia_eletrica_resolves_as_merchant(self):
        self._seed_catalog()
        res = resolve_merchant(self.alice, "COMPANHIA ELETRICA CONTA LUZ")
        self.assertTrue(res.matched)
        self.assertEqual(res.merchant.name, "Companhia Elétrica")
        cl = classify(
            user=self.alice,
            description="COMPANHIA ELETRICA CONTA LUZ",
            direction="expense",
            merchant=res.merchant,
        )
        self.assertEqual(cl.method, TransactionAnalysis.Source.MERCHANT)
        self.assertEqual(cl.category.name, "Energia elétrica")
        self.assertFalse(cl.needs_review)

    def test_provedor_telecom_resolves_as_merchant(self):
        self._seed_catalog()
        res = resolve_merchant(self.alice, "PROVEDOR TELECOM INTERNET FIBRA")
        self.assertTrue(res.matched)
        self.assertEqual(res.merchant.name, "Provedor Telecom")
        cl = classify(
            user=self.alice,
            description="PROVEDOR TELECOM INTERNET FIBRA",
            direction="expense",
            merchant=res.merchant,
        )
        self.assertEqual(cl.method, TransactionAnalysis.Source.MERCHANT)
        self.assertEqual(cl.category.name, "Internet")
        self.assertFalse(cl.needs_review)

    def test_catalog_aliases_do_not_collide_with_existing(self):
        # Não pode roubar o match do catálogo existente (Cinemark / Algar).
        self._seed_catalog()
        res = resolve_merchant(self.alice, "CINEMARK")
        self.assertTrue(res.matched)
        self.assertEqual(res.merchant.name, "Cinemark")
        res2 = resolve_merchant(self.alice, "ALGAR TELECOM")
        self.assertTrue(res2.matched)
        self.assertEqual(res2.merchant.name, "Algar Telecom")


class PixCategoryTests(ClassifierBase):
    """PIX enviado/recebido devem ter categorias próprias (não movimento neutro)."""

    def test_pix_enviado_resolves_to_envio_de_pix(self):
        res = classify(user=self.alice, description="PIX ENVIADO JOAO SILVA", direction="expense")
        self.assertEqual(res.method, TransactionAnalysis.Source.NATURE)
        self.assertEqual(res.category.name, "Envio de PIX")
        self.assertEqual(res.category.kind, Category.Kind.EXPENSE)
        self.assertFalse(res.needs_review)

    def test_pix_recebido_resolves_to_recebimento_de_pix(self):
        res = classify(user=self.alice, description="PIX RECEBIDO EMPRESA X", direction="income")
        self.assertEqual(res.method, TransactionAnalysis.Source.NATURE)
        self.assertEqual(res.category.name, "Recebimento de PIX")
        self.assertEqual(res.category.kind, Category.Kind.INCOME)
        self.assertFalse(res.needs_review)

    def test_pix_credito_resolves_to_recebimento_de_pix(self):
        res = classify(user=self.alice, description="PIX CREDITO 12345", direction="income")
        self.assertEqual(res.method, TransactionAnalysis.Source.NATURE)
        self.assertEqual(res.category.name, "Recebimento de PIX")
        self.assertFalse(res.needs_review)

    def test_pix_entre_contas_remains_movement(self):
        res = classify(user=self.alice, description="PIX ENTRE CONTAS", direction="expense")
        self.assertTrue(res.is_movement)
        self.assertIsNone(res.category)
        self.assertFalse(res.needs_review)


class InvoicePaymentTests(ClassifierBase):
    """FATURA de cartão → Transferência para cartão (não despesa de consumo)."""

    def test_fatura_classified_as_transfer(self):
        res = classify(user=self.alice, description="PAGTO FATURA NUBANK", direction="expense")
        self.assertEqual(res.method, TransactionAnalysis.Source.NATURE)
        self.assertEqual(res.category.name, "Transferência para cartão")
        self.assertEqual(res.category.kind, Category.Kind.EXPENSE)
        self.assertFalse(res.needs_review)
        self.assertFalse(res.is_movement)

    def test_fatura_nubank(self):
        res = classify(user=self.alice, description="FATURA NUBANK", direction="expense")
        self.assertEqual(res.category.name, "Transferência para cartão")

    def test_fat_inter(self):
        res = classify(user=self.alice, description="FAT. INTER", direction="expense")
        self.assertEqual(res.category.name, "Transferência para cartão")

    def test_fat_itau(self):
        res = classify(user=self.alice, description="FAT. ITAU PERSONALITE", direction="expense")
        self.assertEqual(res.category.name, "Transferência para cartão")

    def test_pgto_fatura_bradesco(self):
        res = classify(user=self.alice, description="PGTO FATURA BRADESCO", direction="expense")
        self.assertEqual(res.category.name, "Transferência para cartão")

    def test_fatura_c6_bank(self):
        res = classify(user=self.alice, description="FATURA C6 BANK", direction="expense")
        self.assertEqual(res.category.name, "Transferência para cartão")

    def test_fat_sicredi(self):
        res = classify(user=self.alice, description="FAT SICREDI", direction="expense")
        self.assertEqual(res.category.name, "Transferência para cartão")


class ExtractCardNameTests(ClassifierBase):
    """extract_card_name extrai o nome do cartão de descrições de fatura."""

    def test_nubank(self):
        from .services.classifier import extract_card_name
        self.assertEqual(extract_card_name("PAGTO FATURA NUBANK"), "Nubank")

    def test_inter(self):
        from .services.classifier import extract_card_name
        self.assertEqual(extract_card_name("FAT. INTER"), "Inter")

    def test_itau(self):
        from .services.classifier import extract_card_name
        self.assertEqual(extract_card_name("PGTO FATURA ITAU CLICK"), "Itaú")

    def test_bradesco(self):
        from .services.classifier import extract_card_name
        self.assertEqual(extract_card_name("PAG. FAT. BRADESCO"), "Bradesco")

    def test_c6(self):
        from .services.classifier import extract_card_name
        self.assertEqual(extract_card_name("FATURA C6 BANK"), "C6 Bank")

    def test_sicredi(self):
        from .services.classifier import extract_card_name
        self.assertEqual(extract_card_name("FAT SICREDI"), "Sicredi")

    def test_nu_cartao(self):
        from .services.classifier import extract_card_name
        self.assertEqual(extract_card_name("FATURA DO CARTAO NU"), "Nubank")

    def test_empty_returns_none(self):
        from .services.classifier import extract_card_name
        self.assertIsNone(extract_card_name(""))

    def test_none_returns_none(self):
        from .services.classifier import extract_card_name
        self.assertIsNone(extract_card_name(None))

    def test_non_fatura_returns_none(self):
        from .services.classifier import extract_card_name
        self.assertIsNone(extract_card_name("COMPRA NUBANK SUPERMERCADO"))


