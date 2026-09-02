"""Testes da camada de serviços de dívidas (Debt).

Cobrem criação, atualização, exclusão, pagamento (que gera UMA Transaction.
EXPENSE real e acumula em paid_amount, sem contabilidade paralela), recusa de
pagamento acima do saldo restante/em dívida quitada, auto-marcação de PAID_OFF
e transições de status — sempre com ownership validado.
"""

from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.finance.models import Account, Transaction
from apps.finance.services.errors import (
    ForbiddenResourceError, InvalidAmountError, InvalidStateError,
)

from .models import Debt
from .services.debts import (
    create_debt,
    delete_debt,
    get_debt,
    get_debt_progress,
    get_debt_summary,
    record_debt_payment,
    set_debt_status,
    update_debt,
)

User = get_user_model()


class DebtServiceBase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="alice", password="x")
        self.other = User.objects.create_user(username="bob", password="y")
        self.account = Account.objects.create(
            owner=self.user, name="Conta", initial_balance=1000000
        )
        self.other_account = Account.objects.create(owner=self.other, name="Conta B")


class DebtCreateTests(DebtServiceBase):
    def test_creates_active_debt(self):
        debt = create_debt(user=self.user, name="Empréstimo", total_amount=50000)
        self.assertEqual(debt.owner_id, self.user.id)
        self.assertEqual(debt.status, Debt.Status.ACTIVE)
        self.assertEqual(debt.paid_amount, 0)

    def test_rejects_non_positive_total(self):
        with self.assertRaises(InvalidAmountError):
            create_debt(user=self.user, name="X", total_amount=0)
        with self.assertRaises(InvalidAmountError):
            create_debt(user=self.user, name="X", total_amount=-1)

    def test_rejects_paid_greater_than_total(self):
        with self.assertRaises(InvalidAmountError):
            create_debt(user=self.user, name="X", total_amount=100, paid_amount=200)

    def test_fully_paid_starts_paid_off(self):
        debt = create_debt(user=self.user, name="X", total_amount=100, paid_amount=100)
        self.assertEqual(debt.status, Debt.Status.PAID_OFF)

    def test_rejects_blank_name(self):
        with self.assertRaises(ValueError):
            create_debt(user=self.user, name="   ", total_amount=100)


class DebtUpdateDeleteTests(DebtServiceBase):
    def setUp(self):
        super().setUp()
        self.debt = create_debt(user=self.user, name="Empréstimo", total_amount=50000)

    def test_update_other_users_debt_rejected(self):
        with self.assertRaises(ForbiddenResourceError):
            update_debt(user=self.other, debt=self.debt, name="X")

    def test_get_other_users_debt_rejected(self):
        with self.assertRaises(ForbiddenResourceError):
            get_debt(user=self.other, debt_id=self.debt.pk)

    def test_delete_other_users_debt_rejected(self):
        with self.assertRaises(ForbiddenResourceError):
            delete_debt(user=self.other, debt=self.debt)


