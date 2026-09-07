"""Reabre o cooldown de relatórios IA sem apagar o histórico.

Mantém o cooldown ativo (REPORT_COOLDOWN_DAYS) e apenas retrocede o
``generated_at`` do relatório mais recente de cada usuário para além da
janela — assim o próximo teste/generação volta a ser permitido, sem
precisar liberar uso ilimitado nem perder o relatório (a continuidade
do prompt usa o último relatório como contexto).

Usage:
    python manage.py reset_ai_cooldown            # todos os usuários
    python manage.py reset_ai_cooldown --user 1   # só um usuário
"""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.reports.models import AIReport
from apps.reports.services import COOLDOWN_DAYS


class Command(BaseCommand):
    help = (
        "Reabre o cooldown de relatórios IA de um ou todos os usuários "
        "retrocedendo o generated_at do relatório mais recente."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--user",
            type=int,
            default=None,
            help="ID do usuário a liberar (todos por padrão).",
        )

    def handle(self, *args, **options):
        User = get_user_model()
        if options["user"] is not None:
            users = [User.objects.get(pk=options["user"])]
        else:
            users = list(User.objects.all().order_by("pk"))

        # Mais antigo que a janela do cooldown -> já liberado.
        target = timezone.now() - timedelta(days=COOLDOWN_DAYS + 1)
        updated = 0
        for user in users:
            latest = AIReport.objects.for_user(user).order_by("-generated_at").first()
            if latest is None or latest.generated_at <= target:
                continue
            AIReport.objects.filter(pk=latest.pk).update(generated_at=target)
            updated += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Cooldown reaberto em {len(users)} usuário(s): "
                f"{updated} relatório(s) retrocedido(s). "
                f"(limite continua em {COOLDOWN_DAYS} dia(s))"
            )
        )