"""Testes do Assistente Fintec (MÓDULO CHAT).

Cobrem:
- parser puro (valores, tipo, categoria, descrição, escopo, ambiguidade);
- interpretação via endpoint (rascunho, sem persistência);
- confirmação via endpoint (persistência exata + idempotência);
- segurança: usuário A não usa conta/cartão/categoria/rascunho do usuário B;
- receita nunca vai para cartão de crédito;
- despesa em cartão usa o fluxo de fatura/compra existente.
"""

from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.cards.models import CreditCard
from apps.finance.models import Account, Category, Transaction

from .services.chat_parser import (
    build_description,
    category_group_for_text,
    extract_value_cents,
    normalize_accents,
    parse_message,
)

User = get_user_model()


class ParserValueTests(TestCase):
    def test_value_58(self):
        self.assertEqual(extract_value_cents("Gastei 58 no Uber"), 5800)

    def test_value_comma_2(self):
        self.assertEqual(extract_value_cents("Paguei R$ 127,90 de mercado"), 12790)

    def test_value_comma_1(self):
        self.assertEqual(extract_value_cents("Gastei 58,5"), 5850)

    def test_value_dot_us(self):
        self.assertEqual(extract_value_cents("paguei 58.50"), 5850)

    def test_value_thousands_dot(self):
        self.assertEqual(extract_value_cents("Recebi 1.500"), 150000)

    def test_value_thousands_comma(self):
        self.assertEqual(extract_value_cents("Gastei R$ 1.500,50"), 150050)

    def test_value_reais_word(self):
        self.assertEqual(extract_value_cents("tenho 500 reais"), 50000)

    def test_value_conto(self):
        self.assertEqual(extract_value_cents("1 conto de mercado"), 100000)

    def test_value_no_value(self):
        self.assertIsNone(extract_value_cents("mercado do bairro"))

    def test_value_negative_rejected(self):
        self.assertIsNone(extract_value_cents("Gastei -10 no uber"))

    def test_zero_rejected_no_amount(self):
        parsed = parse_message("gastei zero")
        self.assertEqual(parsed["outcome"], "no_value")

    def test_absurd_rejected(self):
        parsed = parse_message("gastei 999999999999999999999")
        self.assertEqual(parsed["outcome"], "invalid_value")


class ParserOutcomeTests(TestCase):
    def test_expense_58_uber(self):
        parsed = parse_message("Gastei 58 no Uber")
        self.assertEqual(parsed["outcome"], "ok")
        self.assertEqual(parsed["type"], "expense")
        self.assertEqual(parsed["amount_cents"], 5800)
        self.assertEqual(parsed["amount"], "58.00")
        self.assertEqual(parsed["category_group"], "Transporte")
        self.assertEqual(parsed["description"], "Uber")
        self.assertFalse(parsed["type_ambiguous"])

    def test_expense_mercado(self):
        parsed = parse_message("Paguei R$ 127,90 de mercado")
        self.assertEqual(parsed["type"], "expense")
        self.assertEqual(parsed["amount_cents"], 12790)
        self.assertEqual(parsed["category_group"], "Alimentação")
        self.assertEqual(parsed["description"], "Mercado")

    def test_income_freela(self):
        parsed = parse_message("Recebi 1500 de freela")
        self.assertEqual(parsed["type"], "income")
        self.assertEqual(parsed["amount_cents"], 150000)
        self.assertEqual(parsed["category_group"], "Renda")
        self.assertEqual(parsed["description"], "Freela")

    def test_income_salary(self):
        parsed = parse_message("Ganhei R$ 2.350,50 de salário")
        self.assertEqual(parsed["type"], "income")
        self.assertEqual(parsed["amount_cents"], 235050)
        self.assertEqual(parsed["amount"], "2350.50")
        self.assertEqual(parsed["category_group"], "Renda")

    def test_out_of_scope(self):
        for msg in ("oi", "bom dia", "conte uma piada", "qual a previsão do tempo?"):
            with self.subTest(msg=msg):
                self.assertEqual(parse_message(msg)["outcome"], "scope")

    def test_ambiguous_type(self):
        parsed = parse_message("500")
        self.assertEqual(parsed["outcome"], "ok")
        self.assertIsNone(parsed["type"])
        self.assertTrue(parsed["type_ambiguous"])

    def test_tenho_reais_not_auto_expense(self):
        parsed = parse_message("tenho 500 reais")
        self.assertEqual(parsed["outcome"], "ok")
        self.assertIsNone(parsed["type"])  # nunca assume despesa por eliminação
        self.assertTrue(parsed["type_ambiguous"])

    def test_description_keeps_inner_preposition(self):
        self.assertEqual(build_description("Gastei 35 no mercado do bairro", 3500, "Alimentação"), "Mercado do Bairro")

    def test_category_detection(self):
        self.assertEqual(category_group_for_text("gastei no uber"), "Transporte")
        self.assertEqual(category_group_for_text("paguei na farmácia"), "Saúde")

    def test_normalize_accents(self):
        self.assertEqual(normalize_accents("Olá, João! Farmacia"), "ola, joao! farmacia")


