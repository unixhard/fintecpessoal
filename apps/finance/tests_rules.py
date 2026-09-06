"""Testes do serviço de regras de classificação (Ordem 18 — FASE 6).

Cobre: criação pessoal/global, isolamento multiusuário, read-only de regras
globais para usuários comuns, prioridade, ativação e validação de ownership.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase

from .models import Category, ClassificationRule, Merchant
from .services.categories import create_category
from .services.rules import (
    create_rule,
    delete_rule,
    list_global_rules,
    list_rules,
    set_active,
    set_priority,
    update_rule,
)

User = get_user_model()


class RulesServiceTests(TestCase):
    def setUp(self):
        self.alice = User.objects.create_user(username="alice", password="x")
        self.bob = User.objects.create_user(username="bob", password="y")
        self.alimentacao = create_category(user=self.alice, name="Alimentação", kind="expense")

    def test_create_personal_rule(self):
        rule = create_rule(
            user=self.alice,
            name="Ifood",
            condition_type=ClassificationRule.ConditionType.CONTAINS,
            pattern="IFOOD",
            category=self.alimentacao,
            kind=ClassificationRule.Kind.EXPENSE,
            priority=5,
        )
        self.assertEqual(rule.owner, self.alice)
        self.assertFalse(rule.is_global)
        self.assertEqual(rule.category, self.alimentacao)

    def test_personal_rule_rejects_other_users_category(self):
        bob_cat = create_category(user=self.bob, name="Comida", kind="expense")
        with self.assertRaises(ValueError):
            create_rule(
                user=self.alice,
                name="X",
                condition_type=ClassificationRule.ConditionType.CONTAINS,
                pattern="FOO",
                category=bob_cat,
            )

    def test_global_rule_never_references_user_category(self):
        with self.assertRaises(ValueError):
            create_rule(
                user=self.alice,
                is_global=True,
                name="G",
                condition_type=ClassificationRule.ConditionType.CONTAINS,
                pattern="LANCHONETE",
                category=self.alimentacao,
            )

    def test_global_rule_uses_category_name(self):
        rule = create_rule(
            user=self.alice,
            is_global=True,
            name="Global",
            condition_type=ClassificationRule.ConditionType.CONTAINS,
            pattern="LANCHONETE",
            category_name="Restaurante",
            priority=5,
        )
        self.assertTrue(rule.is_global)
        self.assertEqual(rule.category_name, "Restaurante")

    def test_list_and_global_partition(self):
        create_rule(user=self.alice, name="A", pattern="X", category_name="Restaurante")
        create_rule(user=self.bob, name="B", pattern="Y", category_name="Restaurante")
        create_rule(user=self.alice, is_global=True, name="G", pattern="LANCHONETE", category_name="Restaurante")
        self.assertEqual(len(list_rules(self.alice)), 1)
        self.assertEqual(len(list_rules(self.bob)), 1)
        self.assertEqual(len(list_global_rules()), 1)

    def test_update_isolated(self):
        rule = create_rule(user=self.alice, name="A", pattern="X", category_name="Restaurante")
        update_rule(self.alice, rule, name="A2", priority=1)
        rule.refresh_from_db()
        self.assertEqual(rule.name, "A2")
        self.assertEqual(rule.priority, 1)

    def test_cannot_update_other_users_rule(self):
        rule = create_rule(user=self.bob, name="B", pattern="Y", category_name="Restaurante")
        with self.assertRaises(PermissionError):
            update_rule(self.alice, rule, name="hack")

    def test_cannot_modify_global_rule_as_common_user(self):
        rule = create_rule(user=self.alice, is_global=True, name="G", pattern="Z", category_name="Restaurante")
        with self.assertRaises(PermissionError):
            update_rule(self.alice, rule, name="hack")

    def test_set_active_and_priority(self):
        rule = create_rule(user=self.alice, name="A", pattern="X", category_name="Restaurante", priority=50)
        set_active(self.alice, rule, False)
        set_priority(self.alice, rule, 1)
        rule.refresh_from_db()
        self.assertFalse(rule.is_active)
        self.assertEqual(rule.priority, 1)

    def test_delete_isolated(self):
        rule = create_rule(user=self.alice, name="A", pattern="X", category_name="Restaurante")
        other = create_rule(user=self.bob, name="B", pattern="Y", category_name="Restaurante")
        with self.assertRaises(PermissionError):
            delete_rule(self.bob, rule)
        self.assertTrue(delete_rule(self.alice, rule))
        self.assertEqual(ClassificationRule.objects.filter(pk=rule.pk).count(), 0)
        self.assertEqual(ClassificationRule.objects.filter(pk=other.pk).count(), 1)
