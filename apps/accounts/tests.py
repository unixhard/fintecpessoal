"""Testes do app accounts (custom user + profile)."""

from django.contrib.auth import get_user_model
from django.test import TestCase

from .models import Profile

User = get_user_model()


class UserAndProfileTests(TestCase):
    def test_custom_user_model_is_used(self):
        self.assertEqual(User._meta.label, "accounts.User")

    def test_profile_auto_created_on_user_creation(self):
        user = User.objects.create_user(username="alice", password="x")
        self.assertTrue(hasattr(user, "profile"))
        self.assertIsInstance(user.profile, Profile)

    def test_profile_does_not_duplicate_user_fields(self):
        user_fields = {
            f.name
            for f in User._meta.get_fields()
            if f.concrete and hasattr(f, "attname")
        }
        # Campos de credencial/identidade permanecem no User, não no Profile.
        for field in ("username", "email", "password", "first_name", "last_name", "is_active"):
            self.assertIn(field, user_fields)
        # Profile não deve repeti-los:
        profile_fields = {f.name for f in Profile._meta.get_fields() if f.concrete}
        for field in ("password", "email", "is_active", "last_login"):
            self.assertNotIn(field, profile_fields)

    def test_users_unique_by_username(self):
        User.objects.create_user(username="alice", password="x")
        with self.assertRaises(Exception):
            User.objects.create_user(username="alice", password="y")
