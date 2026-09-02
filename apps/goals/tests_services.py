"""Testes da camada de serviços de metas financeiras (Goal).

Cobrem criação (partindo de aporte zero), atualização, exclusão, contribuição
(marcador de progresso com limite no alvo e auto-conquista), transições de
status e isolamento multiusuário.
"""

from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.finance.services.errors import ForbiddenResourceError, InvalidAmountError, InvalidStateError

from .models import Goal
from .services.goals import (
    add_goal_contribution,
    create_goal,
    delete_goal,
    get_goal,
    get_goal_progress,
    get_goal_summary,
    set_goal_status,
    update_goal,
)

User = get_user_model()


class GoalServiceBase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="alice", password="x")
        self.other = User.objects.create_user(username="bob", password="y")


class GoalCreateTests(GoalServiceBase):
    def test_creates_goal_with_zero_initial_amount(self):
        goal = create_goal(
            user=self.user, name="Reserva", target_amount=100000
        )
        self.assertEqual(goal.owner_id, self.user.id)
        self.assertEqual(goal.current_amount, 0)
        self.assertEqual(goal.status, Goal.Status.ACTIVE)

    def test_rejects_non_positive_target(self):
        with self.assertRaises(InvalidAmountError):
            create_goal(user=self.user, name="Meta", target_amount=0)
        with self.assertRaises(InvalidAmountError):
            create_goal(user=self.user, name="Meta", target_amount=-5)

    def test_rejects_negative_current_amount(self):
        with self.assertRaises(InvalidAmountError):
            create_goal(
                user=self.user, name="Meta", target_amount=100, current_amount=-1
            )

    def test_rejects_blank_name(self):
        with self.assertRaises(ValueError):
            create_goal(user=self.user, name="   ", target_amount=100)


class GoalUpdateDeleteTests(GoalServiceBase):
    def setUp(self):
        super().setUp()
        self.goal = create_goal(user=self.user, name="Reserva", target_amount=100000)

    def test_update_other_users_goal_rejected(self):
        with self.assertRaises(ForbiddenResourceError):
            update_goal(user=self.other, goal=self.goal, name="X")

    def test_get_other_users_goal_rejected(self):
        with self.assertRaises(ForbiddenResourceError):
            get_goal(user=self.other, goal_id=self.goal.pk)

    def test_delete_other_users_goal_rejected(self):
        with self.assertRaises(ForbiddenResourceError):
            delete_goal(user=self.other, goal=self.goal)

    def test_update_recomputes_achieved(self):
        update_goal(user=self.user, goal=self.goal, target_amount=50)
        self.goal.refresh_from_db()
        # current(0) < 50 => permanece ativa na regra (0 < 50, não alcança).
        self.assertEqual(self.goal.status, Goal.Status.ACTIVE)


class GoalContributionTests(GoalServiceBase):
    def setUp(self):
        super().setUp()
        self.goal = create_goal(user=self.user, name="Viagem", target_amount=10000)

    def test_contribution_accumulates(self):
        add_goal_contribution(user=self.user, goal=self.goal, amount=3000)
        self.goal.refresh_from_db()
        self.assertEqual(self.goal.current_amount, 3000)
        self.assertEqual(self.goal.status, Goal.Status.ACTIVE)

    def test_contribution_triggers_achieved(self):
        add_goal_contribution(user=self.user, goal=self.goal, amount=12000)
        self.goal.refresh_from_db()
        # Caps no alvo, nunca excede.
        self.assertEqual(self.goal.current_amount, 10000)
        self.assertEqual(self.goal.status, Goal.Status.ACHIEVED)

    def test_contribution_to_achieved_goal_rejected(self):
        add_goal_contribution(user=self.user, goal=self.goal, amount=10000)
        with self.assertRaises(InvalidStateError):
            add_goal_contribution(user=self.user, goal=self.goal, amount=1)

    def test_contribution_to_archived_goal_rejected(self):
        set_goal_status(user=self.user, goal=self.goal, status=Goal.Status.ARCHIVED)
        with self.assertRaises(InvalidStateError):
            add_goal_contribution(user=self.user, goal=self.goal, amount=100)

    def test_contribution_rejects_non_positive(self):
        with self.assertRaises(InvalidAmountError):
            add_goal_contribution(user=self.user, goal=self.goal, amount=0)

    def test_contribution_to_other_users_goal_rejected(self):
        with self.assertRaises(ForbiddenResourceError):
            add_goal_contribution(user=self.other, goal=self.goal, amount=100)


class GoalStatusTests(GoalServiceBase):
    def setUp(self):
        super().setUp()
        self.goal = create_goal(user=self.user, name="Meta", target_amount=10000)

    def test_pause_activate_archive(self):
        set_goal_status(user=self.user, goal=self.goal, status=Goal.Status.PAUSED)
        self.goal.refresh_from_db()
        self.assertEqual(self.goal.status, Goal.Status.PAUSED)

        set_goal_status(user=self.user, goal=self.goal, status=Goal.Status.ACTIVE)
        self.goal.refresh_from_db()
        self.assertEqual(self.goal.status, Goal.Status.ACTIVE)

        set_goal_status(user=self.user, goal=self.goal, status=Goal.Status.ARCHIVED)
        self.goal.refresh_from_db()
        self.assertEqual(self.goal.status, Goal.Status.ARCHIVED)

    def test_cannot_set_achieved_manually(self):
        with self.assertRaises(InvalidStateError):
            set_goal_status(user=self.user, goal=self.goal, status=Goal.Status.ACHIEVED)


class GoalProgressTests(GoalServiceBase):
    def test_progress_percent_and_required_monthly(self):
        goal = create_goal(
            user=self.user, name="Meta", target_amount=12000,
            target_date=date(2026, 12, 31),
        )
        # forçamos evolução para ter valor acumulado sem criar histórico longo
        add_goal_contribution(user=self.user, goal=goal, amount=3000)
        p = get_goal_progress(user=self.user, goal=goal, ref_date=date(2026, 9, 1))
        self.assertEqual(p["percent"], 25)
        self.assertEqual(p["remaining"], 9000)
        self.assertIsNotNone(p["required_monthly"])

    def test_projection_none_without_one_month_sample(self):
        goal = create_goal(
            user=self.user, name="Meta", target_amount=12000,
            target_date=date(2026, 12, 31),
        )
        add_goal_contribution(user=self.user, goal=goal, amount=3000)
        p = get_goal_progress(user=self.user, goal=goal, ref_date=date(2026, 9, 1))
        # A meta acabou de ser criada (sem 1 mês de amostra) => sem projeção.
        self.assertIsNone(p["projected_completion"])


class GoalSummaryTests(GoalServiceBase):
    def test_empty_summary(self):
        s = get_goal_summary(user=self.user)
        self.assertEqual(s["total_target"], 0)
        self.assertEqual(s["goals"], [])

    def test_summary_totals(self):
        create_goal(user=self.user, name="A", target_amount=10000)
        create_goal(user=self.user, name="B", target_amount=20000)
        s = get_goal_summary(user=self.user)
        self.assertEqual(s["total_target"], 30000)
        self.assertEqual(len(s["goals"]), 2)
