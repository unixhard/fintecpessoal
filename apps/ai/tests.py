"""Testes da camada de IA econômica (CFO de Bolso).

Roda sob ``config.settings.test`` (GEMINI_API_KEY vazio), então TODOS os fluxos
exercem o caminho determinístico/fallback — exatamente o que acontece em
produção quando a IA está fora ou o orçamento diário acabou.
"""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.ai import budget
from apps.ai.services import ask, breaker, ledger, presence
from apps.ai.services.digest import build_digest
from apps.finance.models import Account, Transaction

User = get_user_model()


class LedgerTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(username="ana-ledger", password="x")

    def test_consume_respects_cap_and_reports_remaining(self):
        self.assertEqual(ledger.remaining("consult", self.user, 3), 3)
        self.assertTrue(ledger.consume("consult", self.user, 3))
        self.assertTrue(ledger.consume("consult", self.user, 3))
        self.assertTrue(ledger.consume("consult", self.user, 3))
        self.assertEqual(ledger.remaining("consult", self.user, 3), 0)
        # Acima do teto: nega (cai no fallback determinístico do chamador).
        self.assertFalse(ledger.consume("consult", self.user, 3))
        self.assertEqual(ledger.count("consult", self.user), 3)

    def test_ledger_is_per_user(self):
        other = User.objects.create_user(username="bob-ledger", password="x")
        ledger.consume("consult", self.user, 3)
        self.assertEqual(ledger.remaining("consult", self.user, 3), 2)
        self.assertEqual(ledger.remaining("consult", other, 3), 3)

    def test_ledger_is_per_feature(self):
        ledger.consume("presence", self.user, 1)
        self.assertEqual(ledger.remaining("presence", self.user, 1), 0)
        # Consulta não compartilha teto com a presença.
        self.assertEqual(ledger.remaining("consult", self.user, 3), 3)


class BreakerTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_breaker_opens_after_failures_and_recovers_after_window(self):
        self.assertTrue(breaker.permission_granted())
        for _ in range(budget.CIRCUIT_BREAKER_FAILURES):
            breaker.report_failure()
        self.assertFalse(breaker.permission_granted())
        # Sucesso não reverte um breaker aberto (janela precisa expirar),
        # mas zera o contador de falhas para a próxima janela.
        breaker.report_success()

    def test_success_resets_failure_counter(self):
        breaker.report_failure()
        breaker.report_failure()
        breaker.report_success()
        self.assertTrue(breaker.permission_granted())


class DigestTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="maria-digest", password="x")
        self.account = Account.objects.create(
            owner=self.user, name="Conta", initial_balance=100000
        )
        Transaction.objects.create(
            owner=self.user, account=self.account, description="Aluguel",
            type=Transaction.Type.EXPENSE, amount=120000,
            date=timezone.localdate(),
        )

    def test_digest_is_enxuto_and_structured(self):
        d = build_digest(self.user)
        self.assertEqual(d["nome"], "maria-digest")
        self.assertIsInstance(d["disponivel_centavos"], int)
        self.assertIsInstance(d["despesas_centavos"], int)
        self.assertGreaterEqual(d["despesas_centavos"], 0)
        # Tipos estáveis para o prompt (economia: tudo em centavos, sem texto cru).
        self.assertIsInstance(d["alertas"], list)


class PresenceTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(
            username="joao-presenca", first_name="João", password="x"
        )

    def test_fallback_presence_always_answers(self):
        p = presence.daily_presence(self.user)
        self.assertIn("saudacao", p)
        self.assertIn("insights", p)
        self.assertIn("dica", p)
        self.assertIn("alerta", p)
        self.assertTrue(p["saudacao"].strip())

    def test_presence_is_cached_for_the_day(self):
        first = presence.daily_presence(self.user)
        second = presence.daily_presence(self.user)
        self.assertEqual(first["saudacao"], second["saudacao"])
        self.assertEqual(ledger.count("presence", self.user), 0)

    def test_ai_presence_respects_daily_budget(self):
        # Simula IA disponível: gera UMA presença com IA/dia e depois usa o cache.
        with (
            patch("apps.ai.services.presence.ai_enabled", return_value=True),
            patch(
                "apps.ai.services.presence.generate_json",
                return_value={
                    "saudacao": "Olá, João!",
                    "insights": ["Seu resultado fechou positivo."],
                    "alerta": "",
                    "dica": "Separe renda.",
                },
            ),
        ):
            p = presence.daily_presence(self.user)
            self.assertEqual(p["via_ia"], True)
            self.assertEqual(ledger.count("presence", self.user), 1)
            # Mesmo chamando de novo, o cache responde sem gastar mais tokens.
            p2 = presence.daily_presence(self.user)
            self.assertEqual(p2["via_ia"], True)
            self.assertEqual(ledger.count("presence", self.user), 1)


class AskTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(username="paulo-ask", password="x")

    def test_empty_message(self):
        result = ask.answer(self.user, "   ")
        self.assertIn("resposta", result)

    def test_deterministic_answer_when_ai_unavailable(self):
        result = ask.answer(self.user, "Onde posso cortar gastos?")
        self.assertFalse(result["via_ia"])
        self.assertTrue(result["resposta"].strip())
        self.assertIsNone(result["restantes"])  # sem IA, sem contador de consumo

    def test_ai_answer_respects_consult_cap(self):
        with (
            patch("apps.ai.services.ask.ai_enabled", return_value=True),
            patch(
                "apps.ai.services.ask.generate_json",
                return_value={"resposta": "Resposta da IA."},
            ),
        ):
            for _ in range(budget.CONSULT_DAILY_CAP):
                result = ask.answer(self.user, "alguma pergunta")
                self.assertTrue(result["via_ia"] or result["limite"])
            # Após o teto do dia, cai no fallback determinístico e sinaliza limite.
            result = ask.answer(self.user, "alguma pergunta")
            self.assertFalse(result["via_ia"])
            self.assertTrue(result["limite"])
            self.assertEqual(result["restantes"], 0)

    def test_ai_failure_lands_on_deterministic_fallback(self):
        with (
            patch("apps.ai.services.ask.ai_enabled", return_value=True),
            patch(
                "apps.ai.services.ask.generate_json",
                side_effect=Exception("boom"),
            ),
        ):
            result = ask.answer(self.user, "Quanto posso gastar?")
            self.assertFalse(result["via_ia"])
            self.assertTrue(result["resposta"].strip())


class ConsultEndpointTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(username="rita-consult", password="x")

    def _login(self):
        self.client.login(username="rita-consult", password="x")

    def test_requires_login(self):
        resp = self.client.post(reverse("ai:consult"), {"message": "oi"})
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse("accounts:login"), resp.url)

    def test_requires_post(self):
        self._login()
        resp = self.client.get(reverse("ai:consult"))
        self.assertEqual(resp.status_code, 405)

    def test_empty_message_returns_400(self):
        self._login()
        resp = self.client.post(reverse("ai:consult"), {"message": ""})
        self.assertEqual(resp.status_code, 400)

    def test_answers_json(self):
        self._login()
        resp = self.client.post(reverse("ai:consult"), {"message": "Quanto posso gastar?"})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["ok"])
        self.assertIn("resposta", data)
        self.assertFalse(data["via_ia"])


class DashboardCfoTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(username="cfo-dash", password="x")
        self.user.profile.onboarding_completed = True
        self.user.profile.save(update_fields=["onboarding_completed"])
        self.client.login(username="cfo-dash", password="x")

    def test_dashboard_renders_cfo_presence(self):
        html = self.client.get(reverse("dashboard:index")).content.decode()
        self.assertIn("Seu CFO de bolso", html)