"""Testes web do núcleo financeiro (contas, categorias, lançamentos,
transferências e recorrências).

Cobrem CRUD, filtros/paginação e isolamento multiusuário via HTTP, sempre
delegando regras financeiras aos services.
"""

from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import Account, Category, RecurringRule, Transaction

User = get_user_model()


class FinanceWebTestBase(TestCase):
    def setUp(self):
        self.alice = User.objects.create_user(
            username="alice", password="senha123", first_name="Alice"
        )
        self.bob = User.objects.create_user(
            username="bob", password="senha123", first_name="Bob"
        )
        self.login_as(self.alice)

    def login_as(self, user):
        self.client.login(username=user.username, password="senha123")

    def make_account(self, owner=None, name="Conta", **kwargs):
        owner = owner or self.alice
        defaults = {"name": name}
        defaults.update(kwargs)
        return Account.objects.create(owner=owner, **defaults)


class AccountWebTests(FinanceWebTestBase):
    def test_anonymous_redirected(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse("finance:account_list")).status_code, 302)

    def test_create_account(self):
        self.client.post(
            reverse("finance:account_create"),
            {
                "name": "Conta do dia a dia",
                "type": "checking",
                "institution": "Banco Y",
                "initial_balance": "1000,50",
            },
        )
        acc = Account.objects.get(owner=self.alice, name="Conta do dia a dia")
        self.assertEqual(acc.initial_balance, 100050)
        self.assertEqual(acc.type, Account.Type.CHECKING)

    def test_list_isolation(self):
        self.make_account(owner=self.alice, name="Minha")
        self.make_account(owner=self.bob, name="Do Bob")
        resp = self.client.get(reverse("finance:account_list"))
        content = resp.content.decode()
        self.assertIn("Minha", content)
        self.assertNotIn("Do Bob", content)

    def test_detail_other_user_404(self):
        acc = self.make_account(owner=self.bob)
        self.assertEqual(
            self.client.get(reverse("finance:account_detail", args=[acc.pk])).status_code,
            404,
        )

    def test_edit_other_user_404(self):
        acc = self.make_account(owner=self.bob)
        resp = self.client.post(
            reverse("finance:account_edit", args=[acc.pk]),
            {"name": "Ok", "type": "checking", "institution": ""},
        )
        self.assertEqual(resp.status_code, 404)

    def test_archive_and_reactivate(self):
        acc = self.make_account(owner=self.alice)
        self.client.post(reverse("finance:account_archive", args=[acc.pk]))
        acc.refresh_from_db()
        self.assertEqual(acc.status, Account.Status.ARCHIVED)
        self.client.post(reverse("finance:account_reactivate", args=[acc.pk]))
        acc.refresh_from_db()
        self.assertEqual(acc.status, Account.Status.ACTIVE)

    def test_list_splits_active_and_archived_sections(self):
        self.make_account(owner=self.alice, name="Ativa 1")
        self.make_account(owner=self.alice, name="Ativa 2")
        archived = self.make_account(owner=self.alice, name="Arquivada 1")
        archived.status = Account.Status.ARCHIVED
        archived.save()
        resp = self.client.get(reverse("finance:account_list"))
        html = resp.content.decode()
        # As duas seções existem e cada conta aparece na sua seção.
        self.assertIn("Ativas", html)
        self.assertIn("Arquivadas", html)
        self.assertIn("Ativa 1", html)
        self.assertIn("Ativa 2", html)
        self.assertIn("Arquivada 1", html)
        # A arquivada aparece apenas na seção de arquivadas; a ativa não reaparece.
        active_section = html.split("Arquivadas", 1)[0]
        self.assertIn("Ativa 1", active_section)
        self.assertNotIn("Arquivada 1", active_section)