# --------------------------------------------------------------------------- #


class ChatWebTestBase(TestCase):
    def setUp(self):
        from django.core.cache import cache

        cache.clear()
        self.alice = User.objects.create_user(
            username="alice", password="senha123", first_name="Alice"
        )
        self.bob = User.objects.create_user(
            username="bob", password="senha123", first_name="Bob"
        )
        self.client.login(username="alice", password="senha123")

        self.alice_acct = Account.objects.create(
            owner=self.alice, name="Conta Alice", type=Account.Type.CHECKING
        )
        self.alice_card = CreditCard.objects.create(
            owner=self.alice, name="Cartão Alice"
        )
        self.bob_acct = Account.objects.create(
            owner=self.bob, name="Conta Bob", type=Account.Type.CHECKING
        )
        self.bob_card = CreditCard.objects.create(
            owner=self.bob, name="Cartão Bob"
        )
        self.alice_cat = Category.objects.create(
            owner=self.alice, name="Restaurante", kind=Category.Kind.EXPENSE
        )
        self.bob_cat = Category.objects.create(
            owner=self.bob, name="Restaurante Bob", kind=Category.Kind.EXPENSE
        )
        self.parse_url = reverse("finance:chat_parse")
        self.confirm_url = reverse("finance:chat_confirm")

    def login_as(self, user):
        self.client.logout()
        self.client.login(username=user.username, password="senha123")


