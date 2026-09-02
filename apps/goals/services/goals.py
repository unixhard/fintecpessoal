"""Serviços de metas financeiras (Goal).

Regras financeiras permanecem nesta camada. A meta acumula em
``Goal.current_amount`` (rastreador de progresso); o movimento financeiro real
de aporte é feito na camada de contas/transações existente (não se cria
segunda contabilidade paralela). A contribuição aqui é o marcador de progresso,
validado apenas por ownership e valor.
"""

from datetime import date

from django.utils.timezone import localdate as tz_localdate

from apps.finance.services.base import require_owned
from apps.finance.services.errors import InvalidAmountError, InvalidStateError

from ..models import Goal


def _require_goal(user, goal):
    require_owned(
        Goal.objects, user, model_label="Meta",
        object_id=getattr(goal, "pk", None),
    )
    return goal


def _validate_amount(amount, *, allow_zero=False):
    if isinstance(amount, bool) or not isinstance(amount, int):
        raise InvalidAmountError("valor deve ser um inteiro em centavos.")
    if allow_zero:
        if amount < 0:
            raise InvalidAmountError("valor não pode ser negativo.")
    elif amount <= 0:
        raise InvalidAmountError("valor deve ser maior que zero.")
    return amount


def create_goal(
    *,
    user,
    name,
    target_amount,
    priority=Goal.Priority.MEDIUM,
    target_date=None,
    current_amount=0,
    notes="",
):
    """Cria uma meta pertencente ao usuário.

    O valor objetivo deve ser > 0. O valor atual inicial é >= 0.
    """
    name = (name or "").strip()
    if not name:
        raise ValueError("nome da meta é obrigatório.")
    current_amount = _validate_amount(current_amount or 0, allow_zero=True)
    target_amount = _validate_amount(target_amount)
    if target_amount <= 0:
        raise InvalidAmountError("valor objetivo deve ser maior que zero.")
    # Nascida já alcançada se o valor atual inicial cobre o objetivo.
    status = Goal.Status.ACHIEVED if current_amount >= target_amount else Goal.Status.ACTIVE
    return Goal.objects.create(
        owner=user,
        name=name,
        target_amount=target_amount,
        current_amount=current_amount,
        target_date=target_date,
        priority=priority,
        status=status,
        notes=notes or "",
    )


def update_goal(
    *,
    user,
    goal,
    name=None,
    target_amount=None,
    priority=None,
    target_date=None,
    notes=None,
):
    """Atualiza campos editáveis de uma meta (ownership validado).

    Se o valor objetivo mudar, o status de alcançada é recalculado.
    """
    _require_goal(user, goal)
    if name is not None:
        name = (name or "").strip()
        if not name:
            raise ValueError("nome da meta é obrigatório.")
        goal.name = name
    if target_amount is not None:
        goal.target_amount = _validate_amount(target_amount)
    if priority is not None:
        goal.priority = priority
    if target_date is not None:
        goal.target_date = target_date
    if notes is not None:
        goal.notes = notes or ""
    if goal.status == Goal.Status.ACHIEVED and goal.current_amount < goal.target_amount:
        goal.status = Goal.Status.ACTIVE
    if goal.current_amount >= goal.target_amount and goal.status != Goal.Status.ACHIEVED:
        goal.status = Goal.Status.ACHIEVED
    goal.save()
    return goal


def delete_goal(*, user, goal):
    """Exclui uma meta (ownership validado)."""
    _require_goal(user, goal)
    goal.delete()


def get_goal(*, user, goal_id):
    """Retorna a meta do usuário ou sobe ForbiddenResourceError."""
    return require_owned(Goal.objects, user, model_label="Meta", object_id=goal_id)


def get_goals(*, user, statuses=None):
    """Lista metas do usuário (ativas/pausadas por padrão)."""
    qs = Goal.objects.for_user(user)
    if statuses is not None:
        qs = qs.filter(status__in=statuses)
    else:
        qs = qs.filter(
            status__in=[Goal.Status.ACTIVE, Goal.Status.PAUSED]
        )
    return qs.order_by("-priority", "target_date", "name")


def set_goal_status(*, user, goal, status):
    """Altera o status de uma meta (ativo/pausado/arquivado).

    `achieved` é derivado automaticamente por contribuição/edição; este fluxo
    permite pausar, reativar e arquivar.
    """
    _require_goal(user, goal)
    allowed = {
        Goal.Status.ACTIVE,
        Goal.Status.PAUSED,
        Goal.Status.ARCHIVED,
    }
    if status not in allowed:
        raise InvalidStateError("Status inválido para esta operação.")
    goal.status = status
    goal.save()
    return goal


def add_goal_contribution(*, user, goal, amount, ref_date=None):
    """Adiciona um aporte à meta (marcador de progresso, ownership validado).

    O movimento financeiro real é feito na camada de contas/transações; aqui
    apenas acumulamos o valor na meta. Ao atingir o objetivo, a meta passa a
    ACHIEVED automaticamente e não aceita novos aportes (sem exceder o alvo).
    """
    _require_goal(user, goal)
    amount = _validate_amount(amount)
    if goal.status == Goal.Status.ACHIEVED:
        raise InvalidStateError("A meta já foi alcançada.")
    if goal.status == Goal.Status.ARCHIVED:
        raise InvalidStateError("Não é possível contribuir para uma meta arquivada.")
    goal.current_amount = goal.current_amount + amount
    if goal.current_amount >= goal.target_amount:
        goal.current_amount = goal.target_amount
        goal.status = Goal.Status.ACHIEVED
    goal.save()
    return goal


