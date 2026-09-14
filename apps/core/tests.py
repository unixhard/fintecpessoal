"""Testes da landing page institucional — conversão e estados de monetização."""

from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import User
from apps.painel.models import MonetizationConfig, Plan


class LandingPageTests(TestCase):
    """A landing deve renderizar com planos, provas e microcopy coerente."""

    @classmethod
    def setUpTestData(cls):
        cls.gratis = Plan.objects.create(
            name="Grátis",
            description="Para começar",
            price=Decimal("0.00"),
            billing_cycle=Plan.MONTHLY,
            duration_days=30,
            order=1,
        )
        cls.mensal = Plan.objects.create(
            name="Mensal",
            description="Controle completo",
            price=Decimal("24.90"),
            billing_cycle=Plan.MONTHLY,
            duration_days=30,
            is_featured=True,
            order=2,
        )
        cls.vitalicio = Plan.objects.create(
            name="Vitalício",
            description="Pagamento único",
            price=Decimal("299.00"),
            billing_cycle=Plan.LIFETIME,
            duration_days=0,
            order=3,
        )
        cls.anual = Plan.objects.create(
            name="Anual",
            description="Melhor preço no mês",
            price=Decimal("199.00"),
            billing_cycle=Plan.YEARLY,
            duration_days=365,
            order=4,
        )
        cls.user = User.objects.create_user(
            username="maria", email="maria@example.com", password="abc12345"
        )
        cls.cfg = MonetizationConfig.get_singleton()

    def test_home_landing_render_200(self):
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode("utf-8")
        self.assertIn("Seu dinheiro, organizado", html)
        self.assertIn("Sem surpresa no fim do mês", html)
        self.assertIn("Feito para quem odeia planilhas", html)
        self.assertIn("Garantia de 7 dias", html)
        self.assertIn("Como seus dados são tratados", html)
        self.assertNotIn("TemplateSyntaxError", html)
        self.assertNotIn("Traceback", html)

    def test_home_exibe_planos_ativos(self):
        resp = self.client.get("/")
        html = resp.content.decode("utf-8")
        # Plano grátis virou "Grátis" (nunca "R$ 0,00")
        self.assertIn("Grátis", html)
        self.assertNotIn("R$ 0,00", html)
        self.assertIn("R$ 24,90", html)
        self.assertIn("Mensal", html)
        self.assertIn("Vitalício", html)
        # Ancoragem de preço no plano anual (per_month ≈ 16,36)
        self.assertIn("Anual", html)
        self.assertIn("≈ R$ 16,36/mês", html)

    def test_home_microcopy_gratis_sem_atrito(self):
        # Sem modo pago, diz "Grátis para começar" e "Sem cartão de crédito"
        resp = self.client.get("/")
        html = resp.content.decode("utf-8")
        self.assertIn("Grátis para começar", html)
        self.assertIn("Sem cartão de crédito", html)

    def test_home_modo_pago_mostra_solicitar_acesso(self):
        cfg = MonetizationConfig.get_singleton()
        cfg.signup_requires_payment = True
        cfg.price_label = "R$ 24,90/mês"
        cfg.save()
        resp = self.client.get("/")
        html = resp.content.decode("utf-8")
        self.assertIn("Solicitar acesso", html)
        self.assertIn("Acesso imediato", html)
        # Ao contrário, o microcopy de "grátis" sai do ar
        self.assertNotIn("Grátis para começar", html)
        self.assertNotIn("Sem cartão de crédito", html)

    def test_home_prova_social_usuario_real(self):
        resp = self.client.get("/")
        html = resp.content.decode("utf-8")
        self.assertIn("pessoas já cuidam das finanças aqui", html)

    def test_signup_prefill_email_do_form(self):
        url = reverse("accounts:signup")
        resp = self.client.get(f"{url}?email=anna@example.com")
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode("utf-8")
        self.assertIn('value="anna@example.com"', html)