class ChatSecurityTests(ChatWebTestBase):
    def test_anonymous_redirected(self):
        self.client.logout()
        self.assertEqual(self.client.post(self.parse_url, data={}).status_code, 302)
        self.assertEqual(self.client.post(self.confirm_url, data={}).status_code, 302)

    def test_parse_nothing_saved(self):
        resp = self.client.post(
            self.parse_url,
            content_type="application/json",
            data='{"message": "Gastei 58 no Uber"}',
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Transaction.objects.count(), 0)

    def test_confirm_with_other_user_account_rejected(self):
        resp = self.client.post(
            self.confirm_url,
            content_type="application/json",
            data='{"message": "Gastei 58 no Uber", "kind": "expense", "account_id": %d}'
            % self.bob_acct.pk,
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertFalse(data["success"])
        self.assertEqual(Transaction.objects.count(), 0)

    def test_confirm_with_other_user_card_rejected(self):
        resp = self.client.post(
            self.confirm_url,
            content_type="application/json",
            data='{"message": "Gastei 58 no Uber", "kind": "expense", "card_id": %d}'
            % self.bob_card.pk,
        )
        data = resp.json()
        self.assertFalse(data["success"])
        self.assertEqual(Transaction.objects.count(), 0)

    def test_confirm_with_other_user_category_rejected(self):
        resp = self.client.post(
            self.confirm_url,
            content_type="application/json",
            data='{"message": "Gastei 58 no Uber", "kind": "expense", "account_id": %d, "category_id": %d}'
            % (self.alice_acct.pk, self.bob_cat.pk),
        )
        data = resp.json()
        self.assertFalse(data["success"])
        self.assertEqual(Transaction.objects.count(), 0)


class ChatConfirmTests(ChatWebTestBase):
    def test_expense_account_created_exactly_once(self):
        self.client.post(
            self.confirm_url,
            content_type="application/json",
            data='{"message": "Gastei 58 no Uber", "kind": "expense", "account_id": %d, "category_id": %d}'
            % (self.alice_acct.pk, self.alice_cat.pk),
        )
        tx = Transaction.objects.get()
        self.assertEqual(tx.type, Transaction.Type.EXPENSE)
        self.assertEqual(tx.amount, 5800)
        self.assertEqual(tx.account_id, self.alice_acct.pk)
        self.assertEqual(tx.category_id, self.alice_cat.pk)

    def test_duplicate_confirmation_blocked(self):
        payload = (
            '{"message": "Gastei 58 no Uber", "kind": "expense", "account_id": %d}'
            % self.alice_acct.pk
        )
        r1 = self.client.post(self.confirm_url, content_type="application/json", data=payload)
        self.assertTrue(r1.json()["success"])
        r2 = self.client.post(self.confirm_url, content_type="application/json", data=payload)
        self.assertTrue(r2.json()["success"])
        self.assertTrue(r2.json()["already_exists"])
        self.assertEqual(Transaction.objects.count(), 1)

    def test_income_requires_account(self):
        resp = self.client.post(
            self.confirm_url,
            content_type="application/json",
            data='{"message": "Recebi 1500 de freela", "kind": "income"}',
        )
        self.assertFalse(resp.json()["success"])
        self.assertEqual(Transaction.objects.count(), 0)

    def test_income_rejects_card(self):
        resp = self.client.post(
            self.confirm_url,
            content_type="application/json",
            data='{"message": "Recebi 1500 de freela", "kind": "income", "card_id": %d}'
            % self.alice_card.pk,
        )
        data = resp.json()
        self.assertFalse(data["success"])
        self.assertIn("conta", data["message"].lower())
        self.assertEqual(Transaction.objects.count(), 0)

    def test_income_created(self):
        resp = self.client.post(
            self.confirm_url,
            content_type="application/json",
            data='{"message": "Recebi 1500 de freela", "kind": "income", "account_id": %d}'
            % self.alice_acct.pk,
        )
        self.assertTrue(resp.json()["success"])
        tx = Transaction.objects.get()
        self.assertEqual(tx.type, Transaction.Type.INCOME)
        self.assertEqual(tx.amount, 150000)

    def test_expense_on_card_uses_purchase_pipeline(self):
        from apps.cards.models import InstallmentPurchase

        before = InstallmentPurchase.objects.count()
        resp = self.client.post(
            self.confirm_url,
            content_type="application/json",
            data='{"message": "Gastei 58 no Uber", "kind": "expense", "card_id": %d}'
            % self.alice_card.pk,
        )
        self.assertTrue(resp.json()["success"])
        purchase = InstallmentPurchase.objects.get()
        self.assertEqual(purchase.card_id, self.alice_card.pk)
        self.assertEqual(purchase.installment_count, 1)
        self.assertEqual(purchase.total_amount, 5800)
        self.assertEqual(InstallmentPurchase.objects.count(), before + 1)
        # Despesa de cartão NÃO cria Transaction de débito de conta.
        self.assertEqual(Transaction.objects.count(), 0)


class ChatInterpretTests(ChatWebTestBase):
    def test_parse_returns_draft_without_saving(self):
        resp = self.client.post(
            self.parse_url,
            content_type="application/json",
            data='{"message": "Gastei 58 no Uber"}',
        )
        data = resp.json()
        self.assertTrue(data["success"])
        draft = data["draft"]
        self.assertEqual(draft["type"], "expense")
        self.assertEqual(draft["amount"], "58.00")
        self.assertEqual(draft["description"], "Uber")
        self.assertEqual(draft["category_group"], "Transporte")
        self.assertTrue(data["accounts"])
        self.assertEqual(Transaction.objects.count(), 0)

    def test_parse_ambiguous_type_flag(self):
        resp = self.client.post(
            self.parse_url,
            content_type="application/json",
            data='{"message": "500"}',
        )
        data = resp.json()
        self.assertTrue(data["success"])
        self.assertTrue(data["type_ambiguous"])
        self.assertIsNone(data["draft"]["type"])

    def test_parse_out_of_scope(self):
        resp = self.client.post(
            self.parse_url,
            content_type="application/json",
            data='{"message": "oi"}',
        )
        data = resp.json()
        self.assertFalse(data["success"])
        self.assertIn("entradas e saídas", data["message"])

    def test_parse_no_value(self):
        resp = self.client.post(
            self.parse_url,
            content_type="application/json",
            data='{"message": "mercado do bairro"}',
        )
        data = resp.json()
        self.assertFalse(data["success"])
        self.assertIn("valor", data["message"].lower())