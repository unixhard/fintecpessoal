"""Pré-seleção da taxonomia padrão (Ordem 18 — FASE 3).

Semeia (idempotente) as categorias/subcategorias padrão para usuários.

Sem ``--user``: processa todos os usuários do banco. Use ``--user`` para
reprocessar um usuário específico (ex.: backfill de um novo cadastro).
"""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Semeia a taxonomia padrão de categorias para os usuários."

    def add_arguments(self, parser):
        parser.add_argument(
            "--user",
            type=int,
            default=None,
            help="ID do usuário a reprocessar (todos por padrão).",
        )

    def handle(self, *args, **options):
        from apps.finance.services.categories import seed_default_categories

        user_model = get_user_model()
        if options["user"] is not None:
            users = [user_model.objects.get(pk=options["user"])]
        else:
            users = list(user_model.objects.all().order_by("pk"))

        total = {"categories": 0, "subcategories": 0}
        processed = 0
        for user in users:
            created = seed_default_categories(user=user)
            total["categories"] += created["categories"]
            total["subcategories"] += created["subcategories"]
            processed += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Seed concluído: {processed} usuário(s), "
                f"{total['categories']} categorias e "
                f"{total['subcategories']} subcategorias criadas."
            )
        )
