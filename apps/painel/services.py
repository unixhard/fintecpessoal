"""Serviços de leitura do painel do dono — agregações baratas.

Todas as métricas usam ``values(...).annotate(...)`` para agregar no banco
(uma única query por painel, sem carregar linhas no Python). A base de dados
é o contador diário ``FeatureEvent``, �tima por construção: uma linha por
(usuario, recurso, dia) mantém o tamanho e o custo constantes no tempo.

Também expõe utilidades de monetização (config singleton e códigos).
"""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db.models import Count, Sum
from django.utils import timezone

from .models import AccessCode, FeatureEvent, MonetizationConfig

User = get_user_model()


# --------------------------------------------------------------------------- #
# Monetização
# --------------------------------------------------------------------------- #

def monetization() -> MonetizationConfig:
    return MonetizationConfig.get_singleton()


def create_access_codes(quantity: int, note: str = "", created_by=None):
    """Gera ``quantity`` códigos de acesso únicos."""
    import random
    import string

    alphabet = string.ascii_uppercase + string.digits
    created = []
    while len(created) < quantity:
        code = "FP-" + "".join(random.choices(alphabet, k=12))
        if not AccessCode.objects.filter(code__iexact=code).exists():
            created.append(
                AccessCode.objects.create(
                    code=code,
                    note=note.strip(),
                    created_by=created_by,
                )
            )
    return created


# --------------------------------------------------------------------------- #
# Telemetria — escrita
# --------------------------------------------------------------------------- #

# Slugs de telemetria aceitos (higiene de dados no beacon).
_TRACK_PREFIXES = ("nav.", "cta.", "chat.", "dashboard.")


def track_feature(user, feature: str) -> None:
    """Incrementa o contador diário de uma feature para o usuário.

    Escrita O(1): um upsert na linha (user, feature, date) usando ``F()``.
    Slugs fora de um prefixo conhecido são ignorados (higiene do dado).
    """
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
# Telemetria — leitura (agregações no banco)
# --------------------------------------------------------------------------- #

def _since(days):
    return timezone.localdate() - timedelta(days=max(days, 1) - 1)


def overview(days: int = 30) -> dict:
    """KPIs gerais do painel: usuários, atividade e monetização.

    Executa poucas queries agregadas indexadas — adequado para render inline.
    """
    since = _since(days)
    events_qs = FeatureEvent.objects.filter(date__gte=since)

    return {
        "total_users": User.objects.count(),
        "active_users": User.objects.filter(
            last_login__gte=timezone.now() - timedelta(days=days)
        ).count(),
        "new_users": User.objects.filter(
            date_joined__gte=timezone.now() - timedelta(days=days)
        ).count(),
        "paying_users": User.objects.filter(is_paying=True).count(),
        "events_total": events_qs.aggregate(total=Sum("count"))["total"] or 0,
        "events_users": events_qs.values("user").distinct().count(),
    }


def top_features(days: int = 30, limit: int = 12):
    """Recursos (opções/botãos) mais usados no período."""
    since = _since(days)
    return list(
        FeatureEvent.objects.filter(date__gte=since)
        .values("feature")
        .annotate(total=Sum("count"))
        .order_by("-total")[:limit]
    )


def top_users(days: int = 30, limit: int = 12):
    """Usuários mais ativos por nº de eventos no período (com perfil)."""
    since = _since(days)
    rows = (
        FeatureEvent.objects.filter(date__gte=since)
        .values("user")
        .annotate(total=Sum("count"), days_active=Count("date", distinct=True))
        .order_by("-total")[:limit]
    )
    ids = [r["user"] for r in rows]
    users = {u.id: u for u in User.objects.filter(id__in=ids)}
    result = []
    for r in rows:
        u = users.get(r["user"])
        if u is None:
            continue
        result.append(
            {
                "user": u,
                "events": r["total"],
                "days_active": r["days_active"],
            }
        )
    return result


def daily_series(days: int = 30):
    """Série diária de eventos (para o gráfico do painel)."""
    since = _since(days)
    return list(
        FeatureEvent.objects.filter(date__gte=since)
        .values("date")
        .annotate(total=Sum("count"))
        .order_by("date")
    )


def user_feature_breakdown(user, days: int = 0, limit: int = 20):
    """Quais recursos um usuário específico mais usou (0 = todo o período)."""
    qs = FeatureEvent.objects.filter(user=user)
    if days:
        qs = qs.filter(date__gte=_since(days))
    return list(
        qs.values("feature")
        .annotate(total=Sum("count"))
        .order_by("-total")[:limit]
    )


def user_activity_summary(user, days: int = 30) -> dict:
    """Resumo de atividade de um usuário específico (contagens baratas)."""
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