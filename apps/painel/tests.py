"""Testes do Painel do Dono — telemetria, acesso, monetização e relatórios."""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.painel.models import AccessCode, FeatureEvent, MonetizationConfig
from apps.painel.services import (
    create_access_codes,
    daily_series,
    monetization,
    overview,
    top_features,
    top_users,
    track_feature,
    user_activity_summary,
    user_feature_breakdown,
)

User = get_user_model()


def _make_superuser():
    return User.objects.create_superuser(
        username="dono", email="dono@example.com", password="senha-boa-12345"
    )


def _make_user(username="carla"):
    user = User.objects.create_user(
        username=username, email=f"{username}@example.com", password="senha-boa-12345"
    )
    user.profile.onboarding_completed = True
    user.profile.save(update_fields=["onboarding_completed"])
    return user


class TrackFeatureServiceTests(TestCase):
    def test_increments_daily_counter_per_feature(self):
        user = _make_user()
        track_feature(user, "nav.mais.importar")
        track_feature(user, "nav.mais.importar")
        track_feature(user, "nav.inicio")
        row = FeatureEvent.objects.get(user=user, feature="nav.mais.importar")
        self.assertEqual(row.count, 2)
        self.assertEqual(FeatureEvent.objects.filter(user=user).count(), 2)

    def test_ignores_unknown_prefix(self):
        user = _make_user()
        track_feature(user, "garbage-slug")
        track_feature(user, "cta.nova_transacao")
        self.assertEqual(FeatureEvent.objects.filter(user=user).count(), 1)

    def test_daily_granularity(self):
        user = _make_user()
        track_feature(user, "nav.mais.importar")
        row_old = FeatureEvent.objects.get(user=user, feature="nav.mais.importar")
        FeatureEvent.objects.filter(pk=row_old.pk).update(
            date=timezone.localdate() - timedelta(days=1),
            count=row_old.count,
        )
        track_feature(user, "nav.mais.importar")
        self.assertEqual(
            FeatureEvent.objects.filter(
                user=user, feature="nav.mais.importar"
            ).count(),
            2,
        )


class MonitoringEndpointTests(TestCase):
    def test_track_requires_auth(self):
        resp = self.client.post(
            reverse("painel:track"),
            data={"features": ["nav.inicio"]},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 204)
        self.assertEqual(FeatureEvent.objects.count(), 0)

    def test_track_records_for_authenticated(self):
        user = _make_user()
        self.client.login(username=user.username, password="senha-boa-12345")
        resp = self.client.post(
            reverse("painel:track"),
            data={"features": ["nav.mais.importar", "cta.nova_transacao"]},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 204)
        self.assertEqual(FeatureEvent.objects.filter(user=user).count(), 2)

    def test_track_single_feature_form(self):
        user = _make_user()
        self.client.login(username=user.username, password="senha-boa-12345")
        resp = self.client.post(
            reverse("painel:track"), data={"feature": "nav.cartoes"}
        )
        self.assertEqual(resp.status_code, 204)
        self.assertEqual(
            FeatureEvent.objects.filter(user=user, feature="nav.cartoes").count(), 1
        )


class AccessControlTests(TestCase):
    def setUp(self):
        self.owner = _make_superuser()
        self.user = _make_user("alice")

    def test_panel_redirects_non_staff(self):
        self.client.login(username="alice", password="senha-boa-12345")
        resp = self.client.get(reverse("painel:index"))
        # Autenticado mas não superuser -> 403 (UserPassesTestMixin).
        self.assertEqual(resp.status_code, 403)

    def test_panel_anonymous_redirects(self):
        resp = self.client.get(reverse("painel:index"))
        self.assertEqual(resp.status_code, 302)

    def test_panel_ok_for_superuser(self):
        self.client.login(username="dono", password="senha-boa-12345")
        for url in (
            reverse("painel:index"),
            reverse("painel:user_list"),
            reverse("painel:user_detail", args=[self.user.pk]),
            reverse("painel:monetization"),
        ):
            with self.subTest(url=url):
                resp = self.client.get(url)
                self.assertEqual(resp.status_code, 200)

    def test_user_actions_restricted(self):
        self.client.login(username="alice", password="senha-boa-12345")
        resp = self.client.post(
            reverse("painel:user_toggle", args=[self.user.pk, "is_active"])
        )
        self.assertEqual(resp.status_code, 403)


class UserManagementTests(TestCase):
    def setUp(self):
        self.owner = _make_superuser()
        self.user = _make_user("bob")
        self.client.login(username="dono", password="senha-boa-12345")

    def test_toggle_is_active(self):
        self.assertTrue(self.user.is_active)
        self.client.post(reverse("painel:user_toggle", args=[self.user.pk, "is_active"]))
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_active)

    def test_toggle_is_paying(self):
        self.assertFalse(self.user.is_paying)
        self.client.post(reverse("painel:user_toggle", args=[self.user.pk, "is_paying"]))
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_paying)

    def test_search_filters_user_list(self):
        other = _make_user("zezinho")
        resp = self.client.get(reverse("painel:user_list"), {"q": "bob"})
        html = resp.content.decode()
        self.assertIn("bob", html)
        self.assertNotIn("zezinho", html)


