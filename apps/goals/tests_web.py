"""Testes web do módulo de metas financeiras (views, ownership e HTML).

Cobrem o fluxo: listar/criar/editar/detalhar, registrar aporte, pausar/
reativar/arquivar/excluir, isolamento multiusuário e redirecionamento de
anônimos — sempre via services.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import Goal
from .services.goals import create_goal

User = get_user_model()


class GoalWebTestBase(TestCase):
    def setUp(self):
        self.alice = User.objects.create_user(
            username="alice", password="senha123", first_name="Alice"
        )
        self.bob = User.objects.create_user(
            username="bob", password="senha123", first_name="Bob"
        )
        self.login_as(self.alice)

    def login_as(self, user):
        self.client.login(username=user.username, password="senha123")

    def make_goal(self, owner=None, **kwargs):
        owner = owner or self.alice
        defaults = {"name": "Reserva", "target_amount": 100000}
        defaults.update(kwargs)
        return create_goal(user=owner, **defaults)


class GoalListViewTests(GoalWebTestBase):
    def test_anonymous_redirected_to_login(self):
        self.client.logout()
        resp = self.client.get(reverse("goals:goal_list"))
        self.assertEqual(resp.status_code, 302)

    def test_authenticated_lists_only_own_goals(self):
        self.make_goal(owner=self.alice, name="Minha Meta")
        self.make_goal(owner=self.bob, name="Meta do Bob")
        resp = self.client.get(reverse("goals:goal_list"))
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode()
        self.assertIn("Minha Meta", content)
        self.assertNotIn("Meta do Bob", content)


class GoalCreateEditTests(GoalWebTestBase):
    def test_create_goal(self):
        resp = self.client.post(
            reverse("goals:goal_create"),
            {
                "name": "Reserva de emergência",
                "target_amount": "5000",
                "target_date": "",
                "priority": Goal.Priority.MEDIUM,
                "notes": "",
            },
            follow=True,
        )
        self.assertEqual(resp.status_code, 200)
        goal = Goal.objects.get(owner=self.alice, name="Reserva de emergência")
        self.assertEqual(goal.target_amount, 500000)
        # O formulário não expõe current_amount: começa em zero.
        self.assertEqual(goal.current_amount, 0)
        self.assertEqual(goal.status, Goal.Status.ACTIVE)

    def test_edit_goal_updates_target(self):
        goal = self.make_goal(owner=self.alice, name="Reserva", target_amount=100000)
        self.client.post(
            reverse("goals:goal_edit", args=[goal.pk]),
            {
                "name": "Reserva",
                "target_amount": "8000",
                "target_date": "",
                "priority": Goal.Priority.HIGH,
                "notes": "",
            },
        )
        goal.refresh_from_db()
        self.assertEqual(goal.target_amount, 800000)
        self.assertEqual(goal.priority, Goal.Priority.HIGH)

    def test_edit_other_user_goal_returns_404(self):
        goal = self.make_goal(owner=self.bob, name="Reserva", target_amount=100000)
        resp = self.client.post(
            reverse("goals:goal_edit", args=[goal.pk]),
            {
                "name": "Reserva",
                "target_amount": "1",
                "target_date": "",
                "priority": Goal.Priority.MEDIUM,
                "notes": "",
            },
        )
        self.assertEqual(resp.status_code, 404)

    def test_detail_other_user_goal_returns_404(self):
        goal = self.make_goal(owner=self.bob, name="Reserva", target_amount=100000)
        resp = self.client.get(reverse("goals:goal_detail", args=[goal.pk]))
        self.assertEqual(resp.status_code, 404)


class GoalContributionWebTests(GoalWebTestBase):
    def test_contribute_updates_current_amount(self):
        goal = self.make_goal(owner=self.alice, name="Reserva", target_amount=1000000)
        self.client.post(
            reverse("goals:goal_contribute", args=[goal.pk]),
            {"amount": "3000"},
        )
        goal.refresh_from_db()
        self.assertEqual(goal.current_amount, 300000)
        # Aporte parcial não marca a meta como atingida.
        self.assertEqual(goal.status, Goal.Status.ACTIVE)

    def test_contribute_to_other_user_goal_404(self):
        goal = self.make_goal(owner=self.bob, name="Reserva", target_amount=100000)
        resp = self.client.post(
            reverse("goals:goal_contribute", args=[goal.pk]),
            {"amount": "100"},
        )
        self.assertEqual(resp.status_code, 404)


class GoalStatusWebTests(GoalWebTestBase):
    def test_pause_activate_archive(self):
        goal = self.make_goal(owner=self.alice, name="Reserva", target_amount=100000)
        self.client.post(reverse("goals:goal_pause", args=[goal.pk]))
        goal.refresh_from_db()
        self.assertEqual(goal.status, Goal.Status.PAUSED)

        self.client.post(reverse("goals:goal_activate", args=[goal.pk]))
        goal.refresh_from_db()
        self.assertEqual(goal.status, Goal.Status.ACTIVE)

        self.client.post(reverse("goals:goal_archive", args=[goal.pk]))
        goal.refresh_from_db()
        self.assertEqual(goal.status, Goal.Status.ARCHIVED)

    def test_status_change_other_user_goal_404(self):
        goal = self.make_goal(owner=self.bob, name="Reserva", target_amount=100000)
        resp = self.client.post(reverse("goals:goal_pause", args=[goal.pk]))
        self.assertEqual(resp.status_code, 404)

    def test_delete_other_user_goal_404(self):
        goal = self.make_goal(owner=self.bob, name="Reserva", target_amount=100000)
        resp = self.client.post(reverse("goals:goal_delete", args=[goal.pk]))
        self.assertEqual(resp.status_code, 404)
