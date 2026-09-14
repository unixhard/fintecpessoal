"""Testes do Painel do Dono — telemetria, acesso, monetização e relatórios."""

from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.painel.models import (
    AccessCode,
    Coupon,
    FeatureEvent,
    MonetizationConfig,
    Payment,
    Plan,
    Subscription,
)
from apps.painel.services import (
    arr,
    cancel_subscription,
    churn_rate,
    conversion_rate,
    create_access_codes,
    daily_series,
    expire_due_subscriptions,
    grant_subscription,
    mark_payment_paid,
    monetization,
    mrr,
    overview,
    record_payment,
    refund_payment,
    revenue_by_method,
    revenue_by_plan,
    revenue_summary,
    top_customers,
    top_features,
    top_users,
    track_feature,
    user_activity_summary,
    user_feature_breakdown,
    user_ltv,
    user_payments,
    user_subscription,
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


def _make_plan(name="Premium", price="9.90", cycle=Plan.MONTHLY, days=30, **kw):
    return Plan.objects.create(name=name, price=price, billing_cycle=cycle, duration_days=days, **kw)


class PlanTests(TestCase):
    def setUp(self):
        self.owner = _make_superuser()
        self.client.login(username="dono", password="senha-boa-12345")

    def test_create_plan_view(self):
        resp = self.client.post(
            reverse("painel:plan_create"),
            {
                "name": "Mensal Pro",
                "price": "19.90",
                "billing_cycle": Plan.MONTHLY,
                "duration_days": "30",
                "is_active": "on",
            },
        )
        self.assertRedirects(resp, reverse("painel:plan_list"))
        plan = Plan.objects.get(name="Mensal Pro")
        self.assertEqual(plan.slug, "mensal-pro")
        self.assertEqual(str(plan.price), "19.90")

    def test_edit_and_toggle(self):
        plan = _make_plan()
        resp = self.client.post(
            reverse("painel:plan_edit", args=[plan.pk]),
            {
                "name": "Premium v2",
                "price": "12.00",
                "billing_cycle": Plan.MONTHLY,
                "duration_days": "30",
                "is_active": "",
            },
        )
        self.assertRedirects(resp, reverse("painel:plan_list"))
        plan.refresh_from_db()
        self.assertEqual(plan.name, "Premium v2")
        self.assertFalse(plan.is_active)
        self.client.post(reverse("painel:plan_toggle", args=[plan.pk]))
        plan.refresh_from_db()
        self.assertTrue(plan.is_active)

    def test_plan_list_page(self):
        _make_plan()
        resp = self.client.get(reverse("painel:plan_list"))
        self.assertEqual(resp.status_code, 200)

    def test_duplicate_names_get_unique_slugs(self):
        p1 = _make_plan(name="Anual VIP")
        p2 = _make_plan(name="Anual VIP")
        self.assertEqual(p1.slug, "anual-vip")
        self.assertEqual(p2.slug, "anual-vip-1")

    def test_monthly_value_normalizes(self):
        monthly = _make_plan(price="10.00", cycle=Plan.MONTHLY)
        yearly = _make_plan(name="Anual", price="120.00", cycle=Plan.YEARLY)
        lifetime = _make_plan(name="Vitalício", price="299.00", cycle=Plan.LIFETIME, days=0)
        self.assertEqual(monthly.monthly_value, 10)
        self.assertEqual(yearly.monthly_value * 12, 120)
        self.assertEqual(lifetime.monthly_value, 0)


class CouponTests(TestCase):
    def setUp(self):
        self.owner = _make_superuser()
        self.client.login(username="dono", password="senha-boa-12345")

    def test_create_view(self):
        resp = self.client.post(
            reverse("painel:coupon_create"),
            {
                "code": "PIX10",
                "discount_type": Coupon.PERCENT,
                "discount_value": "10",
                "max_uses": "5",
                "is_active": "on",
            },
        )
        self.assertRedirects(resp, reverse("painel:coupon_list"))
        coupon = Coupon.objects.get(code="PIX10")
        self.assertTrue(coupon.is_valid)

    def test_percent_apply(self):
        coupon = Coupon.objects.create(code="P10", discount_type=Coupon.PERCENT, discount_value=10)
        self.assertEqual(coupon.apply_to(100), 90)

    def test_fixed_apply_never_negative(self):
        coupon = Coupon.objects.create(code="F50", discount_type=Coupon.FIXED, discount_value=50)
        self.assertEqual(coupon.apply_to(30), 0)

    def test_expired_or_exhausted_invalid(self):
        past = timezone.localdate() - timedelta(days=1)
        Coupon.objects.create(code="OLD", discount_type=Coupon.FIXED, discount_value=1, valid_until=past)
        used = Coupon.objects.create(code="USED", discount_type=Coupon.FIXED, discount_value=1, max_uses=1, times_used=1)
        self.assertFalse(Coupon.objects.get(code="OLD").is_valid)
        self.assertFalse(Coupon.objects.get(code="USED").is_valid)

    def test_list_and_toggle(self):
        c = Coupon.objects.create(code="X", discount_type=Coupon.FIXED, discount_value=5)
        resp = self.client.get(reverse("painel:coupon_list"))
        self.assertEqual(resp.status_code, 200)
        self.client.post(reverse("painel:coupon_toggle", args=[c.pk]))
        c.refresh_from_db()
        self.assertFalse(c.is_active)


class SubscriptionServiceTests(TestCase):
    def setUp(self):
        self.user = _make_user()
        self.plan = _make_plan()

    def test_grant_marks_paying(self):
        sub = grant_subscription(self.user, self.plan)
        self.assertTrue(sub.is_current)
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_paying)
        self.assertEqual(user_subscription(self.user), sub)

    def test_cancel_syncs_is_paying(self):
        sub = grant_subscription(self.user, self.plan)
        cancel_subscription(sub)
        self.assertEqual(sub.status, Subscription.CANCELED)
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_paying)
        self.assertIsNone(user_subscription(self.user))

    def test_expire_due(self):
        sub = grant_subscription(self.user, self.plan)
        Subscription.objects.filter(pk=sub.pk).update(
            status=Subscription.ACTIVE,
            expires_at=timezone.now() - timedelta(days=1),
        )
        count = expire_due_subscriptions()
        self.assertTrue(count >= 1)
        sub.refresh_from_db()
        self.assertEqual(sub.status, Subscription.EXPIRED)
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_paying)

    def test_lifetime_plan_never_expires(self):
        lifetime = _make_plan(name="Vitalício", price="299.00", cycle=Plan.LIFETIME, days=0)
        sub = grant_subscription(self.user, lifetime)
        self.assertIsNone(sub.expires_at)
        self.assertTrue(sub.is_current)
        self.assertTrue(self.user.is_paying)

    def test_grant_none_returns_none(self):
        self.assertIsNone(grant_subscription(self.user, None))


