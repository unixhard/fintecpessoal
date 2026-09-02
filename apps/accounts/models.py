"""Modelos do app accounts: usuário customizado e perfil financeiro.

Decisão arquitetural (D2/D3 — docs/ARQUITETURA_DOMINIO.md):
- User customizado (AbstractUser) desde o início para evitar custo de troca futura.
- Profile separado 1:1, criado por signal, guardando apenas dados financeiros/
  de preferência que não pertencem ao User do Django (não duplicar campos).
"""

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """Usuário customizado do FINTECPESSOAL.

    Herda todo o comportamento de autenticação do Django. Nenhum dado
    financeiro fica aqui — eles pertencem ao domínio financeiro, cada um
    com sua própria FK para `User` (owner).
    """

    class Meta:
        verbose_name = "usuário"
        verbose_name_plural = "usuários"
        ordering = ["username"]

    def __str__(self):
        return self.get_full_name() or self.username


class Profile(models.Model):
    """Perfil financeiro/preferências do usuário (1:1).

    Não duplica campos já existentes no User (first_name, last_name, email,
    password, is_active, dates). Guarda apenas dados de preferência financeira.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="profile",
        verbose_name="usuário",
    )
    display_name = models.CharField(
        "nome de exibição",
        max_length=80,
        blank=True,
        help_text="Nome exibido na interface (pode diferir dos nomes de cadastro).",
    )
    preferred_currency = models.CharField(
        "moeda padrão",
        max_length=3,
        default="BRL",
        choices=[("BRL", "Real (BRL)")],
    )
    default_account = models.ForeignKey(
        "finance.Account",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="conta padrão",
        help_text="Conta usada por padrão em lançamentos rápidos.",
    )
    preferences = models.JSONField(
        "preferências",
        default=dict,
        blank=True,
        help_text="Preferências de idioma, formato de data, tema, etc.",
    )
    onboarding_completed = models.BooleanField("onboarding concluído", default=False)
    created_at = models.DateTimeField("criado em", auto_now_add=True)
    updated_at = models.DateTimeField("atualizado em", auto_now=True)

    class Meta:
        verbose_name = "perfil"
        verbose_name_plural = "perfis"

    def __str__(self):
        return f"Perfil de {self.user}"
