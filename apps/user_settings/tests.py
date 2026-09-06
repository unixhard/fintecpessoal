"""Testes do app user_settings — backup/export, restore, wipe e views."""

import json
from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.finance.models import Account, Category, Transaction

from .services import (
    delete_account,
    export_user_data,
    restore_user_data,
    wipe_user_data,
)

User = get_user_model()


def make_user(username="alice", password="senha123"):
    return User.objects.create_user(username=username, password=password)


class BackupServiceTests(TestCase):
    def setUp(self):
        self.user = make_user()

    def test_export_contains_own_data(self):
        acc = Account.objects.create(owner=self.user, name="Nubank", initial_balance=1000)
        cat = Category.objects.create(
            owner=self.user, name="Alimentação", kind=Category.Kind.EXPENSE
        )
        Transaction.objects.create(
            owner=self.user, account=acc, category=cat, date=date(2026, 1, 10),
            description="Supermercado", amount=15000,
            type=Transaction.Type.EXPENSE,
        )
        data = export_user_data(self.user)
        self.assertEqual(data["_meta"]["username"], "alice")
        self.assertEqual(
            len(data["finance.account"]), 1,
            "Export deve conter a conta do usuário",
        )
        self.assertEqual(
            len(data["finance.transaction"]), 1,
            "Export deve conter a transação do usuário",
        )
        self.assertEqual(data["finance.transaction"][0]["amount"], 15000)

    def test_export_does_not_leak_other_user_data(self):
        other = make_user("bob")
        Account.objects.create(owner=other, name="Inter", initial_balance=500)
        Account.objects.create(owner=self.user, name="Nubank", initial_balance=1000)
        data = export_user_data(self.user)
        names = [a["name"] for a in data.get("finance.account", [])]
        self.assertIn("Nubank", names)
        self.assertNotIn("Inter", names)

    def test_restore_creates_new_records_and_maps_fk(self):
        acc = Account.objects.create(owner=self.user, name="Nubank", initial_balance=1000)
        cat = Category.objects.create(
            owner=self.user, name="Alimentação", kind=Category.Kind.EXPENSE
        )
        Transaction.objects.create(
            owner=self.user, account=acc, category=cat, date=date(2026, 1, 11),
            description="Mercado", amount=5000, type=Transaction.Type.EXPENSE,
        )
        data = export_user_data(self.user)

        # Restaura para um usuário NOVO (dados nulos)
        other = make_user("bob")
        report = restore_user_data(other, data)
        self.assertGreaterEqual(report["restored"], 2)

        # A transação restaurada deve referenciar a conta restaurada (FK mapeada)
        txn = Transaction.objects.filter(owner=other).select_related("account").first()
        self.assertIsNotNone(txn)
        self.assertEqual(txn.account.owner, other)

    def test_restore_rejects_invalid_format(self):
        with self.assertRaises(ValueError):
            restore_user_data(self.user, ["not", "a", "dict"])

    def test_restore_is_safe_on_duplicates(self):
        acc = Account.objects.create(owner=self.user, name="Conta", initial_balance=100)
        data = export_user_data(self.user)

        # Restaurar para o MESMO usuário que já tem a conta → conta duplicada criada
        # (restore não sobrescreve, cria novo — não deve quebrar)
        report = restore_user_data(self.user, data)
        self.assertEqual(Account.objects.filter(owner=self.user).count(), 2)
        self.assertGreaterEqual(report["restored"], 1)


class WipeServiceTests(TestCase):
    def test_wipe_removes_data_keeps_account(self):
        user = make_user()
        Account.objects.create(owner=user, name="Conta", initial_balance=100)
        Category.objects.create(
            owner=user, name="Categoria", kind=Category.Kind.EXPENSE
        )
        report = wipe_user_data(user)
        self.assertTrue(any("finance.account" in k for k in report))
        self.assertEqual(Account.objects.filter(owner=user).count(), 0)
        self.assertTrue(User.objects.filter(pk=user.pk).exists())

    def test_delete_account_removes_user(self):
        user = make_user()
        Account.objects.create(owner=user, name="Conta", initial_balance=100)
        delete_account(user)
        self.assertFalse(User.objects.filter(pk=user.pk).exists())


class SettingsViewsTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.client.login(username="alice", password="senha123")

    def test_index_requires_login(self):
        self.client.logout()
        resp = self.client.get(reverse("settings:index"))
        self.assertEqual(resp.status_code, 302)

    def test_index_renders(self):
        resp = self.client.get(reverse("settings:index"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Configurações")

    def test_profile_update(self):
        resp = self.client.post(reverse("settings:profile"), {
            "display_name": "Alice Financeira",
            "first_name": "Alice",
            "last_name": "Silva",
            "email": "alice@example.com",
            "default_account": "",
        })
        self.assertEqual(resp.status_code, 302)
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, "Alice")
        self.assertEqual(self.user.profile.display_name, "Alice Financeira")

    def test_password_change(self):
        resp = self.client.post(reverse("settings:password"), {
            "current_password": "senha123",
            "new_password": "nova-senha-456",
            "new_password_confirm": "nova-senha-456",
        })
        self.assertEqual(resp.status_code, 302)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("nova-senha-456"))

    def test_password_change_wrong_current(self):
        resp = self.client.post(reverse("settings:password"), {
            "current_password": "errada",
            "new_password": "nova-senha-456",
            "new_password_confirm": "nova-senha-456",
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Senha atual incorreta")

    def test_export_download(self):
        resp = self.client.get(reverse("settings:backup_export"))
        self.assertEqual(resp.status_code, 200)
        self.assertIn("application/json", resp["Content-Type"])
        payload = json.loads(resp.content)
        self.assertEqual(payload["_meta"]["username"], "alice")

    def test_restore_upload(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        Account.objects.create(owner=self.user, name="Original", initial_balance=100)
        data = export_user_data(self.user)
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        upload = SimpleUploadedFile("backup.json", payload, content_type="application/json")
        resp = self.client.post(reverse("settings:backup_restore"), {"backup_file": upload})
        self.assertEqual(resp.status_code, 302)
        # As contas do backup foram recriadas (novas).
        self.assertGreaterEqual(Account.objects.filter(owner=self.user).count(), 2)

    def test_wipe_requires_confirm(self):
        resp = self.client.post(reverse("settings:wipe"), {"confirm_text": "errado"})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "APAGAR")

    def test_wipe_confirmed(self):
        Account.objects.create(owner=self.user, name="Conta", initial_balance=100)
        resp = self.client.post(reverse("settings:wipe"), {"confirm_text": "APAGAR"})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(Account.objects.filter(owner=self.user).count(), 0)

    def test_delete_account_requires_confirmation(self):
        resp = self.client.post(reverse("settings:delete_account"), {
            "confirm_text": "DELETAR CONTA",
            "password": "senha123",
        })
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(User.objects.filter(pk=self.user.pk).exists())