class PaymentServiceTests(TestCase):
    def setUp(self):
        self.user = _make_user()
        self.plan = _make_plan()

    def test_record_pending_sets_amount_and_method(self):
        p = record_payment(self.user, amount="19.90", method=Payment.PIX, plan=self.plan)
        self.assertEqual(p.status, Payment.PENDING)
        self.assertEqual(str(p.amount), "19.90")
        self.assertFalse(self.user.is_paying)

    def test_record_with_coupon_sets_discount(self):
        coupon = Coupon.objects.create(code="P10", discount_type=Coupon.PERCENT, discount_value=10)
        p = record_payment(self.user, amount="19.90", plan=self.plan, coupon=coupon)
        # desconto calculado sobre o preço do plano
        self.assertEqual(p.discount, Decimal("0.990"))

    def test_mark_paid_grants_subscription(self):
        p = record_payment(self.user, amount="19.90", plan=self.plan)
        mark_payment_paid(p)
        p.refresh_from_db()
        self.assertEqual(p.status, Payment.PAID)
        self.assertIsNotNone(p.paid_at)
        self.assertIsNotNone(p.subscription)
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_paying)

    def test_refund_payment(self):
        p = record_payment(self.user, amount="19.90", plan=self.plan)
        mark_payment_paid(p)
        refund_payment(p)
        p.refresh_from_db()
        self.assertEqual(p.status, Payment.REFUNDED)

    def test_lifetime_value(self):
        p1 = record_payment(self.user, amount="10.00", plan=self.plan)
        p2 = record_payment(self.user, amount="20.00", plan=self.plan)
        mark_payment_paid(p1)
        mark_payment_paid(p2)
        self.assertEqual(user_ltv(self.user), 30)
        self.assertEqual(len(user_payments(self.user)), 2)


class RevenueReportTests(TestCase):
    def setUp(self):
        self.owner = _make_superuser()
        self.user = _make_user()
        self.plan = _make_plan(price="10.00")

    def test_revenue_summary_counts_paid_only(self):
        paid = record_payment(self.user, amount="10.00", plan=self.plan)
        pending = record_payment(self.user, amount="10.00", plan=self.plan)
        mark_payment_paid(paid)
        summary = revenue_summary(days=30)
        self.assertEqual(summary["period_count"], 1)
        self.assertEqual(summary["period_amount"], 10)
        self.assertEqual(str(summary["ticket"]), "10.00")
        refund_payment(paid)
        self.assertEqual(revenue_summary(days=30)["period_amount"], 0)

    def test_mrr_arr(self):
        grant_subscription(self.user, self.plan)
        self.assertEqual(mrr(), 10)
        self.assertEqual(arr(), 120)

    def test_revenue_by_plan_and_method(self):
        p = record_payment(self.user, amount="10.00", method=Payment.CARD, plan=self.plan)
        mark_payment_paid(p)
        plan_rows = revenue_by_plan(days=30)
        method_rows = revenue_by_method(days=30)
        self.assertEqual(plan_rows[0]["total"], 10)
        self.assertEqual(method_rows[0]["method"], Payment.CARD)

    def test_conversion_and_churn(self):
        self.assertIsNotNone(conversion_rate())
        self.assertIsNotNone(churn_rate(days=30))

    def test_top_customers(self):
        p = record_payment(self.user, amount="25.00", plan=self.plan)
        mark_payment_paid(p)
        rows = top_customers(days=30)
        self.assertEqual(rows[0]["user"], self.user.pk)
        self.assertEqual(rows[0]["total"], 25)