class MonetizationTests(TestCase):
    def setUp(self):
        self.owner = _make_superuser()
        self.client.login(username="dono", password="senha-boa-12345")

    def test_config_singleton_exists(self):
        cfg = monetization()
        self.assertIsInstance(cfg, MonetizationConfig)
        self.assertFalse(cfg.signup_requires_payment)

    def test_toggle_via_form(self):
        code = AccessCode.objects.create(code="ABC-123-DEF")
        resp = self.client.post(
            reverse("painel:monetization"),
            {
                "signup_requires_payment": "on",
                "price_label": "R$ 4,90 / mês",
                "payment_instructions": "Pague via Pix e receba o código.",
            },
        )
        self.assertRedirects(resp, reverse("painel:monetization"))
        cfg = monetization()
        self.assertTrue(cfg.signup_requires_payment)
        self.assertEqual(cfg.price_label, "R$ 4,90 / mês")

    def test_create_codes(self):
        resp = self.client.post(
            reverse("painel:access_code_create"), {"quantity": 3, "note": "lote 1"}
        )
        self.assertRedirects(resp, reverse("painel:monetization"))
        self.assertEqual(AccessCode.objects.count(), 3)

    def test_revoke_code(self):
        code = AccessCode.objects.create(code="XPTO-1")
        self.client.post(reverse("painel:access_code_revoke", args=[code.pk]))
        code.refresh_from_db()
        self.assertTrue(code.revoked)


class SignupGateTests(TestCase):
    def test_signup_without_payment_requirement(self):
        cfg = monetization()
        cfg.signup_requires_payment = False
        cfg.save()
        resp = self.client.post(
            reverse("accounts:signup"),
            {
                "name": "Ana",
                "email": "ana@example.com",
                "password": "senha-boa-12345",
                "password_confirmation": "senha-boa-12345",
            },
        )
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(User.objects.filter(email="ana@example.com").exists())

    def test_signup_requires_code_when_gate_on(self):
        cfg = monetization()
        cfg.signup_requires_payment = True
        cfg.save()
        # Sem código -> formulário inválido.
        resp = self.client.post(
            reverse("accounts:signup"),
            {
                "name": "Ana",
                "email": "ana@example.com",
                "password": "senha-boa-12345",
                "password_confirmation": "senha-boa-12345",
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(User.objects.filter(email="ana@example.com").exists())

    def test_signup_with_valid_code_redeems_and_marks_paying(self):
        cfg = monetization()
        cfg.signup_requires_payment = True
        cfg.save()
        code = AccessCode.objects.create(code="PAY-CODE-1")
        resp = self.client.post(
            reverse("accounts:signup"),
            {
                "name": "Ana",
                "email": "ana@example.com",
                "password": "senha-boa-12345",
                "password_confirmation": "senha-boa-12345",
                "access_code": "pay-code-1",
            },
        )
        self.assertEqual(resp.status_code, 302)
        user = User.objects.get(email="ana@example.com")
        self.assertTrue(user.is_paying)
        code.refresh_from_db()
        self.assertTrue(code.is_used)
        self.assertEqual(code.used_by, user)

    def test_signup_code_cannot_be_reused(self):
        cfg = monetization()
        cfg.signup_requires_payment = True
        cfg.save()
        AccessCode.objects.create(code="PAY-1")
        self.client.post(
            reverse("accounts:signup"),
            {
                "name": "Ana",
                "email": "ana@example.com",
                "password": "senha-boa-12345",
                "password_confirmation": "senha-boa-12345",
                "access_code": "pay-1",
            },
        )
        self.client.post(reverse("accounts:logout"))
        resp = self.client.post(
            reverse("accounts:signup"),
            {
                "name": "Bia",
                "email": "bia@example.com",
                "password": "senha-boa-12345",
                "password_confirmation": "senha-boa-12345",
                "access_code": "pay-1",
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(User.objects.filter(email="bia@example.com").exists())


class ReportsTests(TestCase):
    def setUp(self):
        self.owner = _make_superuser()
        self.carla = _make_user("carla")
        self.bob = _make_user("bob")
        for _ in range(4):
            track_feature(self.carla, "nav.mais.importar")
        track_feature(self.bob, "nav.inicio")
        self.client.login(username="dono", password="senha-boa-12345")

    def test_overview_aggregates(self):
        data = overview(days=30)
        self.assertEqual(data["total_users"], 3)
        self.assertGreaterEqual(data["events_total"], 5)

    def test_top_features_ordered(self):
        rows = top_features(days=30)
        self.assertEqual(rows[0]["feature"], "nav.mais.importar")
        self.assertEqual(rows[0]["total"], 4)

    def test_top_users_ordered(self):
        rows = top_users(days=30)
        self.assertEqual(rows[0]["user"], self.carla)
        self.assertEqual(rows[0]["events"], 4)
        self.assertGreaterEqual(rows[0]["days_active"], 1)

    def test_daily_series(self):
        series = daily_series(days=30)
        self.assertTrue(any(r["total"] >= 5 for r in series))

    def test_user_breakdown(self):
        rows = user_feature_breakdown(self.carla)
        self.assertEqual(rows[0]["feature"], "nav.mais.importar")
        self.assertEqual(rows[0]["total"], 4)

    def test_user_activity_summary(self):
        from apps.finance.services.accounts import create_account

        create_account(user=self.carla, name="Conta")
        summary = user_activity_summary(self.carla)
        self.assertGreaterEqual(summary["events"], 4)
        self.assertGreaterEqual(summary["accounts"], 1)