class TransactionWebTests(FinanceWebTestBase):
    def setUp(self):
        super().setUp()
        self.account = self.make_account(owner=self.alice, name="Principal")
        self.cat = Category.objects.create(
            owner=self.alice, name="Alimentação", kind=Category.Kind.EXPENSE
        )

    def test_record_expense(self):
        self.client.post(
            reverse("finance:expense_create"),
            {
                "amount": "89,90",
                "date": "2026-09-01",
                "account": self.account.pk,
                "category": self.cat.pk,
                "description": "Supermercado",
                "notes": "",
            },
        )
        tx = Transaction.objects.get(owner=self.alice, description="Supermercado")
        self.assertEqual(tx.type, Transaction.Type.EXPENSE)
        self.assertEqual(tx.amount, 8990)
        self.assertEqual(tx.account_id, self.account.pk)

    def test_record_income(self):
        self.client.post(
            reverse("finance:income_create"),
            {
                "amount": "2500,00",
                "date": "2026-09-01",
                "account": self.account.pk,
                "category": "",
                "description": "Salário",
                "notes": "",
            },
        )
        tx = Transaction.objects.get(owner=self.alice, description="Salário")
        self.assertEqual(tx.type, Transaction.Type.INCOME)
        self.assertEqual(tx.amount, 250000)

    def test_edit_transaction(self):
        tx = Transaction.objects.create(
            owner=self.alice, type=Transaction.Type.EXPENSE, amount=9000,
            date=date(2026, 9, 1), account=self.account,
        )
        self.client.post(
            reverse("finance:transaction_edit", args=[tx.pk]),
            {
                "amount": "120,00",
                "date": "2026-09-05",
                "account": self.account.pk,
                "category": self.cat.pk,
                "description": "Editada",
                "notes": "",
            },
        )
        tx.refresh_from_db()
        self.assertEqual(tx.amount, 12000)
        self.assertEqual(tx.description, "Editada")

    def test_delete_transaction(self):
        tx = Transaction.objects.create(
            owner=self.alice, type=Transaction.Type.EXPENSE, amount=9000,
            date=date(2026, 9, 1), account=self.account,
        )
        self.client.post(reverse("finance:transaction_delete", args=[tx.pk]))
        self.assertFalse(Transaction.objects.filter(pk=tx.pk).exists())

    def test_edit_other_user_transaction_404(self):
        other_acc = self.make_account(owner=self.bob, name="B")
        tx = Transaction.objects.create(
            owner=self.bob, type=Transaction.Type.EXPENSE, amount=9000,
            date=date(2026, 9, 1), account=other_acc,
        )
        resp = self.client.get(reverse("finance:transaction_edit", args=[tx.pk]))
        self.assertEqual(resp.status_code, 404)

    def test_list_filters_by_type(self):
        Transaction.objects.create(
            owner=self.alice, type=Transaction.Type.INCOME, amount=100,
            date=date(2026, 9, 1), account=self.account,
        )
        Transaction.objects.create(
            owner=self.alice, type=Transaction.Type.EXPENSE, amount=200,
            date=date(2026, 9, 2), account=self.account,
        )
        resp = self.client.get(reverse("finance:transaction_list"), {"type": "income"})
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode()
        self.assertIn("R$ 1,00", content)
        self.assertNotIn("R$ 2,00", content)

    def test_list_search(self):
        Transaction.objects.create(
            owner=self.alice, type=Transaction.Type.EXPENSE, amount=100,
            date=date(2026, 9, 1), account=self.account, description="Mercado A",
        )
        Transaction.objects.create(
            owner=self.alice, type=Transaction.Type.EXPENSE, amount=200,
            date=date(2026, 9, 2), account=self.account, description="Farmácia B",
        )
        resp = self.client.get(reverse("finance:transaction_list"), {"q": "Mercado"})
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode()
        self.assertIn("Mercado A", content)
        self.assertNotIn("Farmácia B", content)


    def test_list_period_filter(self):
        Transaction.objects.create(
            owner=self.alice, type=Transaction.Type.EXPENSE, amount=100,
            date=date(2026, 9, 1), account=self.account, description="Setembro",
        )
        Transaction.objects.create(
            owner=self.alice, type=Transaction.Type.EXPENSE, amount=200,
            date=date(2026, 8, 1), account=self.account, description="Agosto",
        )
        resp = self.client.get(
            reverse("finance:transaction_list"),
            {"from": "2026-09-01", "to": "2026-09-30"},
        )
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode()
        self.assertIn("Setembro", content)
        self.assertNotIn("Agosto", content)

    def test_list_account_filter(self):
        other = self.make_account(owner=self.alice, name="Poupança")
        Transaction.objects.create(
            owner=self.alice, type=Transaction.Type.EXPENSE, amount=100,
            date=date(2026, 9, 1), account=self.account, description="Principal TX",
        )
        Transaction.objects.create(
            owner=self.alice, type=Transaction.Type.EXPENSE, amount=200,
            date=date(2026, 9, 1), account=other, description="Poupança TX",
        )
        resp = self.client.get(reverse("finance:transaction_list"), {"account": other.pk})
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode()
        self.assertIn("Poupança TX", content.replace("&#x27;", "'"))
        self.assertNotIn("Principal TX", content)

    def test_list_category_filter(self):
        other_cat = Category.objects.create(
            owner=self.alice, name="Lazer", kind=Category.Kind.EXPENSE
        )
        Transaction.objects.create(
            owner=self.alice, type=Transaction.Type.EXPENSE, amount=100,
            date=date(2026, 9, 1), account=self.account, category=self.cat,
            description="Comida",
        )
        Transaction.objects.create(
            owner=self.alice, type=Transaction.Type.EXPENSE, amount=200,
            date=date(2026, 9, 1), account=self.account, category=other_cat,
            description="Cinema",
        )
        resp = self.client.get(reverse("finance:transaction_list"), {"category": other_cat.pk})
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode()
        self.assertIn("Cinema", content)
        self.assertNotIn("Comida", content)

    def test_list_isolation_by_user(self):
        Transaction.objects.create(
            owner=self.alice, type=Transaction.Type.EXPENSE, amount=100,
            date=date(2026, 9, 1), account=self.account, description="Minha TX",
        )
        bob_account = self.make_account(owner=self.bob, name="Conta Bob")
        Transaction.objects.create(
            owner=self.bob, type=Transaction.Type.EXPENSE, amount=999,
            date=date(2026, 9, 1), account=bob_account, description="TX do Bob",
        )
        resp = self.client.get(reverse("finance:transaction_list"))
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode()
        self.assertIn("Minha TX", content)
        self.assertNotIn("TX do Bob", content)


