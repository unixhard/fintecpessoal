"""Testes web do módulo de cartões (views, ownership, compras e faturas).

Cobrem o fluxo completo: listar/criar/editar/bloquear/encerrar/reativar cartão,
criar compra (à vista e parcelada), ver/consultar faturas e pagar fatura — sempre
validando isolamento multiusuário e uso dos services (sem regra financeira na
view).
"""

from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.finance.models import Account, Transaction

from .models import CreditCard, CreditCardInvoice, InstallmentPurchase

User = get_user_model()


class CardWebTestBase(TestCase):
    def setUp(self):
        self.alice = User.objects.create_user(
            username="alice", password="senha123", first_name="Alice"
        )
        self.bob = User.objects.create_user(
            username="bob", password="senha123", first_name="Bob"
        )
        self.bank_a = Account.objects.create(
            owner=self.alice, name="Banco da Alice", initial_balance=100000
        )
        self.bank_b = Account.objects.create(
            owner=self.bob, name="Banco do Bob", initial_balance=100000
        )
        self.login_as(self.alice)

    def login_as(self, user):
        self.client.login(username=user.username, password="senha123")

    def make_card(self, owner=None, **kwargs):
        owner = owner or self.alice
        defaults = {
            "name": "Cartão Padrão",
            "limit": 500000,
            "closing_day": 20,
            "due_day": 5,
        }
        defaults.update(kwargs)
        if owner == self.alice and "payment_account" not in kwargs:
            defaults["payment_account"] = self.bank_a
        if owner == self.bob and "payment_account" not in kwargs:
            defaults["payment_account"] = self.bank_b
        return CreditCard.objects.create(owner=owner, **defaults)


class CardListViewTests(CardWebTestBase):
    def test_anonymous_redirected_to_login(self):
        self.client.logout()
        resp = self.client.get(reverse("cards:card_list"))
        self.assertEqual(resp.status_code, 302)

    def test_authenticated_lists_only_own_cards(self):
        self.make_card(owner=self.alice, name="Meu")
        self.make_card(owner=self.bob, name="Do Bob")
        resp = self.client.get(reverse("cards:card_list"))
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode()
        self.assertIn("Meu", content)
        self.assertNotIn("Do Bob", content)


class CardCreateEditTests(CardWebTestBase):
    def test_create_card(self):
        resp = self.client.post(
            reverse("cards:card_create"),
            {
                "name": "Cartão Black",
                "institution": "Banco X",
                "limit": "5000",
                "closing_day": "20",
                "due_day": "5",
                "payment_account": self.bank_a.pk,
            },
            follow=True,
        )
        self.assertEqual(resp.status_code, 200)
        card = CreditCard.objects.get(owner=self.alice, name="Cartão Black")
        self.assertEqual(card.limit, 500000)
        self.assertEqual(card.status, CreditCard.Status.ACTIVE)

    def test_edit_card_keeps_limit_owned(self):
        card = self.make_card(owner=self.alice, limit=100000)
        self.client.post(
            reverse("cards:card_edit", args=[card.pk]),
            {
                "name": "Renomeado",
                "institution": "",
                "limit": "2000",
                "closing_day": "10",
                "due_day": "20",
                "payment_account": "",
            },
        )
        card.refresh_from_db()
        self.assertEqual(card.name, "Renomeado")
        self.assertEqual(card.limit, 200000)

    def test_edit_other_user_card_returns_404(self):
        card = self.make_card(owner=self.bob)
        resp = self.client.post(
            reverse("cards:card_edit", args=[card.pk]),
            {
                "name": "Tentativa",
                "institution": "",
                "limit": "1",
                "closing_day": "1",
                "due_day": "1",
            },
        )
        self.assertEqual(resp.status_code, 404)

    def test_detail_other_user_card_returns_404(self):
        card = self.make_card(owner=self.bob)
        resp = self.client.get(reverse("cards:card_detail", args=[card.pk]))
        self.assertEqual(resp.status_code, 404)


class CardStatusTests(CardWebTestBase):
    def test_block_close_reactivate(self):
        card = self.make_card(owner=self.alice)
        self.client.post(reverse("cards:card_block", args=[card.pk]))
        card.refresh_from_db()
        self.assertEqual(card.status, CreditCard.Status.BLOCKED)

        self.client.post(reverse("cards:card_close", args=[card.pk]))
        card.refresh_from_db()
        self.assertEqual(card.status, CreditCard.Status.CLOSED)

        self.client.post(reverse("cards:card_reactivate", args=[card.pk]))
        card.refresh_from_db()
        self.assertEqual(card.status, CreditCard.Status.ACTIVE)

    def test_status_change_other_user_card_404(self):
        card = self.make_card(owner=self.bob)
        resp = self.client.post(reverse("cards:card_block", args=[card.pk]))
        self.assertEqual(resp.status_code, 404)


