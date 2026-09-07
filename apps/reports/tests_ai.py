"""Testes do Relatório de Análise IA (auditor de bolso).

Cobrem: cooldown (configurável), isolamento por usuário, fallback gracioso sem IA
(sem quebrar, sem consumir o limite), geração por IA (mockada — offline), e a
renderização leve de Markdown.
"""

from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.core.services.ai import AIServiceError

from .models import AIReport
from .services import (
    build_manual_report,
    can_generate,
    next_available_date,
    render_markdown,
)

User = get_user_model()


def _make_user(username):
    return User.objects.create_user(username=username, password="x123")


class AIReportServiceTests(TestCase):
    def setUp(self):
        self.alice = _make_user("alice")
        self.bob = _make_user("bob")

    def _report(self, user, *, days_ago=0, via_ai=True):
        r = AIReport.objects.create(
            owner=user, content="## Visão global", summary="Resumo", via_ai=via_ai
        )
        if days_ago:
            AIReport.objects.filter(pk=r.pk).update(
                generated_at=timezone.now() - timedelta(days=days_ago)
            )
            r.refresh_from_db()
        return r

    def test_no_report_can_generate(self):
        self.assertTrue(can_generate(self.alice))
        self.assertEqual(next_available_date(self.alice), timezone.localdate())

    def test_fresh_report_blocks_within_cooldown(self):
        self._report(self.alice)
        self.assertFalse(can_generate(self.alice))
        self.assertEqual(
            next_available_date(self.alice), timezone.localdate() + timedelta(days=3)
        )

    def test_old_report_allows_generation(self):
        self._report(self.alice, days_ago=4)
        self.assertTrue(can_generate(self.alice))

    def test_cooldown_isolated_per_user(self):
        self._report(self.bob)
        self.assertTrue(can_generate(self.alice))

    def test_render_markdown_basic(self):
        html = render_markdown("## Título\n\n- item um\n- item dois\n")
        self.assertIn("<h3>Título</h3>", html)
        self.assertIn("<ul>", html)
        self.assertIn("<li>item um</li>", html)

    def test_render_markdown_escapes_html(self):
        html = render_markdown("ola <script>alert(1)</script>")
        self.assertIn("&lt;script&gt;", html)
        self.assertNotIn("<script>alert", html)

    def test_build_manual_report_string(self):
        text = build_manual_report(self.alice)
        self.assertIsInstance(text, str)
        self.assertIn("## 📋 Visão geral", text)


@override_settings(GEMINI_API_KEY="fake-key")
class AIReportGenerationTests(TestCase):
    def setUp(self):
        self.alice = _make_user("alice")
        self.client.login(username="alice", password="x123")

    @patch("apps.reports.services.generate_text")
    def test_generate_creates_report(self, mock_gen):
        mock_gen.return_value = "## 📋 Visão geral\n\nTexto do relatório."
        resp = self.client.post(reverse("reports:ai_report"))
        self.assertEqual(resp.status_code, 302)
        report = AIReport.objects.for_user(self.alice).get()
        self.assertTrue(report.via_ai)
        self.assertIn("Visão geral", report.content)
        self.assertTrue(can_generate is not None)

    @patch("apps.reports.services.generate_text")
    def test_cooldown_blocks_duplicate(self, mock_gen):
        mock_gen.return_value = "AAA"
        self.client.post(reverse("reports:ai_report"))  # primeiro gera
        resp = self.client.post(reverse("reports:ai_report"))  # segundo bloqueia
        self.assertEqual(resp.status_code, 302)
        msgs = [m.message for m in get_messages(resp.wsgi_request)]
        self.assertTrue(any("3 dias" in m for m in msgs))
        self.assertEqual(AIReport.objects.for_user(self.alice).count(), 1)
        mock_gen.assert_called_once()


class AIReportWebTests(TestCase):
    def setUp(self):
        self.alice = _make_user("alice")

    def test_requires_auth(self):
        resp = self.client.get(reverse("reports:ai_report"))
        self.assertEqual(resp.status_code, 302)

    def test_get_renders_empty_state(self):
        self.client.login(username="alice", password="x123")
        resp = self.client.get(reverse("reports:ai_report"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Gerar relatório")

    def test_get_shows_persisted_report(self):
        AIReport.objects.create(
            owner=self.alice, content="## ✅ Ações concretas", summary="ok"
        )
        self.client.login(username="alice", password="x123")
        resp = self.client.get(reverse("reports:ai_report"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Ações concretas")

    def test_fallback_without_ai(self):
        # Sem chave configurada (config.settings.test força GEMINI_API_KEY=""),
        # o POST não quebra: renderiza o relatório local e não persiste nada.
        self.client.login(username="alice", password="x123")
        resp = self.client.post(reverse("reports:ai_report"))
        self.assertEqual(resp.status_code, 200)
        self.assertIsNotNone(resp.context["manual_html"])
        self.assertEqual(AIReport.objects.for_user(self.alice).count(), 0)

    def test_fallback_manual_does_not_consume_cooldown(self):
        self.client.login(username="alice", password="x123")
        self.client.post(reverse("reports:ai_report"))
        # Sem relatório persistido, o cooldown continua permitindo gerar.
        self.assertTrue(can_generate(self.alice))


class AIReportErrorPathTests(TestCase):
    def setUp(self):
        self.alice = _make_user("alice")
        self.client.login(username="alice", password="x123")

    @override_settings(GEMINI_API_KEY="fake-key")
    @patch("apps.reports.services.generate_text", side_effect=AIServiceError("x"))
    def test_ai_error_falls_back_gracefully(self, mock_gen):
        resp = self.client.post(reverse("reports:ai_report"))
        self.assertEqual(resp.status_code, 200)
        self.assertIsNotNone(resp.context["manual_html"])
        self.assertEqual(AIReport.objects.for_user(self.alice).count(), 0)
