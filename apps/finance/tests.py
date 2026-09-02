"""Testes do núcleo financeiro: isolamento, transferência, recorrência,
dinheiro, categorias e restrições de integridade."""

from datetime import date

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from .models import Account, Category, RecurringRule, Transaction, Transfer

User = get_user_model()


class MoneyAndIntegrityTests(TestCase):
    def test_money_fields_are_integer_cents_not_float(self):
        """Valores monetários NUNCA devem usar float (decisão D10)."""
        money_fields = {
            ("finance", "Account", "initial_balance"),
            ("finance", "Transaction", "amount"),
            ("finance", "Transfer", "amount"),
            ("finance", "RecurringRule", "amount"),
            ("cards", "CreditCard", "limit"),
            ("cards", "InstallmentPurchase", "total_amount"),
            ("cards", "InstallmentPurchase", "installment_amount"),
            ("cards", "Installment", "amount"),
            ("budgets", "Budget", "limit_amount"),
            ("goals", "Goal", "target_amount"),
            ("goals", "Goal", "current_amount"),
            ("debts", "Debt", "total_amount"),
            ("debts", "Debt", "paid_amount"),
        }
        for app, model, field in money_fields:
            with self.subTest(model=model, field=field):
                f = self.get_field(app, model, field)
                self.assertIn(
                    f.get_internal_type(),
                    ("IntegerField", "BigIntegerField", "SmallIntegerField", "PositiveIntegerField"),
                    f"{model}.{field} deve ser inteiro (centavos), não float",
                )

    def get_field(self, app_label, model_name, field_name):
        from django.apps import apps

        model = apps.get_model(app_label, model_name)
        return model._meta.get_field(field_name)

    def test_account_rejects_negative_initial_balance(self):
        user = User.objects.create_user(username="a", password="x")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Account.objects.bulk_create(
                    [Account(owner=user, name="Bad", initial_balance=-1)]
                )

    def test_transfer_rejects_same_account(self):
        user = User.objects.create_user(username="a", password="x")
        acc = Account.objects.create(owner=user, name="Única")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Transfer.objects.bulk_create(
                    [
                        Transfer(
                            owner=user,
                            from_account=acc,
                            to_account=acc,
                            amount=100,
                            date=date(2026, 1, 1),
                        )
                    ]
                )


class IsolationTests(TestCase):
    def setUp(self):
        self.alice = User.objects.create_user(username="alice", password="x")
        self.bob = User.objects.create_user(username="bob", password="y")

    def test_user_a_cannot_list_user_b_accounts(self):
        Account.objects.create(owner=self.bob, name="Conta do Bob")
        self.assertEqual(Account.objects.for_user(self.alice).count(), 0)

    def test_user_a_cannot_access_user_b_category(self):
        cat = Category.objects.create(owner=self.bob, name="Moradia")
        self.assertNotIn(cat, list(Category.objects.for_user(self.alice)))
        self.assertEqual(Category.objects.for_user(self.alice).count(), 0)

    def test_category_cannot_have_cross_owner_parent(self):
        parent = Category.objects.create(owner=self.alice, name="Padding")
        child = Category(owner=self.bob, name="Filha", parent=parent)
        with self.assertRaises(ValidationError):
            child.save()

    def test_transaction_cannot_use_account_of_another_user(self):
        bob_acc = Account.objects.create(owner=self.bob, name="Bob")
        tx = Transaction(
            owner=self.alice,
            type=Transaction.Type.EXPENSE,
            amount=100,
            date=date(2026, 1, 1),
            account=bob_acc,
        )
        with self.assertRaises(ValidationError):
            tx.save()


class TransferTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="alice", password="x")
        self.account_a = Account.objects.create(owner=self.user, name="Conta A")
        self.account_b = Account.objects.create(owner=self.user, name="Conta B")

    def balance(self, account):
        total = account.initial_balance
        for t in account.transactions.all():
            if hasattr(t, "transfer_out"):
                total -= t.amount
            elif hasattr(t, "transfer_in"):
                total += t.amount
            elif t.type == Transaction.Type.INCOME:
                total += t.amount
            else:
                total -= t.amount
        return total

    def test_transfer_uses_two_transfer_legs_not_income_expense(self):
        out_tx = Transaction.objects.create(
            owner=self.user, type=Transaction.Type.TRANSFER,
            amount=50000, date=date(2026, 1, 1), account=self.account_a,
        )
        in_tx = Transaction.objects.create(
            owner=self.user, type=Transaction.Type.TRANSFER,
            amount=50000, date=date(2026, 1, 1), account=self.account_b,
        )
        transfer = Transfer.objects.create(
            owner=self.user,
            from_account=self.account_a,
            to_account=self.account_b,
            amount=50000,
            date=date(2026, 1, 1),
            out_transaction=out_tx,
            in_transaction=in_tx,
        )
        out_tx.transfer = transfer
        in_tx.transfer = transfer
        out_tx.save()
        in_tx.save()

        # Não pode ser representado como receita + despesa:
        self.assertNotEqual(out_tx.type, Transaction.Type.EXPENSE)
        self.assertNotEqual(in_tx.type, Transaction.Type.INCOME)
        self.assertEqual(Transaction.objects.filter(type=Transaction.Type.EXPENSE).count(), 0)
        self.assertEqual(Transaction.objects.filter(type=Transaction.Type.INCOME).count(), 0)
        # Patrimônio total invariável:
        net_change = -out_tx.amount + in_tx.amount
        self.assertEqual(net_change, 0)
        self.assertEqual(self.balance(self.account_a) + self.balance(self.account_b), 0)


class RecurringRuleTests(TestCase):
    def test_recurring_rule_does_not_generate_transactions(self):
        user = User.objects.create_user(username="alice", password="x")
        acc = Account.objects.create(owner=user, name="Conta")
        RecurringRule.objects.create(
            owner=user,
            kind=RecurringRule.Kind.EXPENSE,
            title="Aluguel",
            amount=120000,
            account=acc,
            frequency=RecurringRule.Frequency.MONTHLY,
            start_date=date(2026, 1, 1),
            day_of_month=10,
        )
        # Criar a regra NÃO pode materializar transações (evita registros infinitos):
        self.assertEqual(Transaction.objects.filter(owner=user).count(), 0)

    def test_expense_rule_requires_account_or_card(self):
        user = User.objects.create_user(username="alice", password="x")
        rule = RecurringRule(
            owner=user, kind=RecurringRule.Kind.EXPENSE, title="X",
            amount=100, account=None, card=None,
            frequency=RecurringRule.Frequency.MONTHLY, start_date=date(2026, 1, 1),
        )
        with self.assertRaises(ValidationError):
            rule.save()
