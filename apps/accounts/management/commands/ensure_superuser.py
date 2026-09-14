"""Garante a existência de um superusuário (dono da plataforma).

Útil em ambientes sem shell (ex.: Render free tier): roda no build/start sem
interação, criando o superuser somente se nenhum existir ainda. As credenciais
vêm de variáveis de ambiente para não ficarem no código:

    DJANGO_SU_USERNAME   (padrão: "admin")
    DJANGO_SU_EMAIL      (obrigatório)
    DJANGO_SU_PASSWORD   (padrão: gerada aleatória e exibida no log)

Usage:
    python manage.py ensure_superuser
"""

import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

User = get_user_model()


class Command(BaseCommand):
    help = "Cria um superusuário (dono) se ainda não existir nenhum."

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="Cria/atualiza mesmo se já existir algum superusuário.",
        )

    def handle(self, *args, **options):
        if User.objects.filter(is_superuser=True).exists() and not options["force"]:
            self.stdout.write("Superusuário já existe — nada a fazer.")
            return

        username = os.getenv("DJANGO_SU_USERNAME", "admin").strip()
        email = os.getenv("DJANGO_SU_EMAIL", "").strip()
        password = os.getenv("DJANGO_SU_PASSWORD", "")

        if not email:
            self.stderr.write("DJANGO_SU_EMAIL não definida — abortando.")
            raise SystemExit(1)

        user = User.objects.filter(username=username).first()
        if user is None:
            user = User(username=username, email=email)
            created = True
        else:
            created = False

        user.email = email
        user.is_superuser = True
        user.is_staff = True
        user.is_active = True
        if password:
            user.set_password(password)
        user.save()

        if created:
            self.stdout.write(
                self.style.SUCCESS(f"Superusuário criado: {username} <{email}>")
            )
            if not password:
                self.stdout.write(
                    self.style.WARNING("Senha não definida — use 'manage.py changepassword'.")
                )
        else:
            self.stdout.write(
                self.style.SUCCESS(f"Superusuário atualizado: {username} <{email}>")
            )