def get_goal_progress(*, user, goal, ref_date=None):
    """Progresso de uma meta: acumulado, restante, percentual, prazo e ritmo.

    - `required_monthly`: quanto por mês é necessário para atingir no prazo
      (só quando existe `target_date` e ainda não foi alcançada).
    - `projected_completion`: estimativa de conclusão baseada no ritmo atual.
      Só é emitida quando há base suficiente (ritmo mensal observável); caso
      contrário fica `None` (evita previsão artificial).
    """
    _require_goal(user, goal)
    ref_date = ref_date or tz_localdate()
    target = goal.target_amount
    current = goal.current_amount
    remaining = max(target - current, 0)
    percent = goal.progress_percent

    required_monthly = None
    projected_completion = None
    if (
        goal.target_date
        and goal.status == Goal.Status.ACTIVE
        and remaining > 0
    ):
        months_left = _months_between(ref_date, goal.target_date)
        if months_left > 0:
            required_monthly = _ceil_div(remaining, months_left)
        # Projeção por ritmo acumulado desde a criação da meta: só emite quando
        # `created_at` aponta para um período >= 1 mês com aporte observável.
        observed = _observed_monthly_pace(goal, ref_date)
        if observed and observed > 0 and months_left and months_left >= 0:
            projected_completion = _projected_date(goal, observed, ref_date)

    status = "achieved" if goal.status == Goal.Status.ACHIEVED else goal.status
    return {
        "goal": goal,
        "target_amount": target,
        "current_amount": current,
        "remaining": remaining,
        "percent": percent,
        "target_date": goal.target_date,
        "status": status,
        "required_monthly": required_monthly,
        "projected_completion": projected_completion,
        "ref_date": ref_date,
    }


def get_goal_summary(*, user, ref_date=None):
    """Resumo das metas ativas/pausadas do usuário.

    - total_target, total_current, total_remaining, overall_percent;
    - active: metas ativas;
    - near_target: metas com percentual >= 90% (passíveis de conclusão breve);
    - overdue: metas ativas com prazo vencido e ainda não alcançadas;
    - closest_deadline: meta ativa com prazo mais próximo (se houver).
    """
    goals = list(
        get_goals(user=user, statuses=[Goal.Status.ACTIVE, Goal.Status.PAUSED])
    )
    if not goals:
        return {
            "goals": [], "rows": [],
            "total_target": 0, "total_current": 0,
            "total_remaining": 0, "overall_percent": 0,
            "active": [], "near_target": [], "overdue": [],
            "closest_deadline": None,
        }
    rows = [
        get_goal_progress(user=user, goal=g, ref_date=ref_date) for g in goals
    ]
    total_target = sum(g.target_amount for g in goals)
    total_current = sum(g.current_amount for g in goals)
    overall = int(round(total_current / total_target * 100)) if total_target else 0
    active = [r for r in rows if r["status"] == "active"]
    near_target = [r for r in rows if r["status"] == "active" and r["percent"] >= 90]
    ref_date = ref_date or tz_localdate()
    overdue = [
        r for r in rows
        if r["status"] == "active"
        and r["target_date"] and r["target_date"] < ref_date
        and r["remaining"] > 0
    ]
    with_deadline = [r for r in rows if r["status"] == "active" and r["target_date"]]
    closest = (
        min(with_deadline, key=lambda r: r["target_date"]) if with_deadline else None
    )
    return {
        "goals": goals,
        "rows": rows,
        "total_target": total_target,
        "total_current": total_current,
        "total_remaining": max(total_target - total_current, 0),
        "overall_percent": overall,
        "active": active,
        "near_target": near_target,
        "overdue": overdue,
        "closest_deadline": closest,
    }


def _months_between(start: date, end: date) -> int:
    """Meses cheios entre duas datas (arredonda para baixo)."""
    months = (end.year - start.year) * 12 + (end.month - start.month)
    if end.day < start.day:
        months -= 1
    return max(months, 0)


def _ceil_div(a: int, b: int) -> int:
    return -(-a // b) if b else 0


def _observed_monthly_pace(goal, ref_date):
    """Aporte mensal observado desde a criação da meta (centavos/mês).

    Só retorna valor se a meta existe há pelo menos 1 mês (amostra suficiente);
    caso contrário `None` — evitando projeção artificial.
    """
    if not goal.created_at:
        return None
    since = tz_localdate(goal.created_at)
    months = _months_between(since, ref_date)
    if months < 1:
        return None
    if goal.current_amount <= 0:
        return None
    return _ceil_div(goal.current_amount, months)


def _projected_date(goal, pace, ref_date):
    """Estimativa de conclusão mantendo o ritmo observado (nunca antes de hoje)."""
    remaining = max(goal.target_amount - goal.current_amount, 0)
    if remaining <= 0 or pace <= 0:
        return ref_date
    months_needed = _ceil_div(remaining, pace)
    if months_needed <= 0:
        return ref_date
    year = ref_date.year
    month = ref_date.month + months_needed
    while month > 12:
        month -= 12
        year += 1
    from calendar import monthrange

    day = min(ref_date.day, monthrange(year, month)[1])
    return date(year, month, day)
