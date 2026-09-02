"""Testes da leitura inteligente de comprovantes por IA (feature flag opcional).

Cobrem: fallback quando a chave está ausente (nada quebra), leitura a partir de
um ``pk`` com isolamento multiusuário, leitura a partir de um arquivo de upload,
normalização de valor monetário e validação de upload. A chamada real à API é
sempre mockada com ``@patch`` — os testes rodam offline e sem gastar cotas.
"""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.core.services.ai import AIServiceError

from .models import Comprovante
from .services import UploadError, parse_comprovante_with_ai

User = get_user_model()


class ComprovanteAIServiceTests(TestCase):
    def setUp(self):
        self.alice = User.objects.create_user(
            username="alice", password="senha123", first_name="Alice"
        )
        self.bob = User.objects.create_user(
            username="bob", password="senha123", first_name="Bob"
        )

    def _make_pdf(self, name="nota.pdf", content=b"PDFDATA"):
        return SimpleUploadedFile(name, content, content_type="application/pdf")

    def _make_comprovante(self, user, name="nota.pdf"):
        return Comprovante.objects.create(
            owner=user,
            slug="abc123",
            title="Nota",
            kind=Comprovante.Kind.INVOICE,
            file=self._make_pdf(name=name),
        )

    def test_unavailable_when_key_missing(self):
        with override_settings(GEMINI_API_KEY=""):
            with self.assertRaises(AIServiceError):
                parse_comprovante_with_ai(
                    user=self.alice, comprovante_id_or_file=1
                )

    @patch("apps.comprovantes.services.generate_json")
    def test_parse_by_pk_owned(self, mock_gen):
        mock_gen.return_value = {
            "estabelecimento": "Padaria do Bairro",
            "valor_centavos": 1290,
            "data": "2026-03-14",
            "categoria_sugerida": "Alimentação",
        }
        comp = self._make_comprovante(self.alice)
        with override_settings(GEMINI_API_KEY="fake-key"):
            data = parse_comprovante_with_ai(
                user=self.alice, comprovante_id_or_file=comp.pk
            )
        self.assertTrue(data["ok"])
        self.assertEqual(data["estabelecimento"], "Padaria do Bairro")
        self.assertEqual(data["valor_centavos"], 1290)
        self.assertEqual(data["data"], "2026-03-14")
        self.assertEqual(data["categoria_sugerida"], "Alimentação")

    @patch("apps.comprovantes.services.generate_json")
    def test_parse_by_pk_other_user_blocked(self, mock_gen):
        mock_gen.return_value = {"estabelecimento": "X", "valor_centavos": 1}
        comp = self._make_comprovante(self.alice)
        with override_settings(GEMINI_API_KEY="fake-key"):
            with self.assertRaises(UploadError):
                parse_comprovante_with_ai(
                    user=self.bob, comprovante_id_or_file=comp.pk
                )
        mock_gen.assert_not_called()

    @patch("apps.comprovantes.services.generate_json")
    def test_parse_from_uploaded_file(self, mock_gen):
        mock_gen.return_value = {
            "estabelecimento": "Mercado",
            "valor_centavos": 4750,
            "data": "2026-01-02",
            "categoria_sugerida": "Compras",
        }
        with override_settings(GEMINI_API_KEY="fake-key"):
            data = parse_comprovante_with_ai(
                user=self.alice, comprovante_id_or_file=self._make_pdf()
            )
        self.assertTrue(data["ok"])
        self.assertEqual(data["valor_centavos"], 4750)
        self.assertEqual(data["estabelecimento"], "Mercado")

    @patch("apps.comprovantes.services.generate_json")
    def test_value_normalization_from_real_string(self, mock_gen):
        mock_gen.return_value = {
            "estabelecimento": "Farmácia",
            "valor_centavos": "12,90",
            "data": "",
            "categoria_sugerida": "Saúde",
        }
        with override_settings(GEMINI_API_KEY="fake-key"):
            data = parse_comprovante_with_ai(
                user=self.alice, comprovante_id_or_file=self._make_pdf()
            )
        self.assertEqual(data["valor_centavos"], 1290)

    @patch("apps.comprovantes.services.generate_json")
    def test_rejects_oversized_upload(self, mock_gen):
        big = self._make_pdf(content=b"x" * (2 * 1024 * 1024 + 1))
        with override_settings(GEMINI_API_KEY="fake-key"):
            with self.assertRaises(UploadError):
                parse_comprovante_with_ai(
                    user=self.alice, comprovante_id_or_file=big
                )
        mock_gen.assert_not_called()

    @patch("apps.comprovantes.services.generate_json")
    def test_unknown_pk_raises_upload_error(self, mock_gen):
        with override_settings(GEMINI_API_KEY="fake-key"):
            with self.assertRaises(UploadError):
                parse_comprovante_with_ai(
                    user=self.alice, comprovante_id_or_file=9999
                )
        mock_gen.assert_not_called()


class ComprovanteAIWebTests(TestCase):
    def setUp(self):
        self.alice = User.objects.create_user(
            username="alice", password="senha123", first_name="Alice"
        )
        self.client.login(username="alice", password="senha123")

    def _make_pdf(self, name="nota.pdf", content=b"PDFDATA"):
        return SimpleUploadedFile(name, content, content_type="application/pdf")

    def test_create_form_renders_with_button(self):
        resp = self.client.get(reverse("comprovantes:create"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Preencher com IA")

    def test_parse_ai_endpoint_graceful_without_key(self):
        # Sem GEMINI_API_KEY o endpoint não quebra: devolve ok:False e mensagem.
        resp = self.client.post(
            reverse("comprovantes:parse_ai"), {"file": self._make_pdf()}
        )
        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        self.assertFalse(payload["ok"])
        self.assertIn("manual", payload["message"].lower())

    def test_parse_ai_endpoint_requires_login(self):
        self.client.logout()
        resp = self.client.post(
            reverse("comprovantes:parse_ai"), {"file": self._make_pdf()}
        )
        self.assertEqual(resp.status_code, 302)

    @patch("apps.comprovantes.services.generate_json")
    def test_parse_ai_endpoint_success(self, mock_gen):
        mock_gen.return_value = {
            "estabelecimento": "Padaria do Bairro",
            "valor_centavos": 1290,
            "data": "2026-03-14",
            "categoria_sugerida": "Alimentação",
        }
        with override_settings(GEMINI_API_KEY="fake-key"):
            resp = self.client.post(
                reverse("comprovantes:parse_ai"), {"file": self._make_pdf()}
            )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["estabelecimento"], "Padaria do Bairro")
        self.assertEqual(data["valor_centavos"], 1290)