class TransferWebTests(FinanceWebTestBase):
    def setUp(self):
        super().setUp()
        self.a = self.make_account(owner=self.alice, name="A")
        self.b = self.make_account(owner=self.alice, name="B")

    def test_create_transfer(self):
        self.client.post(
            reverse("finance:transfer_create"),
            {
                "from_account": self.a.pk,
                "to_account": self.b.pk,
                "amount": "500,00",
                "date": "2026-09-01",
                "description": "Reserva",
            },
        )
        # Duas pernas TRANSFER; patrimônio total invariável.
        legs = Transaction.objects.filter(
            owner=self.alice, type=Transaction.Type.TRANSFER
        )
        self.assertEqual(legs.count(), 2)

    def test_transfer_same_account_rejected(self):
        resp = self.client.post(
            reverse("finance:transfer_create"),
            {
                "from_account": self.a.pk,
                "to_account": self.a.pk,
                "amount": "100,00",
                "date": "2026-09-01",
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            Transaction.objects.filter(owner=self.alice, type=Transaction.Type.TRANSFER).count(),
            0,
        )


class CategoryWebTests(FinanceWebTestBase):
    def test_create_category(self):
        self.client.post(
            reverse("finance:category_create"),
            {"name": "Transporte", "kind": "expense", "parent": ""},
        )
        cat = Category.objects.get(owner=self.alice, name="Transporte")
        self.assertEqual(cat.kind, Category.Kind.EXPENSE)

    def test_edit_other_user_category_404(self):
        cat = Category.objects.create(owner=self.bob, name="Bob")
        resp = self.client.post(
            reverse("finance:category_edit", args=[cat.pk]),
            {"name": "X", "kind": "expense", "parent": ""},
        )
        self.assertEqual(resp.status_code, 404)


class RecurringWebTests(FinanceWebTestBase):
    def setUp(self):
        super().setUp()
        self.account = self.make_account(owner=self.alice, name="Principal")
        self.cat = Category.objects.create(
            owner=self.alice, name="Moradia", kind=Category.Kind.EXPENSE
        )

    def test_create_recurring_expense(self):
        self.client.post(
            reverse("finance:recurring_create"),
            {
                "kind": "expense",
                "title": "Aluguel",
                "amount": "1200,00",
                "frequency": "monthly",
                "interval": "1",
                "account": self.account.pk,
                "category": self.cat.pk,
                "card": "",
                "start_date": "2026-09-01",
                "end_date": "",
                "day_of_month": "5",
                "weekday": "",
            },
        )
        rule = RecurringRule.objects.get(owner=self.alice, title="Aluguel")
        self.assertEqual(rule.amount, 120000)
        self.assertEqual(rule.frequency, RecurringRule.Frequency.MONTHLY)
        self.assertEqual(rule.status, RecurringRule.Status.ACTIVE)

    def test_pause_and_reactivate(self):
        rule = RecurringRule.objects.create(
            owner=self.alice, kind=RecurringRule.Kind.EXPENSE, title="A",
            amount=1000, frequency=RecurringRule.Frequency.MONTHLY,
            start_date=date(2026, 9, 1), account=self.account,
        )
        self.client.post(reverse("finance:recurring_pause", args=[rule.pk]))
        rule.refresh_from_db()
        self.assertEqual(rule.status, RecurringRule.Status.PAUSED)
        self.client.post(reverse("finance:recurring_activate", args=[rule.pk]))
        rule.refresh_from_db()
        self.assertEqual(rule.status, RecurringRule.Status.ACTIVE)

    def test_status_other_user_rule_404(self):
        other_acc = self.make_account(owner=self.bob, name="B")
        rule = RecurringRule.objects.create(
            owner=self.bob, kind=RecurringRule.Kind.EXPENSE, title="B",
            amount=1000, frequency=RecurringRule.Frequency.MONTHLY,
            start_date=date(2026, 9, 1), account=other_acc,
        )
        resp = self.client.post(reverse("finance:recurring_pause", args=[rule.pk]))
        self.assertEqual(resp.status_code, 404)
