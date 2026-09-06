"""Testes da taxonomia padrão (Ordem 18 — FASE 3).

Cobre: estrutura da árvore (sem categorias de marca), seeding idempotente,
isolamento A≠B, tipos (kinds), atributos padrão e backfill (comando/onboarding).
"""

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase

from .models import Category
from .taxonomy import DEFAULT_TREE, default_kinds
from .services.categories import seed_default_categories

User = get_user_model()

SENSIBLE_BRAND_CATEGORIES = {"netflix", "uber", "spotify", "ifood", "amazon"}


class TaxonomyTreeTests(TestCase):
    def test_tree_has_expense_and_income_kinds(self):
        kinds = default_kinds()
        self.assertIn(Category.Kind.EXPENSE, kinds)
        self.assertIn(Category.Kind.INCOME, kinds)

    def test_tree_does_not_contain_brand_categories(self):
        """Regra da Ordem 18: nenhuma categoria de marca nesta camada."""
        names = {
            name.lower()
            for kind, name, children in DEFAULT_TREE
            for n in [name, *children]
        }
        self.assertFalse(names & SENSIBLE_BRAND_CATEGORIES)

    def test_no_subcategory_model_needed_hierarchy(self):
        """Hierarquia é expressa por Category.parent (sem modelo separado)."""
        children = {
            name for kind, name, children in DEFAULT_TREE for name in children
        }
        self.assertGreater(len(children), 0)


class SeedTests(TestCase):
    def setUp(self):
        self.alice = User.objects.create_user(username="alice", password="x")
        self.bob = User.objects.create_user(username="bob", password="y")

    def test_seed_creates_categories_and_subcategories(self):
        result = seed_default_categories(user=self.alice)
        self.assertGreater(result["categories"], 0)
        self.assertGreater(result["subcategories"], 0)
        top = Category.objects.filter(
            owner=self.alice, parent__isnull=True, is_default=True
        )
        self.assertEqual(top.count(), result["categories"])

    def test_seed_sets_kind_and_default_flag(self):
        seed_default_categories(user=self.alice)
        rend = Category.objects.get(
            owner=self.alice, name="Rendimentos", kind=Category.Kind.INCOME
        )
        self.assertTrue(rend.is_default)
        self.assertIsNone(rend.parent)
        salario = Category.objects.get(
            owner=self.alice, name="Salário", kind=Category.Kind.INCOME
        )
        self.assertEqual(salario.parent, rend)

    def test_seed_is_idempotent(self):
        first = seed_default_categories(user=self.alice)
        second = seed_default_categories(user=self.alice)
        base_count = Category.objects.filter(owner=self.alice).count()
        self.assertEqual(base_count, first["categories"] + first["subcategories"])
        self.assertEqual(second["categories"], 0)
        self.assertEqual(second["subcategories"], 0)
        self.assertEqual(Category.objects.filter(owner=self.alice).count(), base_count)

    def test_seed_isolation_between_users(self):
        seed_default_categories(user=self.alice)
        self.assertEqual(
            Category.objects.filter(owner=self.bob, parent__isnull=True).count(), 0
        )
        seed_default_categories(user=self.bob)
        a_names = set(
            Category.objects.filter(owner=self.alice).values_list("name", flat=True)
        )
        b_names = set(
            Category.objects.filter(owner=self.bob).values_list("name", flat=True)
        )
        self.assertEqual(a_names, b_names)

    def test_seed_allows_same_child_name_under_different_parents(self):
        """'Streaming de vídeo' existe sob Entretenimento e Assinaturas."""
        seed_default_categories(user=self.alice)
        streams = Category.objects.filter(
            owner=self.alice, name="Streaming de vídeo"
        )
        self.assertGreater(
            streams.count(), 1, "deve existir sob pais distintos sem conflito"
        )

    def test_seed_does_not_touch_user_created_categories(self):
        seed_default_categories(user=self.alice)
        extra = Category.objects.create(
            owner=self.alice, name="Categoria pessoal", kind=Category.Kind.EXPENSE
        )
        before = Category.objects.filter(owner=self.alice).count()
        seed_default_categories(user=self.alice)
        self.assertEqual(Category.objects.filter(owner=self.alice).count(), before)
        extra.refresh_from_db()
        self.assertFalse(extra.is_default)
        self.assertEqual(extra.name, "Categoria pessoal")


class SeedCommandTests(TestCase):
    def test_command_backfills_all_users(self):
        alice = User.objects.create_user(username="alice", password="x")
        call_command("seed_categories")
        self.assertGreater(
            Category.objects.filter(owner=alice, parent__isnull=True).count(), 0
        )

    def test_command_backfills_single_user(self):
        alice = User.objects.create_user(username="alice", password="x")
        bob = User.objects.create_user(username="bob", password="y")
        call_command("seed_categories", "--user", alice.pk)
        self.assertGreater(
            Category.objects.filter(owner=alice, parent__isnull=True).count(), 0
        )
        self.assertEqual(
            Category.objects.filter(owner=bob, parent__isnull=True).count(), 0
        )