class DebtPaymentTests(DebtServiceBase):
    def setUp(self):
        super().setUp()
        self.debt = create_debt(user=self.user, name="Empréstimo", total_amount=10000)

    def test_payment_creates_single_expense_and_accumulates(self):
        tx = record_debt_payment(
            user=self.user, debt=self.debt, account=self.account,
            amount=4000, date=date(2026, 9, 10),
        )
        self.debt.refresh_from_db()
        self.assertEqual(self.debt.paid_amount, 4000)
        self.assertEqual(tx.type, Transaction.Type.EXPENSE)
        self.assertEqual(tx.amount, 4000)
        # Apenas essa transação de despesa foi criada.
        self.assertEqual(
            Transaction.objects.filter(owner=self.user, type=Transaction.Type.EXPENSE).count(),
            1,
        )

    def test_payment_marks_paid_off_when_settled(self):
        record_debt_payment(
            user=self.user, debt=self.debt, account=self.account,
            amount=10000, date=date(2026, 9, 10),
        )
        self.debt.refresh_from_db()
        self.assertEqual(self.debt.paid_amount, 10000)
        self.assertEqual(self.debt.status, Debt.Status.PAID_OFF)

    def test_rejects_overpayment(self):
        with self.assertRaises(InvalidAmountError):
            record_debt_payment(
                user=self.user, debt=self.debt, account=self.account,
                amount=15000, date=date(2026, 9, 10),
            )

    def test_rejects_payment_on_paid_off_debt(self):
        record_debt_payment(
            user=self.user, debt=self.debt, account=self.account,
            amount=10000, date=date(2026, 9, 10),
        )
        with self.assertRaises(InvalidStateError):
            record_debt_payment(
                user=self.user, debt=self.debt, account=self.account,
                amount=1, date=date(2026, 9, 11),
            )

    def test_rejects_payment_with_other_users_account(self):
        with self.assertRaises(ForbiddenResourceError):
            record_debt_payment(
                user=self.user, debt=self.debt, account=self.other_account,
                amount=100, date=date(2026, 9, 10),
            )

    def test_rejects_payment_on_other_users_debt(self):
        other_debt = create_debt(user=self.other, name="Do Bob", total_amount=100)
        with self.assertRaises(ForbiddenResourceError):
            record_debt_payment(
                user=self.user, debt=other_debt, account=self.account,
                amount=100, date=date(2026, 9, 10),
            )

    def test_rejects_non_positive_amount(self):
        with self.assertRaises(InvalidAmountError):
            record_debt_payment(
                user=self.user, debt=self.debt, account=self.account,
                amount=0, date=date(2026, 9, 10),
            )


class DebtStatusTests(DebtServiceBase):
    def setUp(self):
        super().setUp()
        self.debt = create_debt(user=self.user, name="Empréstimo", total_amount=10000)

    def test_default_reactivate_archive(self):
        set_debt_status(user=self.user, debt=self.debt, status=Debt.Status.DEFAULTED)
        self.debt.refresh_from_db()
        self.assertEqual(self.debt.status, Debt.Status.DEFAULTED)

        set_debt_status(user=self.user, debt=self.debt, status=Debt.Status.ACTIVE)
        self.debt.refresh_from_db()
        self.assertEqual(self.debt.status, Debt.Status.ACTIVE)

        set_debt_status(user=self.user, debt=self.debt, status=Debt.Status.ARCHIVED)
        self.debt.refresh_from_db()
        self.assertEqual(self.debt.status, Debt.Status.ARCHIVED)

    def test_cannot_manually_mark_paid_off(self):
        with self.assertRaises(InvalidStateError):
            set_debt_status(user=self.user, debt=self.debt, status=Debt.Status.PAID_OFF)

    def test_cannot_reclassify_paid_off_debt(self):
        record_debt_payment(
            user=self.user, debt=self.debt, account=self.account,
            amount=10000, date=date(2026, 9, 10),
        )
        with self.assertRaises(InvalidStateError):
            set_debt_status(user=self.user, debt=self.debt, status=Debt.Status.ACTIVE)


class DebtProgressSummaryTests(DebtServiceBase):
    def test_progress_percent(self):
        debt = create_debt(user=self.user, name="X", total_amount=10000, paid_amount=2500)
        p = get_debt_progress(user=self.user, debt=debt)
        self.assertEqual(p["remaining_amount"], 7500)
        self.assertEqual(p["percent"], 25)

    def test_empty_summary(self):
        s = get_debt_summary(user=self.user)
        self.assertEqual(s["total_remaining"], 0)
        self.assertEqual(s["debts"], [])

    def test_summary_remaining_total(self):
        create_debt(user=self.user, name="A", total_amount=10000, paid_amount=2000)
        create_debt(user=self.user, name="B", total_amount=5000)
        s = get_debt_summary(user=self.user)
        self.assertEqual(s["total_amount"], 15000)
        self.assertEqual(s["paid_amount"], 2000)
        self.assertEqual(s["total_remaining"], 13000)
