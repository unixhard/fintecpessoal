"""Testes do app cards: cartão, parcelamento e faturas."""

from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.finance.models import Account, Transaction

from .models import CreditCard, CreditCardInvoice, Installment, InstallmentPurchase

User = get_user_model()


class CardPurchaseTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="alice", password="x")
        self.bank = Account.objects.create(
            owner=self.user, name="Banco", initial_balance=100000
        )
        self.card = CreditCard.objects.create(
            owner=self.user, name="Cartão", limit=500000,
            payment_account=self.bank, closing_day=20, due_day=5,
        )

    def test_card_purchase_does_not_withdraw_from_bank_immediately(self):
        purchase = InstallmentPurchase.objects.create(
            owner=self.user,
            card=self.card,
            description="Notebook",
            total_amount=120000,
            installment_count=12,
            installment_amount=10000,
            first_due_date=date(2026, 2, 10),
        )
        purchase.generate_installments()

        # Nenhuma transação é criada e o saldo do banco permanece intacto.
        self.assertEqual(Transaction.objects.filter(owner=self.user).count(), 0)
        self.assertEqual(self.bank.transactions.count(), 0)
        self.assertEqual(self.bank.initial_balance, 100000)

    def test_twelve_installments_have_correct_relationship(self):
        purchase = InstallmentPurchase.objects.create(
            owner=self.user, card=self.card, description="Compra",
            total_amount=120000, installment_count=12,
            installment_amount=10000, first_due_date=date(2026, 2, 10),
        )
        insts = list(purchase.generate_installments())

        self.assertEqual(len(insts), 12)
        self.assertEqual([i.number for i in insts], list(range(1, 13)))
        self.assertTrue(all(i.owner_id == self.user.id for i in insts))
        self.assertTrue(all(i.status == Installment.Status.PENDING for i in insts))
        # Relacionamento correto:
        self.assertTrue(all(i.purchase_id == purchase.id for i in insts))
        self.assertEqual(sum(i.amount for i in insts), purchase.total_amount)
        self.assertEqual(insts[0].due_date, date(2026, 2, 10))
        self.assertEqual(insts[1].due_date, date(2026, 3, 10))

    def test_rounding_absorbed_by_last_installment(self):
        purchase = InstallmentPurchase.objects.create(
            owner=self.user, card=self.card, description="3x",
            total_amount=1000, installment_count=3,
            installment_amount=333, first_due_date=date(2026, 2, 10),
        )
        insts = list(purchase.generate_installments())
        self.assertEqual([i.amount for i in insts], [333, 333, 334])
        self.assertEqual(sum(i.amount for i in insts), 1000)

    def test_installment_cannot_belong_to_other_users_purchase(self):
        other = User.objects.create_user(username="bob", password="y")
        other_card = CreditCard.objects.create(owner=other, name="outro")
        purchase = InstallmentPurchase.objects.create(
            owner=other, card=other_card, description="X",
            total_amount=1000, installment_count=2,
            installment_amount=500, first_due_date=date(2026, 2, 10),
        )
        inst = Installment(owner=self.user, purchase=purchase, number=1,
                           amount=500, due_date=date(2026, 2, 10))
        from django.core.exceptions import ValidationError

        with self.assertRaises(ValidationError):
            inst.save()


class InvoiceTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="alice", password="x")
        self.bank = Account.objects.create(owner=self.user, name="Banco")
        self.card = CreditCard.objects.create(owner=self.user, name="Cartão")

    def test_invoice_amount_is_derived_from_installments(self):
        invoice = CreditCardInvoice.objects.create(
            owner=self.user, card=self.card,
            period_start=date(2026, 2, 1), period_end=date(2026, 2, 28),
            closing_date=date(2026, 2, 20), due_date=date(2026, 3, 5),
        )
        purchase = InstallmentPurchase.objects.create(
            owner=self.user, card=self.card, description="1x10k",
            total_amount=20000, installment_count=2,
            installment_amount=10000, first_due_date=date(2026, 2, 10),
        )
        installments = list(purchase.generate_installments())
        for inst in installments:
            inst.invoice = invoice
            inst.save()

        self.assertEqual(invoice.amount, 20000)

    def test_invoice_requires_same_owner_card(self):
        other = User.objects.create_user(username="bob", password="y")
        other_card = CreditCard.objects.create(owner=other, name="outro")
        from django.core.exceptions import ValidationError

        invoice = CreditCardInvoice(
            owner=self.user, card=other_card,
            period_start=date(2026, 2, 1), period_end=date(2026, 2, 28),
            closing_date=date(2026, 2, 20), due_date=date(2026, 3, 5),
        )
        with self.assertRaises(ValidationError):
            invoice.save()
