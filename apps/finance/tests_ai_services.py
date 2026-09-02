"""Testes da sugestão de categoria por IA (feature flag opcional).

Cobrem: fallback quando a chave está ausente (retorna ``None``), match contra
categorias reais do usuário, isolamento multiusuário (nunca sugere categoria de
outro usuário), falha da API (``AIServiceError`` vira ``None``). A chamada à IA
é sempre mockada com ``@patch`` — testes offline, sem gastar cotas.
"""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from apps.core.services.ai import AIServiceError

from .models import Category
from .services.ai_suggestions import suggest_category_with_ai

User = get_user_model()


class SuggestCategoryAIServiceTests(TestCase):
    def setUp(self):
        self.alice = User.objects.create_user(username="alice", password="x")
        self.bob = User.objects.create_user(username="bob", password="y")

    def _category(self, user, name, kind=Category.Kind.EXPENSE):
        return Category.objects.create(owner=user, name=name, kind=kind)

    def test_none_when_no_key(self):
        with override_settings(GEMINI_API_KEY=""):
            result = suggest_category_with_ai(
                user=self.alice, descricao="uber"
            )
        self.assertIsNone(result)

    def test_none_when_blank_description(self):
        with override_settings(GEMINI_API_KEY="fake-key"):
            result = suggest_category_with_ai(
                user=self.alice, descricao="   "
            )
        self.assertIsNone(result)

    @patch("apps.finance.services.ai_suggestions.generate_json")
    def test_returns_owned_category(self, mock_gen):
        transport = self._category(self.alice, "Transporte")
        mock_gen.return_value = {"categoria": "Transporte"}
        with override_settings(GEMINI_API_KEY="fake-key"):
            result = suggest_category_with_ai(
                user=self.alice, descricao="corrida de app"
            )
        self.assertIsNotNone(result)
        self.assertEqual(result.pk, transport.pk)
        self.assertEqual(result.owner_id, self.alice.id)

    @patch("apps.finance.services.ai_suggestions.generate_json")
    def test_never_suggests_other_users_category(self, mock_gen):
        self._category(self.bob, "Transporte")
        self._category(self.alice, "Alimentação")
        mock_gen.return_value = {"categoria": "Transporte"}
        with override_settings(GEMINI_API_KEY="fake-key"):
            result = suggest_category_with_ai(
                user=self.alice, descricao="corrida de app"
            )
        self.assertIsNone(result)

    @patch("apps.finance.services.ai_suggestions.generate_json")
    def test_respects_kind_filter(self, mock_gen):
        self._category(self.alice, "Salário", kind=Category.Kind.INCOME)
        mock_gen.return_value = {"categoria": "Salário"}
        # O usuário não tem categorias de despesa -> nem chama a IA
        with override_settings(GEMINI_API_KEY="fake-key"):
            result = suggest_category_with_ai(
                user=self.alice, descricao="salário", kind=Category.Kind.EXPENSE
            )
        self.assertIsNone(result)
        mock_gen.assert_not_called()

    @patch("apps.finance.services.ai_suggestions.generate_json")
    def test_api_error_falls_back_to_none(self, mock_gen):
        self._category(self.alice, "Saúde")
        mock_gen.side_effect = AIServiceError("sem internet")
        with override_settings(GEMINI_API_KEY="fake-key"):
            result = suggest_category_with_ai(
                user=self.alice, descricao="farmácia"
            )
        self.assertIsNone(result)

    @patch("apps.finance.services.ai_suggestions.generate_json")
    def test_empty_suggestion_returns_none(self, mock_gen):
        self._category(self.alice, "Saúde")
        mock_gen.return_value = {"categoria": ""}
        with override_settings(GEMINI_API_KEY="fake-key"):
            result = suggest_category_with_ai(
                user=self.alice, descricao="farmácia"
            )
        self.assertIsNone(result)