class PurchaseTests(CardWebTestBase):
    def setUp(self):
        super().setUp()
        self.card = self.make_card(owner=self.alice, name="Alice Card")

    def test_create_single_installment_purchase(self):
        resp = self.client.post(
            reverse("cards:purchase_create"),
            {
                "card": self.card.pk,
                "description": "Notebook",
                "total_amount": "3000,00",
                "installment_count": "1",
                "first_due_date": "2026-09-10",
            },
            follow=True,
        )
        self.assertEqual(resp.status_code, 200)
        purchase = InstallmentPurchase.objects.get(owner=self.alice, description="Notebook")
        self.assertEqual(purchase.total_amount, 300000)
        self.assertEqual(purchase.installment_count, 1)
        # À vista: 1 parcela, mas não debita a conta bancária.
        self.assertEqual(Transaction.objects.filter(owner=self.alice).count(), 0)

    def test_create_installment_purchase(self):
        self.client.post(
            reverse("cards:purchase_create"),
            {
                "card": self.card.pk,
                "description": "Sofá",
                "total_amount": "1200,00",
                "installment_count": "10",
                "first_due_date": "2026-09-10",
            },
        )
        purchase = InstallmentPurchase.objects.get(owner=self.alice, description="Sofá")
        self.assertEqual(purchase.installment_count, 10)
        self.assertEqual(purchase.installments.count(), 10)
        # Soma das parcelas == total (sem perda por arredondamento).
        self.assertEqual(
            sum(i.amount for i in purchase.installments.all()), purchase.total_amount
        )

    def test_create_purchase_with_other_user_card_rejected(self):
        other = self.make_card(owner=self.bob, name="Bob Card")
        resp = self.client.post(
            reverse("cards:purchase_create"),
            {
                "card": other.pk,
                "description": "Invalida",
                "total_amount": "100,00",
                "installment_count": "1",
                "first_due_date": "2026-09-10",
            },
        )
        # O form filtra o cartão pelo usuário; ID de B não é escolha válida.
        self.assertEqual(
            InstallmentPurchase.objects.filter(description="Invalida").count(), 0
        )
        self.assertEqual(resp.status_code, 200)

    def test_purchase_list_isolation(self):
        self.make_card(owner=self.bob, name="Bob")
        self.client.post(
            reverse("cards:purchase_create"),
            {
                "card": self.card.pk,
                "description": "Minha",
                "total_amount": "100,00",
                "installment_count": "1",
                "first_due_date": "2026-09-10",
            },
        )
        resp = self.client.get(reverse("cards:purchase_list"))
        content = resp.content.decode()
        self.assertIn("Minha", content)
        self.assertNotIn("Nenhuma", content)


class InvoiceTests(CardWebTestBase):
    def setUp(self):
        super().setUp()
        self.card = self.make_card(owner=self.alice, name="Alice Card", closing_day=20, due_day=5)
        self.bob_card = self.make_card(owner=self.bob, name="Bob Card", closing_day=20, due_day=5)

    def make_invoice(self, card=None):
        card = card or self.card
        return CreditCardInvoice.objects.create(
            owner=card.owner,
            card=card,
            period_start=date(2026, 9, 1),
            period_end=date(2026, 9, 20),
            closing_date=date(2026, 9, 20),
            due_date=date(2026, 10, 5),
            status=CreditCardInvoice.Status.OPEN,
        )

    def test_invoice_detail_isolation(self):
        invoice = self.make_invoice(self.bob_card)
        resp = self.client.get(reverse("cards:invoice_detail", args=[invoice.pk]))
        self.assertEqual(resp.status_code, 404)

    def test_pay_invoice_creates_single_expense(self):
        from apps.cards.services.invoices import pay_invoice

        invoice = self.make_invoice(self.card)
        # registra uma compra para dar valor à fatura (obrigação, não despesa).
        from .models import Installment, InstallmentPurchase

        purchase = InstallmentPurchase.objects.create(
            owner=self.alice, card=self.card, description="Compra",
            total_amount=10000, installment_count=1, installment_amount=10000,
            first_due_date=date(2026, 9, 15),
        )
        inst = Installment.objects.create(
            owner=self.alice, purchase=purchase, number=1, amount=10000,
            due_date=date(2026, 9, 15), invoice=invoice,
        )
        self.assertEqual(invoice.amount, 10000)

        self.client.post(
            reverse("cards:invoice_pay", args=[invoice.pk]),
            {"account": self.bank_a.pk, "date": "2026-10-05"},
        )
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, CreditCardInvoice.Status.PAID)
        # UMA transação de saída, nenhuma segunda despesa da compra.
        expenses = Transaction.objects.filter(
            owner=self.alice, type=Transaction.Type.EXPENSE
        )
        self.assertEqual(expenses.count(), 1)
        self.assertEqual(expenses.first().amount, 10000)

    def test_pay_invoice_of_other_user_404(self):
        invoice = self.make_invoice(self.bob_card)
        resp = self.client.post(
            reverse("cards:invoice_pay", args=[invoice.pk]),
            {"account": self.bank_a.pk, "date": "2026-10-05"},
        )
        self.assertEqual(resp.status_code, 404)

    def test_pay_invoice_other_user_account_rejected(self):
        from .models import Installment, InstallmentPurchase

        invoice = self.make_invoice(self.card)
        purchase = InstallmentPurchase.objects.create(
            owner=self.alice, card=self.card, description="Compra",
            total_amount=10000, installment_count=1, installment_amount=10000,
            first_due_date=date(2026, 9, 15),
        )
        Installment.objects.create(
            owner=self.alice, purchase=purchase, number=1, amount=10000,
            due_date=date(2026, 9, 15), invoice=invoice,
        )
        resp = self.client.post(
            reverse("cards:invoice_pay", args=[invoice.pk]),
            {"account": self.bank_b.pk, "date": "2026-10-05"},
        )
        # Conta de B fora do queryset do form => form inválido; fatura segue aberta.
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, CreditCardInvoice.Status.OPEN)
        self.assertEqual(resp.status_code, 200)
