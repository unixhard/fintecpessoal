"""Testes da camada de serviços da app finance.

Cobrem transações (receita/despesa), transferência (com rollback REAL),
saldos, recorrência (anti-duplicação) e isolamento multiusuário no nível de
serviço.
"""

from datetime import date
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from .models import Account, Category, RecurringRule, Transaction, Transfer
from .services.accounts import create_account
from .services.balances import account_balance, net_worth
from .services.errors import ForbiddenResourceError, InvalidAmountError, InvalidStateError
from .services.recurrences import generate_occurrence
from .services.transactions import (
    delete_transaction,
    record_expense,
    record_income,
    update_transaction,
)
from .services.transfers import transfer_between

User = get_user_model()


class BaseServiceTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="alice", password="x")
        self.other = User.objects.create_user(username="bob", password="y")


class CreateAccountServiceTests(BaseServiceTestCase):
    def test_creates_account_with_owner(self):
        account = create_account(user=self.user, name="Conta Corrente")
        self.assertEqual(account.owner_id, self.user.id)
        self.assertEqual(account.status, Account.Status.ACTIVE)
        self.assertEqual(account.initial_balance, 0)
        self.assertEqual(account.currency, "BRL")

    def test_creates_account_with_initial_balance(self):
        account = create_account(
            user=self.user, name="Poupança", type=Account.Type.SAVINGS,
            initial_balance=100000,
        )
        self.assertEqual(account.initial_balance, 100000)
        self.assertEqual(account.type, Account.Type.SAVINGS)

    def test_rejects_blank_name(self):
        with self.assertRaises(ValueError):
            create_account(user=self.user, name="   ")

    def test_rejects_negative_initial_balance(self):
        with self.assertRaises(InvalidAmountError):
            create_account(user=self.user, name="Conta", initial_balance=-5)


class IncomeServiceTests(BaseServiceTestCase):
    def test_creates_income_transaction(self):
        account = Account.objects.create(owner=self.user, name="Conta")
        tx = record_income(
            user=self.user, account=account, amount=5000,
            date=date(2026, 1, 5), description="Salário",
        )
        tx.refresh_from_db()
        self.assertEqual(tx.type, Transaction.Type.INCOME)
        self.assertEqual(tx.amount, 5000)
        self.assertEqual(tx.owner_id, self.user.id)
        self.assertEqual(tx.account_id, account.id)

    def test_income_with_category(self):
        account = Account.objects.create(owner=self.user, name="Conta")
        category = Category.objects.create(
            owner=self.user, name="Trabalho", kind=Category.Kind.INCOME
        )
        tx = record_income(
            user=self.user, account=account, amount=100,
            date=date(2026, 1, 1), category=category,
        )
        self.assertEqual(tx.category_id, category.id)
        self.assertEqual(tx.owner_id, self.user.id)

    def test_income_rejects_other_users_account(self):
        other_account = Account.objects.create(owner=self.other, name="Do Bob")
        with self.assertRaises(ForbiddenResourceError):
            record_income(
                user=self.user, account=other_account, amount=100,
                date=date(2026, 1, 1),
            )

    def test_income_rejects_non_positive_amount(self):
        account = Account.objects.create(owner=self.user, name="Conta")
        for bad in (0, -5, 2.5, "100"):
            with self.subTest(bad=bad):
                with self.assertRaises(InvalidAmountError):
                    record_income(
                        user=self.user, account=account, amount=bad,
                        date=date(2026, 1, 1),
                    )


class ExpenseServiceTests(BaseServiceTestCase):
    def test_creates_expense_transaction(self):
        account = Account.objects.create(owner=self.user, name="Conta")
        category = Category.objects.create(
            owner=self.user, name="Moradia", kind=Category.Kind.EXPENSE
        )
        tx = record_expense(
            user=self.user, account=account, amount=1500,
            date=date(2026, 1, 3), description="Aluguel", category=category,
        )
        self.assertEqual(tx.type, Transaction.Type.EXPENSE)
        self.assertEqual(tx.category_id, category.id)
        self.assertEqual(tx.owner_id, self.user.id)

    def test_expense_rejects_other_users_category(self):
        account = Account.objects.create(owner=self.user, name="Conta")
        other_cat = Category.objects.create(
            owner=self.other, name="Outro", kind=Category.Kind.EXPENSE
        )
        with self.assertRaises(ForbiddenResourceError):
            record_expense(
                user=self.user, account=account, amount=10,
                date=date(2026, 1, 1), category=other_cat,
            )


