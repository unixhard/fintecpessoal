"""Testes do fluxo completo de autenticação, onboarding e shell (Ordem 6).

Cobre: cadastro, login, logout, recuperação de senha, onboarding, criação da
primeira conta com ownership, proteção de rotas e ISOLAMENTO REAL entre usuários.
"""

from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.test import TestCase
from django.urls import reverse

from apps.finance.models import Account
from apps.finance.services.accounts import create_account

User = get_user_model()


class SignUpTests(TestCase):
    def test_valid_signup_creates_user_and_profile(self):
        resp = self.client.post(
            reverse("accounts:signup"),
            {
                "name": "Maria Silva",
                "email": "maria@example.com",
                "password": "senha-super-segura-123",
                "password_confirmation": "senha-super-segura-123",
            },
        )
        # Cadastro autentica e direciona ao onboarding (etapa 1).
        self.assertEqual(resp.status_code, 302)
        self.assertRedirects(resp, reverse("accounts:onboarding_step", args=[1]))
        user = User.objects.get(email="maria@example.com")
        self.assertTrue(user.profile)
        self.assertFalse(user.profile.onboarding_completed)
        self.assertEqual(user.username, "maria")
        self.assertEqual(user.first_name, "Maria")
        self.assertEqual(user.last_name, "Silva")

    def test_signup_matches_username_from_email_uniqueness(self):
        self.client.post(
            reverse("accounts:signup"),
            {
                "name": "Maria",
                "email": "maria@example.com",
                "password": "senha-super-segura-123",
                "password_confirmation": "senha-super-segura-123",
            },
        )
        self.client.logout()
        resp = self.client.post(
            reverse("accounts:signup"),
            {
                "name": "Maria Segundo",
                "email": "maria@example.com",
                "password": "outra-senha-segura-456",
                "password_confirmation": "outra-senha-segura-456",
            },
        )
        # Email duplicado -> formulário inválido, sem nova conta com mesmo email.
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(User.objects.filter(email="maria@example.com").count(), 1)

    def test_invalid_password_rejected(self):
        resp = self.client.post(
            reverse("accounts:signup"),
            {
                "name": "Joao",
                "email": "joao@example.com",
                "password": "123",
                "password_confirmation": "123",
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(User.objects.filter(email="joao@example.com").exists())

    def test_password_confirmation_mismatch_rejected(self):
        resp = self.client.post(
            reverse("accounts:signup"),
            {
                "name": "Joao",
                "email": "joao@example.com",
                "password": "senha-boa-12345",
                "password_confirmation": "outra-senha-diferente",
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(User.objects.filter(email="joao@example.com").exists())


class LoginLogoutTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="carla", email="carla@example.com", password="senha-boa-12345"
        )

    def test_login_by_email(self):
        resp = self.client.post(
            reverse("accounts:login"),
            {"username": "carla@example.com", "password": "senha-boa-12345"},
        )
        # Após login vai para a raiz (/), que desvia conforme onboarding.
        self.assertRedirects(
            resp, reverse("core:home"), fetch_redirect_response=False
        )
        self.assertTrue("_auth_user_id" in self.client.session)

    def test_login_invalid_credentials(self):
        resp = self.client.post(
            reverse("accounts:login"),
            {"username": "carla@example.com", "password": "errada"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertFalse("_auth_user_id" in self.client.session)

    def test_logout_via_post(self):
        self.client.login(username="carla", password="senha-boa-12345")
        resp = self.client.post(reverse("accounts:logout"))
        self.assertRedirects(resp, reverse("accounts:login"))
        self.assertFalse("_auth_user_id" in self.client.session)

    def test_protected_page_redirects_unauthenticated(self):
        resp = self.client.get(reverse("dashboard:index"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse("accounts:login"), resp.url)


class PasswordResetTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="pedro", email="pedro@example.com", password="senha-antiga-123"
        )

    def _reset_link_from_outbox(self):
        body = mail.outbox[0].body
        for line in body.splitlines():
            line = line.strip()
            if "/recuperar-senha/confirmar/" in line:
                # Captura a URL absoluta completa (ex.: http://testserver/...).
                start = line.index("http")
                return line[start:]
        self.fail("Link de redefinição não encontrado no email.")

    def test_password_reset_flow(self):
        resp = self.client.post(
            reverse("accounts:password_reset"), {"email": "pedro@example.com"}
        )
        self.assertRedirects(resp, reverse("accounts:password_reset_done"))
        self.assertEqual(len(mail.outbox), 1)

        link = self._reset_link_from_outbox()
        # Django 6.1 valida o token e redireciona para uma URL "set-password".
        resp = self.client.get(link)
        self.assertEqual(resp.status_code, 302)
        set_password_url = resp.url
        self.assertIn("/set-password/", set_password_url)

        resp = self.client.get(set_password_url)
        self.assertEqual(resp.status_code, 200)
        redirect = self.client.post(
            set_password_url,
            {"new_password1": "nova-senha-456789", "new_password2": "nova-senha-456789"},
        )
        self.assertRedirects(redirect, reverse("accounts:password_reset_complete"))

        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("nova-senha-456789"))

    def test_password_reset_does_not_reveal_existence(self):
        # Email inexistente: redireciona para o "done" (sem vazar se existe).
        resp = self.client.post(
            reverse("accounts:password_reset"), {"email": "naoexiste@example.com"}
        )
        self.assertRedirects(resp, reverse("accounts:password_reset_done"))
        self.assertEqual(len(mail.outbox), 0)


class OnboardingFlowTests(TestCase):
    def _signup_auth(self, name="Ana", email="ana@example.com", password="senha-boa-12345"):
        self.client.post(
            reverse("accounts:signup"),
            {
                "name": name,
                "email": email,
                "password": password,
                "password_confirmation": password,
            },
        )
        return User.objects.get(email=email)

    def test_new_user_beginner_redirected_to_onboarding(self):
        user = self._signup_auth()
        # Acesso à raiz depois de autenticado e sem onboarding -> onboarding 1.
        resp = self.client.get(reverse("core:home"))
        self.assertRedirects(
            resp,
            reverse("accounts:onboarding_step", args=[1]),
            fetch_redirect_response=False,
        )

    def test_onboarding_steps_and_account_creation(self):
        user = self._signup_auth()
        # Etapa 1 visível
        resp = self.client.get(reverse("accounts:onboarding_step", args=[1]))
        self.assertEqual(resp.status_code, 200)
        # Etapa 2 (perfil)
        resp = self.client.post(
            reverse("accounts:onboarding_step", args=[2]),
            {"display_name": "Ana", "preferred_currency": "BRL"},
        )
        self.assertRedirects(resp, reverse("accounts:onboarding_step", args=[3]))
        user.refresh_from_db()
        self.assertEqual(user.profile.display_name, "Ana")
        # Etapa 3 (primeira conta) -> cria conta com ownership + conclui onboarding
        resp = self.client.post(
            reverse("accounts:onboarding_step", args=[3]),
            {"name": "Conta Corrente", "type": "checking", "initial_balance": "1.500,00"},
        )
        self.assertRedirects(resp, reverse("accounts:onboarding_step", args=[4]))
        user.refresh_from_db()
        self.assertTrue(user.profile.onboarding_completed)
        account = Account.objects.get(owner=user)
        self.assertEqual(account.name, "Conta Corrente")
        self.assertEqual(account.type, Account.Type.CHECKING)
        self.assertEqual(account.initial_balance, 150000)

    def test_onboarding_not_accessible_after_completion(self):
        user = self._signup_auth()
        # Completa rapidamente o onboarding.
        self.client.post(reverse("accounts:onboarding_step", args=[3]),
                         {"name": "Carteira", "type": "cash", "initial_balance": "0"},
                         )
        user.refresh_from_db()
        self.assertTrue(user.profile.onboarding_completed)
        # Acessar onboarding agora redireciona para a aplicação.
        resp = self.client.get(reverse("accounts:onboarding_step", args=[1]))
        self.assertRedirects(resp, reverse("dashboard:index"))

    def test_onboarded_user_goes_to_dashboard_after_login(self):
        user = self._signup_auth()
        self.client.post(reverse("accounts:onboarding_step", args=[3]),
                         {"name": "Carteira", "type": "cash", "initial_balance": "0"},
                         )
        self.client.post(reverse("accounts:logout"))
        resp = self.client.post(
            reverse("accounts:login"),
            {"username": "ana@example.com", "password": "senha-boa-12345"},
        )
        self.assertRedirects(
            resp, reverse("core:home"), fetch_redirect_response=False
        )
        # A raiz agora leva ao dashboard (onboarding concluído).
        resp = self.client.get(reverse("core:home"))
        self.assertRedirects(
            resp, reverse("dashboard:index"), fetch_redirect_response=False
        )


class ShellTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="edu", email="edu@example.com", password="senha-boa-12345",
        )
        self.user.profile.onboarding_completed = True
        self.user.profile.save(update_fields=["onboarding_completed"])

    def test_authenticated_shell_responds(self):
        self.client.login(username="edu", password="senha-boa-12345")
        html = self.client.get(reverse("dashboard:index")).content.decode()
        for marker in ("Seu painel financeiro", "Movimentações", "Contas", "Cartões", "Sair"):
            with self.subTest(marker=marker):
                self.assertIn(marker, html)
        for url in (
            reverse("dashboard:index"),
            reverse("dashboard:section", args=["contas"]),
            reverse("dashboard:section", args=["cartoes"]),
        ):
            with self.subTest(url=url):
                resp = self.client.get(url)
                self.assertEqual(resp.status_code, 200)

    def test_unauthenticated_redirected(self):
        resp = self.client.get(reverse("dashboard:index"))
        self.assertEqual(resp.status_code, 302)


class RealIsolationTests(TestCase):
    def test_user_a_cannot_see_or_create_for_user_b(self):
        a = User.objects.create_user(username="alice", email="alice@example.com", password="x")
        b = User.objects.create_user(username="bob", email="bob@example.com", password="y")

        account_a = create_account(user=a, name="Conta da Alice")
        create_account(user=b, name="Conta do Bob")

        # A não vê a conta de B através do manager de ownership.
        self.assertNotIn(
            account_a.pk,
            list(Account.objects.for_user(b).values_list("pk", flat=True)),
        )
        # Cada serviço sempre atribui owner ao usuário autenticado (nunca do frontend).
        created_by_b = create_account(user=b, name="Outra do Bob")
        self.assertEqual(created_by_b.owner_id, b.id)
        self.assertNotIn(created_by_b.pk, list(Account.objects.for_user(a).values_list("pk", flat=True)))

    def test_user_a_cannot_alter_user_b_account_through_onboarding(self):
        a = User.objects.create_user(username="alice", email="alice@example.com", password="x")
        b = User.objects.create_user(username="bob", email="bob@example.com", password="y")
        create_account(user=b, name="Conta do Bob")

        # Autenticado como A, tenta (não existe rota de edição de B) — garantimos
        # que o onboarding de A nunca toca contas de B e que o manager isola.
        self.client.login(username="alice", password="x")
        self.client.post(reverse("accounts:onboarding_step", args=[3]),
                         {"name": "Conta da Alice", "type": "checking", "initial_balance": "0"},
                         )
        bob_accounts = Account.objects.for_user(b)
        self.assertEqual(bob_accounts.count(), 1)
        self.assertEqual(bob_accounts.first().name, "Conta do Bob")
        alice_accounts = Account.objects.for_user(a)
        self.assertEqual(alice_accounts.count(), 1)
        self.assertEqual(alice_accounts.first().name, "Conta da Alice")

    def test_unauthenticated_cannot_reach_onboarding(self):
        resp = self.client.get(reverse("accounts:onboarding_step", args=[1]))
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse("accounts:login"), resp.url)
