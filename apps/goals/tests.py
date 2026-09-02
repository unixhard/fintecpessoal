"""Testes do app goals."""

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase

from .models import Goal

User = get_user_model()


class GoalTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="alice", password="x")

    def test_goal_rejects_negative_target(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Goal.objects.bulk_create(
                    [Goal(owner=self.user, name="Viagem", target_amount=-1)]
                )

    def test_goal_progress_percent(self):
        goal = Goal.objects.create(
            owner=self.user, name="Reserva",
            target_amount=10000, current_amount=2500,
        )
        self.assertEqual(goal.progress_percent, 25)

    def test_ownermodel_full_clean_on_goal(self):
        # goals.Goal herda OwnedModel; garantir que owner seja obrigatório.
        with self.assertRaises(Exception):
            Goal.objects.create(name="Sem dono")