class TransferServiceTests(BaseServiceTestCase):
    def setUp(self):
        super().setUp()
        self.a = Account.objects.create(owner=self.user, name="A", initial_balance=50000)
        self.b = Account.objects.create(owner=self.user, name="B")
        self.c = Account.objects.create(owner=self.other, name="C")

    def test_creates_two_transfer_legs(self):
        transfer = transfer_between(
            user=self.user, from_account=self.a, to_account=self.b,
            amount=20000, date=date(2026, 1, 10),
        )
        self.assertEqual(
            Transaction.objects.filter(
                owner=self.user, type=Transaction.Type.TRANSFER
            ).count(),
            2,
        )
        self.assertIsNotNone(transfer.out_transaction)
        self.assertIsNotNone(transfer.in_transaction)
        # Não é receita nem despesa:
        self.assertEqual(
            Transaction.objects.filter(type=Transaction.Type.INCOME).count(), 0
        )
        self.assertEqual(
            Transaction.objects.filter(type=Transaction.Type.EXPENSE).count(), 0
        )

    def test_net_worth_invariant(self):
        before = net_worth(self.user)
        transfer_between(
            user=self.user, from_account=self.a, to_account=self.b,
            amount=15000, date=date(2026, 1, 10),
        )
        after = net_worth(self.user)
        self.assertEqual(before, after)
        self.assertEqual(account_balance(self.a), 35000)
        self.assertEqual(account_balance(self.b), 15000)

    def test_rejects_cross_owner_destination(self):
        with self.assertRaises(ForbiddenResourceError):
            transfer_between(
                user=self.user, from_account=self.a, to_account=self.c,
                amount=100, date=date(2026, 1, 10),
            )

    def test_rejects_same_account(self):
        with self.assertRaises(InvalidAmountError):
            transfer_between(
                user=self.user, from_account=self.a, to_account=self.a,
                amount=100, date=date(2026, 1, 10),
            )

    def test_rejects_non_positive_amount(self):
        with self.assertRaises(InvalidAmountError):
            transfer_between(
                user=self.user, from_account=self.a, to_account=self.b,
                amount=0, date=date(2026, 1, 10),
            )


class TransferRealRollbackTestCase(BaseServiceTestCase):
    """Prova que o rollback é REAL (não apenas mock).

    Executa a operação inteira (services.transfers.transfer_between) com
    ``Transaction.objects.create`` substituído para falhar na SEGUNDA perna
    (após a primeira já ter sido gravada). Verifica que a primeira perna
    também desaparece: transaction.atomic() reverteu tudo.
    """

    def test_first_leg_is_rolled_back_when_second_leg_fails(self):
        a = Account.objects.create(owner=self.user, name="A", initial_balance=50000)
        b = Account.objects.create(owner=self.user, name="B")

        real_create = Transaction.objects.create
        calls = {"n": 0}

        class Boom(Exception):
            pass

        def flaky_create(**kwargs):
            if kwargs.get("type") == Transaction.Type.TRANSFER:
                calls["n"] += 1
                if calls["n"] == 2:
                    raise Boom("falha provocada na segunda perna")
            return real_create(**kwargs)

        with patch(
            "apps.finance.services.transfers.Transaction.objects.create",
            side_effect=flaky_create,
        ):
            with self.assertRaises(Boom):
                transfer_between(
                    user=self.user, from_account=a, to_account=b,
                    amount=1000, date=date(2026, 1, 1),
                )

        # Nenhuma das duas pernas sobreviveu; a transferência não existe.
        self.assertEqual(
            Transaction.objects.filter(
                owner=self.user, type=Transaction.Type.TRANSFER
            ).count(),
            0,
        )
        self.assertEqual(Transfer.objects.for_user(self.user).count(), 0)
        self.assertEqual(account_balance(a), 50000)
        self.assertEqual(account_balance(b), 0)


class BalanceServiceTests(BaseServiceTestCase):
    def test_saldo_reflects_income_expense_and_transfer(self):
        a = Account.objects.create(owner=self.user, name="A", initial_balance=10000)
        b = Account.objects.create(owner=self.user, name="B")
        record_income(user=self.user, account=a, amount=5000, date=date(2026, 1, 1))
        record_expense(user=self.user, account=a, amount=2000, date=date(2026, 1, 2))
        transfer_between(
            user=self.user, from_account=a, to_account=b, amount=3000,
            date=date(2026, 1, 3),
        )
        self.assertEqual(account_balance(a), 10000 + 5000 - 2000 - 3000)
        self.assertEqual(account_balance(b), 3000)
        self.assertEqual(net_worth(self.user), 10000 + 5000 - 2000)


