"""Serviços do Painel do Dono — telemetria, monetização e vendas.

Todas as métricas de receita/MRR/churn usam ``values().annotate(...)`` para
agregar no banco. As operações de escrita (grant/cancel/renew, record_payment)
validam invariants e mantêm ``user.is_paying`` consistente.
"""

import random
import string
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db.models import Count, F, Q, Sum
from django.utils import timezone

from .models import (
    AccessCode,
    Coupon,
    FeatureEvent,
    MonetizationConfig,
    Payment,
    Plan,
    Subscription,
)

User = get_user_model()


# --------------------------------------------------------------------------- #
# Monetização
# --------------------------------------------------------------------------- #

def monetization() -> MonetizationConfig:
    return MonetizationConfig.get_singleton()


def create_access_codes(quantity: int, note: str = "", created_by=None, plan=None):
    """Gera ``quantity`` códigos de acesso únicos, opcionalmente ligados a um plano."""
    alphabet = string.ascii_uppercase + string.digits
    created = []
    while len(created) < quantity:
        code = "FP-" + "".join(random.choices(alphabet, k=12))
        if not AccessCode.objects.filter(code__iexact=code).exists():
            created.append(
                AccessCode.objects.create(
                    code=code,
                    plan=plan,
                    note=note.strip(),
                    created_by=created_by,
                )
            )
    return created


# --------------------------------------------------------------------------- #
# Assinaturas
# --------------------------------------------------------------------------- #

def grant_subscription(user, plan, *, status=Subscription.ACTIVE, notes="", started_at=None):
    """Concede uma assinatura ao usuário e atualiza ``is_paying``."""
    if plan is None:
        return None
    started_at = started_at or timezone.now()
    expires_at = None
    if not plan.is_lifetime and plan.duration_days:
        expires_at = started_at + timedelta(days=plan.duration_days)
    sub = Subscription.objects.create(
        user=user,
        plan=plan,
        status=status,
        started_at=started_at,
        expires_at=expires_at,
        notes=notes,
    )
    _sync_is_paying(user)
    return sub


def cancel_subscription(sub, when=None):
    """Cancela uma assinatura ativa."""
    sub.status = Subscription.CANCELED
    sub.canceled_at = when or timezone.now()
    sub.save(update_fields=["status", "canceled_at"])
    _sync_is_paying(sub.user)
    return sub


def renew_subscription(sub):
    """Renova uma assinatura (cria nova a partir da data de expiração)."""
    start = sub.expires_at or timezone.now()
    return grant_subscription(
        sub.user, sub.plan, notes=f"Renovação de #{sub.pk}"
    )


def expire_due_subscriptions():
    """Expira assinaturas cujo prazo venceu. Retorna número de afetadas."""
    now = timezone.now()
    expired = Subscription.objects.filter(
        status__in=(Subscription.ACTIVE, Subscription.TRIAL),
        expires_at__isnull=False,
        expires_at__lt=now,
    )
    affected_ids = set(expired.values_list("user_id", flat=True))
    count = expired.update(status=Subscription.EXPIRED)
    for uid in affected_ids:
        try:
            _sync_is_paying(User.objects.get(pk=uid))
        except User.DoesNotExist:
            pass
    return count


def _sync_is_paying(user):
    """Atualiza ``user.is_paying`` com base em suas assinaturas ativas."""
    has_active = Subscription.objects.filter(
        user=user, status__in=(Subscription.ACTIVE, Subscription.TRIAL),
    ).filter(
        Q(expires_at__isnull=True) | Q(expires_at__gte=timezone.now()),
    ).exists()
    if user.is_paying != has_active:
        user.is_paying = has_active
        user.save(update_fields=["is_paying"])


def active_subscriptions_qs():
    """Queryset de assinaturas vigentes (ativas/trial e não expiradas)."""
    now = timezone.now()
    return Subscription.objects.filter(
        status__in=(Subscription.ACTIVE, Subscription.TRIAL),
    ).filter(
        Q(expires_at__isnull=True) | Q(expires_at__gte=now),
    )


# --------------------------------------------------------------------------- #
# Pagamentos
# --------------------------------------------------------------------------- #

def record_payment(user, *, amount, method=Payment.PIX, plan=None, subscription=None,
                   coupon=None, notes="", created_by=None):
    """Registra um pagamento pendente. Retorna instância criada."""
    amount = Decimal(amount or 0)
    discount = Decimal("0")
    if coupon and coupon.is_valid and plan:
        original = Decimal(plan.price or amount)
        final = coupon.apply_to(original)
        discount = original - final
    return Payment.objects.create(
        user=user,
        plan=plan,
        subscription=subscription,
        coupon=coupon,
        amount=amount,
        discount=discount,
        method=method,
        status=Payment.PENDING,
        notes=notes.strip(),
        created_by=created_by,
    )


