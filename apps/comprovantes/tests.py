"""Testes do app comprovantes (organizador de comprovantes e garantias)."""

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from .models import Comprovante

User = get_user_model()

MAX = 2 * 1024 * 1024  # limite de 2 MB


class ComprovantesTestBase(TestCase):
    def setUp(self):
        self.alice = User.objects.create_user(
            username="alice", password="senha123", first_name="Alice"
        )
        self.bob = User.objects.create_user(
            username="bob", password="senha123", first_name="Bob"
        )
        self.client.login(username="alice", password="senha123")

    def _make_file(self, content=b"PDFDATA", name="doc.pdf"):
        return SimpleUploadedFile(name, content, content_type="application/pdf")


class CreateTests(ComprovantesTestBase):
    def test_create_with_valid_file(self):
        resp = self.client.post(
            reverse("comprovantes:create"),
            {
                "title": "Nota da geladeira",
                "kind": "invoice",
                "file": self._make_file(),
            },
        )
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(Comprovante.objects.for_user(self.alice).count(), 1)

    def test_rejects_oversized_file(self):
        big = b"x" * (MAX + 1)
        resp = self.client.post(
            reverse("comprovantes:create"),
            {
                "title": "Grande",
                "kind": "receipt",
                "file": SimpleUploadedFile(
                    "big.pdf", big, content_type="application/pdf"
                ),
            },
        )
        form = resp.context["form"]
        self.assertIn("2 MB", str(form.errors))
        self.assertEqual(Comprovante.objects.for_user(self.alice).count(), 0)

    def test_rejects_unsupported_extension(self):
        resp = self.client.post(
            reverse("comprovantes:create"),
            {
                "title": "Z",
                "kind": "receipt",
                "file": SimpleUploadedFile(
                    "virus.exe", b"MZ", content_type="application/octet-stream"
                ),
            },
        )
        form = resp.context["form"]
        self.assertIn("não suportado", str(form.errors))


class OwnershipTests(ComprovantesTestBase):
    def test_edit_other_users_is_404(self):
        c = Comprovante.objects.create(
            owner=self.bob, title="Do Bob", kind="receipt", file="x/1.pdf"
        )
        resp = self.client.get(reverse("comprovantes:edit", args=[c.pk]))
        self.assertEqual(resp.status_code, 404)


class WebTests(ComprovantesTestBase):
    def test_list_renders(self):
        resp = self.client.get(reverse("comprovantes:list"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Comprovantes e garantias")

    def test_delete_removes(self):
        self.client.post(
            reverse("comprovantes:create"),
            {"title": "N", "kind": "receipt", "file": self._make_file()},
        )
        c = Comprovante.objects.for_user(self.alice).get()
        self.client.post(reverse("comprovantes:delete", args=[c.pk]))
        self.assertEqual(Comprovante.objects.for_user(self.alice).count(), 0)

    def test_requires_auth(self):
        self.client.logout()
        self.assertEqual(
            self.client.get(reverse("comprovantes:list")).status_code, 302
        )