class RecurrenceServiceTests(BaseServiceTestCase):
    def _monthly_rule(self):
        account = Account.objects.create(owner=self.user, name="Conta")
        return RecurringRule.objects.create(
            owner=self.user,
            kind=RecurringRule.Kind.EXPENSE,
            title="Aluguel",
            amount=120000,
            account=account,
            frequency=RecurringRule.Frequency.MONTHLY,
            start_date=date(2026, 1, 10),
            day_of_month=10,
        )

    def test_generates_single_occurrence(self):
        rule = self._monthly_rule()
        tx = generate_occurrence(
            user=self.user, rule=rule, target_date=date(2026, 9, 1)
        )
        self.assertEqual(tx.type, Transaction.Type.EXPENSE)
        self.assertEqual(tx.amount, 120000)
        self.assertEqual(tx.date, date(2026, 9, 10))
        self.assertEqual(tx.recurrence_id, rule.id)

    def test_prevents_duplicate_occurrence(self):
        rule = self._monthly_rule()
        first = generate_occurrence(
            user=self.user, rule=rule, target_date=date(2026, 9, 1)
        )
        second = generate_occurrence(
            user=self.user, rule=rule, target_date=date(2026, 9, 20)
        )
        # Idempotente: mesmo período -> mesma ocorrência, sem duplicar.
        self.assertEqual(first.id, second.id)
        self.assertEqual(
            Transaction.objects.filter(owner=self.user, recurrence=rule).count(), 1
        )

    def test_inactive_rule_is_rejected(self):
        rule = self._monthly_rule()
        rule.status = RecurringRule.Status.PAUSED
        rule.save()
        with self.assertRaises(InvalidStateError):
            generate_occurrence(
                user=self.user, rule=rule, target_date=date(2026, 9, 1)
            )

    def test_other_users_rule_is_rejected(self):
        rule = self._monthly_rule()
        with self.assertRaises(ForbiddenResourceError):
            generate_occurrence(
                user=self.other, rule=rule, target_date=date(2026, 9, 1)
            )


