"""Testes da extensão do Motor a cartões/dívidas (Ordem 18 — FASE 8).

Garante que pagamentos de fatura e de dívida ganham snapshot
``TransactionAnalysis.is_movement`` (não vira consumo comum), SEM alterar a
contabilização (número de transações, saldos e tipos permanecem).
"""

from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.cards.models import CreditCard
from apps.cards.services.invoices import pay_invoice
from apps.cards.services.purchases import create_card_purchase
from apps.debts.services.debts import create_debt, record_debt_payment
from apps.finance.models import Account, Transaction, TransactionAnalysis

User = get_user_model()


class CardInvoiceMovementTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="alice", password="x")
        self.bank = Account.objects.create(owner=self.user, name="Banco", initial_balance=1000000)
        self.card = CreditCard.objects.create(
            owner=self.user, name="Cartão", limit=500000,
            payment_account=self.bank, closing_day=10, due_day=5,
        )
        self.purchase = create_card_purchase(
            user=self.user, card=self.card, description="Compra",
            total_amount=30000, installment_count=1, first_due_date=date(2026, 2, 5),
        )
        self.invoice = self.purchase.installments.first().invoice

    def test_pay_invoice_marks_movement_not_consumption(self):
        tx = pay_invoice(user=self.user, invoice=self.invoice, account=self.bank, date=date(2026, 3, 5))
        analysis = TransactionAnalysis.objects.get(transaction=tx)
        self.assertTrue(analysis.is_movement)
        self.assertEqual(analysis.classification_source, TransactionAnalysis.Source.MOVEMENT)
        self.assertIsNone(analysis.category)

    def test_pay_invoice_single_expense_preserved(self):
        pay_invoice(user=self.user, invoice=self.invoice, account=self.bank, date=date(2026, 3, 5))
        # contabilização intacta: apenas UM expense no banco
        self.assertEqual(
            Transaction.objects.filter(type=Transaction.Type.EXPENSE, account=self.bank).count(), 1
        )


class DebtPaymentMovementTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="alice", password="x")
        self.bank = Account.objects.create(owner=self.user, name="Banco", initial_balance=1000000)
        self.debt = create_debt(
            user=self.user, name="Empréstimo", total_amount=50000,
        )

    def test_debt_payment_marks_movement_not_consumption(self):
        tx = record_debt_payment(
            user=self.user, debt=self.debt, account=self.bank, amount=20000,
            date=date(2026, 3, 5),
        )
        analysis = TransactionAnalysis.objects.get(transaction=tx)
        self.assertTrue(analysis.is_movement)
        self.assertEqual(analysis.classification_source, TransactionAnalysis.Source.MOVEMENT)
        self.assertIsNone(analysis.category)

    def test_debt_payment_accounting_preserved(self):
        record_debt_payment(
            user=self.user, debt=self.debt, account=self.bank, amount=20000,
            date=date(2026, 3, 5),
        )
        self.assertEqual(
            Transaction.objects.filter(type=Transaction.Type.EXPENSE, account=self.bank).count(), 1
        )
        self.debt.refresh_from_db()
        self.assertEqual(self.debt.paid_amount, 20000)
        self.assertEqual(self.debt.status, self.debt.Status.ACTIVE)