def mark_payment_paid(payment, when=None):
    """Marca pagamento como pago; se houver plano vinculado, gera assinatura."""
    payment.mark_paid(when)
    if payment.plan_id and payment.user_id:
        sub = grant_subscription(
            payment.user, payment.plan,
            notes=f"Pagamento #{payment.pk}",
        )
        payment.subscription = sub
        payment.save(update_fields=["subscription"])
    if payment.coupon_id:
        Coupon.objects.filter(pk=payment.coupon_id).update(
            times_used=F("times_used") + 1
        )
    return payment


def refund_payment(payment, when=None):
    payment.status = Payment.REFUNDED
    payment.save(update_fields=["status"])
    return payment


# --------------------------------------------------------------------------- #
# Telemetria — escrita
# --------------------------------------------------------------------------- #

_TRACK_PREFIXES = ("nav.", "cta.", "chat.", "dashboard.")


def track_feature(user, feature: str) -> None:
    feature = (feature or "").strip().lower()[:64]
    if not feature or not feature.startswith(_TRACK_PREFIXES):
        return
    row, created = FeatureEvent.objects.get_or_create(
        user=user,
        feature=feature,
        date=timezone.localdate(),
        defaults={"count": 0},
    )
    if not created:
        FeatureEvent.objects.filter(pk=row.pk).update(count=row.count + 1)
    else:
        FeatureEvent.objects.filter(pk=row.pk).update(count=1)


def track_features(user, features: list) -> None:
    for feature in features or []:
        track_feature(user, feature)


# --------------------------------------------------------------------------- #
# Telemetria — leitura (agregações)
# --------------------------------------------------------------------------- #

def _since(days):
    return timezone.localdate() - timedelta(days=max(days, 1) - 1)


def overview(days: int = 30) -> dict:
    since = _since(days)
    events_qs = FeatureEvent.objects.filter(date__gte=since)
    active_sub_qs = active_subscriptions_qs()
    return {
        "total_users": User.objects.count(),
        "active_users": User.objects.filter(
            last_login__gte=timezone.now() - timedelta(days=days)
        ).count(),
        "new_users": User.objects.filter(
            date_joined__gte=timezone.now() - timedelta(days=days)
        ).count(),
        "paying_users": User.objects.filter(is_paying=True).count(),
        "active_subscriptions": active_sub_qs.count(),
        "expiring_soon": active_sub_qs.filter(
            expires_at__isnull=False,
            expires_at__lte=timezone.now() + timedelta(days=7),
            expires_at__gte=timezone.now(),
        ).count(),
        "events_total": events_qs.aggregate(total=Sum("count"))["total"] or 0,
        "events_users": events_qs.values("user").distinct().count(),
    }


def top_features(days: int = 30, limit: int = 12):
    since = _since(days)
    return list(
        FeatureEvent.objects.filter(date__gte=since)
        .values("feature")
        .annotate(total=Sum("count"))
        .order_by("-total")[:limit]
    )


def top_users(days: int = 30, limit: int = 12):
    since = _since(days)
    rows = (
        FeatureEvent.objects.filter(date__gte=since)
        .values("user")
        .annotate(total=Sum("count"), days_active=Count("date", distinct=True))
        .order_by("-total")[:limit]
    )
    ids = [r["user"] for r in rows]
    users = {u.id: u for u in User.objects.filter(id__in=ids)}
    return [
        {"user": users[r["user"]], "events": r["total"], "days_active": r["days_active"]}
        for r in rows if r["user"] in users
    ]


def daily_series(days: int = 30):
    since = _since(days)
    return list(
        FeatureEvent.objects.filter(date__gte=since)
        .values("date")
        .annotate(total=Sum("count"))
        .order_by("date")
    )


def user_feature_breakdown(user, days: int = 0, limit: int = 20):
    qs = FeatureEvent.objects.filter(user=user)
    if days:
        qs = qs.filter(date__gte=_since(days))
    return list(
        qs.values("feature")
        .annotate(total=Sum("count"))
        .order_by("-total")[:limit]
    )


def user_activity_summary(user, days: int = 30) -> dict:
    from django.apps import apps
    since = _since(days)
    summary = {
        "events": FeatureEvent.objects.filter(user=user).aggregate(
            total=Sum("count")
        )["total"]
        or 0,
        "events_30d": FeatureEvent.objects.filter(user=user, date__gte=since)
        .aggregate(total=Sum("count"))["total"]
        or 0,
    }
    counts = {}
    for label, app, model, field in (
        ("transactions", "finance", "Transaction", "owner"),
        ("accounts", "finance", "Account", "owner"),
        ("cards", "cards", "CreditCard", "owner"),
        ("budgets", "budgets", "Budget", "owner"),
        ("goals", "goals", "Goal", "owner"),
        ("debts", "debts", "Debt", "owner"),
        ("invoices", "cards", "CreditCardInvoice", "owner"),
        ("imports", "imports", "ImportBatch", "owner"),
    ):
        try:
            m = apps.get_model(app, model)
            counts[label] = m.objects.filter(**{field: user}).count()
        except Exception:
            counts[label] = 0
    summary.update(counts)
    return summary


