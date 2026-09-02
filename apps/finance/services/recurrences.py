"""Serviço de recorrência: transforma uma regra em ocorrência real.

A regra NUNCA gera transações em massa no banco (decisão D8 do domínio). Uma
ocorrência é materializada pontualmente — sob demanda ou de forma agendada —
como um único Transaction vinculado à regra.
"""

from datetime import date

from django.db import transaction as db_transaction

from ..models import Account, Category, RecurringRule, Transaction
from .base import ensure_owned_integer_amount, require_owned
from .errors import InvalidStateError, InvalidAmountError

_UNSET = object()


def _clamp_day(year, month, day):
    """Ajusta o dia para caber no mês (ex.: 31 em fevereiro -> último dia)."""
    from calendar import monthrange

    return min(day, monthrange(year, month)[1])


def occurrence_date(rule, target_date):
    """Calcula a DATA da ocorrência da regra que corresponde a ``target_date``.

    Mensal : dia = ``day_of_month`` (ou dia do start_date); mês/ano de target.
    Semanal: dia da semana = ``weekday`` (ou weekday do start_date) na semana
             que contém ``target_date``.
    Anual  : mês/dia do start_date (ou day_of_month) no ano de ``target_date``.
    """
    sd = rule.start_date
    if rule.frequency == RecurringRule.Frequency.MONTHLY or (
        rule.frequency == RecurringRule.Frequency.CUSTOM and rule.day_of_month
    ):
        day = rule.day_of_month or sd.day
        day = _clamp_day(target_date.year, target_date.month, day)
        return target_date.replace(day=day)
    if rule.frequency == RecurringRule.Frequency.WEEKLY:
        target_weekday = rule.weekday if rule.weekday is not None else sd.weekday()
        days_ahead = (target_weekday - target_date.weekday()) % 7
        return target_date.fromordinal(target_date.toordinal() + days_ahead)
    if rule.frequency == RecurringRule.Frequency.YEARLY:
        month = sd.month
        day = _clamp_day(target_date.year, month, sd.day)
        return date(target_date.year, month, day)
    # CUSTOM sem day_of_month: assume mensal a partir do start_date.
    day = _clamp_day(target_date.year, target_date.month, sd.day)
    return target_date.replace(day=day)


def generate_occurrence(*, user, rule, target_date, description=""):
    """Materializa a ocorrência de ``rule`` para ``target_date``.

    - Valida ownership da regra.
    - Valida o estado (ativa) e o intervalo de datas (start/end).
    - Calcula a data da ocorrência e a cria como Transaction, vinculando
      ``recurrence = rule``.
    - Proteção anti-duplicação: se já existe uma Transação para a mesma regra
      e mesma data de ocorrência, não cria outra — retorna a existente
      (operando de forma idempotente).
    """
    require_owned(
        RecurringRule.objects, user, model_label="Regra recorrente", object_id=rule.pk
    )

    if rule.status != RecurringRule.Status.ACTIVE:
        raise InvalidStateError("A regra recorrente não está ativa.")

    occurrence = occurrence_date(rule, target_date)

    if rule.start_date and occurrence < rule.start_date:
        raise InvalidStateError("A data da ocorrência é anterior ao início da regra.")
    if rule.end_date and occurrence > rule.end_date:
        raise InvalidStateError("A data da ocorrência é posterior ao fim da regra.")

    existing = (
        Transaction.objects.for_user(user)
        .filter(recurrence=rule, date=occurrence)
        .first()
    )
    if existing is not None:
        return existing

    title = description or rule.title
    with db_transaction.atomic():
        created = Transaction.objects.create(
            owner=user,
            type=(
                Transaction.Type.EXPENSE
                if rule.kind == RecurringRule.Kind.EXPENSE
                else Transaction.Type.INCOME
            ),
            amount=rule.amount,
            date=occurrence,
            description=title,
            account=rule.account,
            category=rule.category,
            recurrence=rule,
            source=Transaction.Source.RECURRENCE,
        )
    return created


def _resolve_owned(model, user, obj, label):
    if obj is None:
        return None
    require_owned(model.objects, user, model_label=label, object_id=obj.pk)
    return obj