class UniversalEditDeleteTests(BaseServiceTestCase):
    """Controle total: editar/excluir QUALQUER lançamento do usuário."""

    def setUp(self):
        super().setUp()
        self.a = Account.objects.create(owner=self.user, name="A", initial_balance=100000)
        self.b = Account.objects.create(owner=self.user, name="B")
        self.expense_cat = Category.objects.create(
            owner=self.user, name="Comida", kind=Category.Kind.EXPENSE
        )

    def test_edits_income_amount_and_category(self):
        tx = record_income(
            user=self.user, account=self.a, amount=100,
            date=date(2026, 1, 1), description="X",
        )
        category = Category.objects.create(
            owner=self.user, name="Trabalho", kind=Category.Kind.INCOME
        )
        updated = update_transaction(
            user=self.user, transaction=tx, amount=200,
            date=date(2026, 2, 1), description="Y", category=category,
        )
        updated.refresh_from_db()
        self.assertEqual(updated.amount, 200)
        self.assertEqual(updated.date, date(2026, 2, 1))
        self.assertEqual(updated.description, "Y")
        self.assertEqual(updated.category_id, category.id)

    def test_edits_transfer_keeps_both_legs_in_sync(self):
        transfer = transfer_between(
            user=self.user, from_account=self.a, to_account=self.b,
            amount=2000, date=date(2026, 1, 10),
        )
        out_leg = transfer.out_transaction
        update_transaction(
            user=self.user, transaction=out_leg, amount=3500,
            date=date(2026, 3, 15), description="Transfer atualizada",
        )
        transfer.refresh_from_db()
        out_leg.refresh_from_db()
        in_leg = transfer.in_transaction
        in_leg.refresh_from_db()
        self.assertEqual(transfer.amount, 3500)
        self.assertEqual(out_leg.amount, 3500)
        self.assertEqual(in_leg.amount, 3500)
        self.assertEqual(out_leg.date, date(2026, 3, 15))
        self.assertEqual(in_leg.date, date(2026, 3, 15))
        self.assertEqual(out_leg.description, "Transfer atualizada")
        self.assertEqual(in_leg.description, "Transfer atualizada")

    def test_editing_transfer_rejects_swapping_account_of_a_leg(self):
        transfer = transfer_between(
            user=self.user, from_account=self.a, to_account=self.b,
            amount=2000, date=date(2026, 1, 10),
        )
        with self.assertRaises(InvalidStateError):
            update_transaction(
                user=self.user, transaction=transfer.out_transaction,
                account=self.b,
            )

    def test_editing_transfer_rejects_category(self):
        transfer = transfer_between(
            user=self.user, from_account=self.a, to_account=self.b,
            amount=2000, date=date(2026, 1, 10),
        )
        with self.assertRaises(InvalidStateError):
            update_transaction(
                user=self.user, transaction=transfer.out_transaction,
                category=self.expense_cat,
            )

    def test_deletes_transfer_removes_both_legs_and_record(self):
        transfer = transfer_between(
            user=self.user, from_account=self.a, to_account=self.b,
            amount=3000, date=date(2026, 1, 10),
        )
        delete_transaction(user=self.user, transaction=transfer.out_transaction)
        self.assertEqual(
            Transaction.objects.filter(owner=self.user).count(), 0
        )
        self.assertEqual(Transfer.objects.for_user(self.user).count(), 0)
        self.assertEqual(account_balance(self.a), 100000)
        self.assertEqual(account_balance(self.b), 0)

    def test_deletes_transfer_from_inbound_leg(self):
        transfer = transfer_between(
            user=self.user, from_account=self.a, to_account=self.b,
            amount=3000, date=date(2026, 1, 10),
        )
        delete_transaction(user=self.user, transaction=transfer.in_transaction)
        self.assertEqual(
            Transaction.objects.filter(owner=self.user).count(), 0
        )
        self.assertEqual(Transfer.objects.for_user(self.user).count(), 0)

    def test_deletes_invoice_payment_reverses_invoice(self):
        from apps.cards.models import CreditCard, CreditCardInvoice
        from apps.cards.services.invoices import pay_invoice, get_or_create_invoice

        card = CreditCard.objects.create(owner=self.user, name="Visa")
        invoice = get_or_create_invoice(self.user, card, date(2026, 5, 1))
        CreditCardInvoice.objects.filter(pk=invoice.pk).update(
            status="open"
        )
        invoice.refresh_from_db()
        # Parcela para dar valor à fatura.
        from apps.cards.models import Installment, InstallmentPurchase

        purchase = InstallmentPurchase.objects.create(
            owner=self.user, card=card, description="Notebook",
            total_amount=500000, installment_count=1, installment_amount=500000,
            first_due_date=date(2026, 5, 1),
        )
        installment = Installment.objects.create(
            owner=self.user, purchase=purchase, number=1,
            amount=500000, due_date=date(2026, 5, 10),
        )
        invoice = get_or_create_invoice(self.user, card, installment.due_date)
        installment.invoice = invoice
        installment.save()
        invoice.refresh_from_db()
        self.assertEqual(invoice.amount, 500000)

        payment = pay_invoice(
            user=self.user, invoice=invoice, account=self.a,
            date=date(2026, 5, 10),
        )
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, CreditCardInvoice.Status.PAID)

        delete_transaction(user=self.user, transaction=payment)
        invoice.refresh_from_db()
        self.assertNotEqual(invoice.status, CreditCardInvoice.Status.PAID)
        self.assertIsNone(invoice.payment_transaction_id)
        self.assertEqual(
            invoice.installments.filter(
                status=Installment.Status.PENDING
            ).count(),
            1,
        )

    def test_deletes_plain_transaction(self):
        tx = record_expense(
            user=self.user, account=self.a, amount=50,
            date=date(2026, 1, 1), description="Café",
        )
        delete_transaction(user=self.user, transaction=tx)
        self.assertFalse(
            Transaction.objects.filter(owner=self.user).exists()
        )

    def test_rejects_editing_other_users_transaction(self):
        other_account = Account.objects.create(owner=self.other, name="Bob")
        other_tx = record_expense(
            user=self.other, account=other_account, amount=10,
            date=date(2026, 1, 1),
        )
        with self.assertRaises(ForbiddenResourceError):
            update_transaction(
                user=self.user, transaction=other_tx, amount=99,
            )

    def test_rejects_deleting_other_users_transaction(self):
        other_account = Account.objects.create(owner=self.other, name="Bob")
        other_tx = record_expense(
            user=self.other, account=other_account, amount=10,
            date=date(2026, 1, 1),
        )
        with self.assertRaises(ForbiddenResourceError):
            delete_transaction(user=self.user, transaction=other_tx)