# --------------------------------------------------------------------------- #
# Relatórios de vendas
# --------------------------------------------------------------------------- #

def revenue_summary(days: int = 30) -> dict:
    """Receita total, do período e Ticket Médio (pagos)."""
    since = _since(days)
    paid = Payment.objects.filter(status=Payment.PAID)
    total = paid.aggregate(s=Sum("amount"))["s"] or Decimal("0")
    period = paid.filter(paid_at__date__gte=since).aggregate(
        s=Sum("amount"), d=Sum("discount")
    )
    period_amount = period["s"] or Decimal("0")
    period_discount = period["d"] or Decimal("0")
    period_count = paid.filter(paid_at__date__gte=since).count()
    ticket = (period_amount / Decimal(period_count)) if period_count else Decimal("0")
    return {
        "total": total,
        "period_amount": period_amount,
        "period_discount": period_discount,
        "period_count": period_count,
        "ticket": ticket.quantize(Decimal("0.01")),
    }


def mrr():
    """MRR — receita recorrente mensal estimada (soma do valor mensal de assinaturas ativas)."""
    from django.db.models import Q
    subs = Subscription.objects.filter(
        status__in=(Subscription.ACTIVE, Subscription.TRIAL),
        plan__isnull=False,
    ).filter(
        Q(expires_at=None) | Q(expires_at__gte=timezone.now()),
    ).select_related("plan")
    total = Decimal("0")
    for s in subs:
        total += s.plan.monthly_value
    return total.quantize(Decimal("0.01"))


def arr():
    """ARR = MRR × 12."""
    return (mrr() * Decimal("12")).quantize(Decimal("0.01"))


def revenue_by_plan(days: int = 30):
    since = _since(days)
    return list(
        Payment.objects.filter(status=Payment.PAID, paid_at__date__gte=since)
        .values("plan__name")
        .annotate(total=Sum("amount"), count=Count("pk"))
        .order_by("-total")
    )


def revenue_by_method(days: int = 30):
    since = _since(days)
    return list(
        Payment.objects.filter(status=Payment.PAID, paid_at__date__gte=since)
        .values("method")
        .annotate(total=Sum("amount"), count=Count("pk"))
        .order_by("-total")
    )


def churn_rate(days: int = 30):
    """Taxa de churn = canceladas/expiradas no período / total de assinaturas no início do período."""
    since = _since(days)
    start = Subscription.objects.filter(created_at__date__lt=since).count() or 1
    lost = Subscription.objects.filter(
        status__in=(Subscription.EXPIRED, Subscription.CANCELED),
        updated_at__date__gte=since,
    ).count()
    return (Decimal(lost) / Decimal(start) * Decimal("100")).quantize(Decimal("0.1"))


def conversion_rate():
    total = User.objects.count() or 1
    paying = User.objects.filter(is_paying=True).count()
    return (Decimal(paying) / Decimal(total) * Decimal("100")).quantize(Decimal("0.1"))


def new_subscribers_series(days: int = 30):
    since = _since(days)
    return list(
        Subscription.objects.filter(created_at__date__gte=since)
        .values("created_at__date")
        .annotate(total=Count("pk"))
        .order_by("created_at__date")
    )


def top_customers(days: int = 30, limit: int = 15):
    """Top clientes por valor total pago no período."""
    since = _since(days)
    return list(
        Payment.objects.filter(status=Payment.PAID, paid_at__date__gte=since)
        .values("user")
        .annotate(total=Sum("amount"), count=Count("pk"))
        .order_by("-total")[:limit]
    )


def user_payments(user):
    return list(Payment.objects.filter(user=user).order_by("-created_at")[:50])


def user_ltv(user):
    """Lifetime Value — valor total já pago."""
    return (
        Payment.objects.filter(user=user, status=Payment.PAID)
        .aggregate(s=Sum("amount"))["s"]
        or Decimal("0")
    )


def user_subscription(user):
    """Assinatura ativa/vigente do usuário (ou None)."""
    from django.db.models import Q
    return (
        Subscription.objects.filter(user=user)
        .filter(status__in=(Subscription.ACTIVE, Subscription.TRIAL))
        .filter(Q(expires_at=None) | Q(expires_at__gte=timezone.now()))
        .select_related("plan")
        .first()
    )