def create_rule(
    *,
    user,
    kind,
    title,
    amount,
    frequency,
    start_date,
    account=None,
    category=None,
    card=None,
    end_date=None,
    day_of_month=None,
    weekday=None,
    interval=1,
):
    """Cria uma regra de recorrência do usuário.

    Valida ownership de conta/categoria/cartão e as regras de domínio do model
    (despesa exige conta ou cartão; receita exige conta).
    """
    title = (title or "").strip()
    if not title:
        raise ValueError("título da recorrência é obrigatório.")
    amount = ensure_owned_integer_amount(amount, field="valor")
    if isinstance(interval, bool) or not isinstance(interval, int) or interval < 1:
        raise InvalidAmountError("Intervalo inválido.")

    account = _resolve_owned(Account, user, account, "Conta")
    category = _resolve_owned(Category, user, category, "Categoria")
    if card is not None:
        from apps.cards.models import CreditCard

        card = _resolve_owned(CreditCard, user, card, "Cartão")

    rule = RecurringRule(
        owner=user,
        kind=kind,
        title=title,
        amount=amount,
        frequency=frequency,
        start_date=start_date,
        account=account,
        category=category,
        card=card,
        end_date=end_date,
        day_of_month=day_of_month,
        weekday=weekday,
        interval=interval or 1,
        status=RecurringRule.Status.ACTIVE,
    )
    rule.full_clean()
    rule.save()
    return rule


def update_rule(
    *,
    user,
    rule,
    title=None,
    amount=None,
    frequency=None,
    start_date=None,
    account=_UNSET,
    category=_UNSET,
    card=_UNSET,
    end_date=None,
    day_of_month=None,
    weekday=None,
    interval=None,
):
    """Atualiza uma regra de recorrência do usuário (ownership validado).

    Campos de referência (conta/categoria/cartão) com sentinela ``_UNSET`` só
    são aplicados quando informados; omissão mantém o valor atual.
    """
    require_owned(
        RecurringRule.objects, user, model_label="Regra recorrente",
        object_id=getattr(rule, "pk", None),
    )
    if title is not None:
        title = (title or "").strip()
        if not title:
            raise ValueError("título da recorrência é obrigatório.")
        rule.title = title
    if amount is not None:
        rule.amount = ensure_owned_integer_amount(amount, field="valor")
    if frequency is not None:
        rule.frequency = frequency
    if start_date is not None:
        rule.start_date = start_date
    if end_date is not None:
        rule.end_date = end_date
    if day_of_month is not None:
        rule.day_of_month = day_of_month
    if weekday is not None:
        rule.weekday = weekday
    if interval is not None:
        if isinstance(interval, bool) or not isinstance(interval, int) or interval < 1:
            raise InvalidAmountError("Intervalo inválido.")
        rule.interval = interval
    _apply_targets(rule, user, account=account, category=category, card=card)
    rule.full_clean()
    rule.save()
    return rule


def _apply_targets(rule, user, *, account=_UNSET, category=_UNSET, card=_UNSET):
    """Reaplica as referências opcionais (conta/categoria/cartão) com ownership."""
    if account is not _UNSET:
        rule.account = _resolve_owned(Account, user, account, "Conta")
    if category is not _UNSET:
        rule.category = _resolve_owned(Category, user, category, "Categoria")
    if card is not _UNSET:
        _set_card(rule, user, card)


def _set_card(rule, user, card):
    if card is None:
        rule.card = None
        return
    from apps.cards.models import CreditCard

    rule.card = _resolve_owned(CreditCard, user, card, "Cartão")


def set_rule_status(*, user, rule, status):
    """Pausa, reativa ou encerra uma regra (ownership validado)."""
    require_owned(
        RecurringRule.objects, user, model_label="Regra recorrente",
        object_id=getattr(rule, "pk", None),
    )
    if status not in (
        RecurringRule.Status.ACTIVE,
        RecurringRule.Status.PAUSED,
        RecurringRule.Status.ENDED,
    ):
        raise InvalidStateError("Status inválido para a regra recorrente.")
    rule.status = status
    rule.save()
    return rule