class SalesViewTests(TestCase):
    def setUp(self):
        self.owner = _make_superuser()
        self.user = _make_user()
        self.plan = _make_plan()
        self.client.login(username="dono", password="senha-boa-12345")

    def test_sales_pages_return_200(self):
        for url in (
            reverse("painel:plan_list"),
            reverse("painel:plan_create"),
            reverse("painel:coupon_list"),
            reverse("painel:coupon_create"),
            reverse("painel:subscription_list"),
            reverse("painel:payment_list"),
            reverse("painel:reports"),
            reverse("painel:payment_create", args=[self.user.pk]),
        ):
            with self.subTest(url=url):
                resp = self.client.get(url)
                self.assertEqual(resp.status_code, 200)

    def test_grant_subscription_via_modal_post(self):
        resp = self.client.post(
            reverse("painel:subscription_grant", args=[self.user.pk]),
            {"plan": self.plan.pk, "notes": "via Pix"},
        )
        self.assertRedirects(resp, reverse("painel:user_detail", args=[self.user.pk]))
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_paying)

    def test_cancel_subscription_post(self):
        sub = grant_subscription(self.user, self.plan)
        resp = self.client.post(reverse("painel:subscription_cancel", args=[sub.pk]))
        self.assertEqual(resp.status_code, 302)
        sub.refresh_from_db()
        self.assertEqual(sub.status, Subscription.CANCELED)

    def test_record_payment_and_mark_paid(self):
        resp = self.client.post(
            reverse("painel:payment_create", args=[self.user.pk]),
            {"amount": "19.90", "method": Payment.PIX, "plan": self.plan.pk},
        )
        self.assertRedirects(resp, reverse("painel:user_detail", args=[self.user.pk]))
        payment = Payment.objects.get(user=self.user)
        self.assertEqual(payment.status, Payment.PENDING)
        self.client.post(reverse("painel:payment_mark_paid", args=[payment.pk]))
        payment.refresh_from_db()
        self.assertEqual(payment.status, Payment.PAID)
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_paying)

    def test_refund_post(self):
        p = record_payment(self.user, amount="9.90", plan=self.plan)
        resp = self.client.post(reverse("painel:payment_refund", args=[p.pk]))
        self.assertEqual(resp.status_code, 302)
        p.refresh_from_db()
        self.assertEqual(p.status, Payment.REFUNDED)

    def test_filter_filters(self):
        for st in ("active", "trial", "expired", "canceled"):
            resp = self.client.get(reverse("painel:subscription_list"), {"status": st})
            self.assertEqual(resp.status_code, 200)
        resp = self.client.get(reverse("painel:payment_list"), {"status": "paid"})
        self.assertEqual(resp.status_code, 200)
        resp = self.client.get(reverse("painel:reports"), {"days": "7"})
        self.assertEqual(resp.status_code, 200)

    def test_sales_views_restricted_to_superuser(self):
        self.client.logout()
        alice = _make_user("alice2")
        self.client.login(username="alice2", password="senha-boa-12345")
        for url in (
            reverse("painel:plan_list"),
            reverse("painel:coupon_list"),
            reverse("painel:subscription_list"),
            reverse("painel:payment_list"),
            reverse("painel:reports"),
        ):
            with self.subTest(url=url):
                resp = self.client.get(url)
                self.assertEqual(resp.status_code, 403)

    def test_grant_form_requires_valid_plan(self):
        alice = _make_user("guida")
        self.client.post(
            reverse("painel:subscription_grant", args=[alice.pk]),
            {"plan": "999999", "notes": ""},
        )
        self.assertFalse(alice.is_paying)


class AccessCodePlanTests(TestCase):
    def test_signup_with_plan_code_grants_subscription(self):
        cfg = monetization()
        cfg.signup_requires_payment = True
        cfg.save()
        plan = _make_plan()
        code = AccessCode.objects.create(
            code="PLAN-1", note="Pix lote 1", plan=plan
        )
        resp = self.client.post(
            reverse("accounts:signup"),
            {
                "name": "Tiago",
                "email": "tiago@example.com",
                "password": "senha-boa-12345",
                "password_confirmation": "senha-boa-12345",
                "access_code": "plan-1",
            },
        )
        self.assertEqual(resp.status_code, 302)
        user = User.objects.get(email="tiago@example.com")
        self.assertTrue(user.is_paying)
        sub = user_subscription(user)
        self.assertIsNotNone(sub)
        self.assertEqual(sub.plan, plan)
        code.refresh_from_db()
        self.assertTrue(code.is_used)