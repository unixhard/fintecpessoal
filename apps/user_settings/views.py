"""Views da tela de Configurações.

Substitui o placeholder do dashboard por uma tela real com:
  - Perfil (nome, email, conta padrão)
  - Troca de senha
  - Backup / Export (download JSON)
  - Restore / Import (upload JSON)
  - Limpar dados (wipe)
  - Deletar conta
"""

import json

from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views import View
from django.views.generic import TemplateView

from .forms import (
    DeleteAccountForm,
    PasswordChangeForm,
    ProfileForm,
    UserForm,
    WipeConfirmForm,
)
from .services import (
    delete_account,
    export_user_data,
    restore_user_data,
    wipe_user_data,
)


class SettingsIndexView(LoginRequiredMixin, TemplateView):
    """Página principal de configurações — hub com links para cada seção."""

    template_name = "settings/index.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["title"] = "Configurações"
        return ctx


class ProfileUpdateView(LoginRequiredMixin, View):
    """Editar perfil do usuário (nome de exibição, nome, email, conta padrão)."""

    def get(self, request):
        profile = request.user.profile
        user_form = UserForm(instance=request.user)
        profile_form = ProfileForm(instance=profile, user=request.user)
        return render(request, "settings/profile.html", {
            "user_form": user_form,
            "profile_form": profile_form,
        })

    def post(self, request):
        profile = request.user.profile
        user_form = UserForm(request.POST, instance=request.user)
        profile_form = ProfileForm(request.POST, instance=profile, user=request.user)
        if user_form.is_valid() and profile_form.is_valid():
            user_form.save()
            profile_form.save()
            messages.success(request, "Perfil atualizado com sucesso.")
            return redirect("settings:profile")
        return render(request, "settings/profile.html", {
            "user_form": user_form,
            "profile_form": profile_form,
        })


class PasswordChangeView(LoginRequiredMixin, View):
    """Troca de senha do usuário."""

    def get(self, request):
        form = PasswordChangeForm(user=request.user)
        return render(request, "settings/password.html", {"form": form})

    def post(self, request):
        form = PasswordChangeForm(request.POST, user=request.user)
        if form.is_valid():
            request.user.set_password(form.cleaned_data["new_password"])
            request.user.save()
            update_session_auth_hash(request, request.user)
            messages.success(request, "Senha alterada com sucesso.")
            return redirect("settings:profile")
        return render(request, "settings/password.html", {"form": form})


class BackupExportView(LoginRequiredMixin, View):
    """Exporta todos os dados do usuário como JSON para download."""

    def get(self, request):
        data = export_user_data(request.user)
        content = json.dumps(data, indent=2, ensure_ascii=False, default=str)
        filename = f"fintecpessoal-backup-{request.user.username}.json"
        response = HttpResponse(content, content_type="application/json; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response


class BackupRestoreView(LoginRequiredMixin, View):
    """Importa dados a partir de um arquivo JSON de backup."""

    def get(self, request):
        return render(request, "settings/restore.html", {})

    def post(self, request):
        uploaded = request.FILES.get("backup_file")
        if not uploaded:
            messages.error(request, "Selecione um arquivo JSON de backup.")
            return render(request, "settings/restore.html", {})

        if uploaded.size > 10 * 1024 * 1024:  # 10 MB
            messages.error(request, "Arquivo muito grande (máx. 10 MB).")
            return render(request, "settings/restore.html", {})

        try:
            raw = uploaded.read().decode("utf-8")
            data = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError):
            messages.error(request, "Arquivo inválido. Use um JSON exportado pelo FINTECPESSOAL.")
            return render(request, "settings/restore.html", {})

        if not isinstance(data, dict) or "_meta" not in data:
            messages.error(request, "Formato de arquivo não reconhecido.")
            return render(request, "settings/restore.html", {})

        try:
            report = restore_user_data(request.user, data)
        except Exception as exc:
            messages.error(request, f"Erro ao restaurar: {exc}")
            return render(request, "settings/restore.html", {})

        total = report.get("restored", 0)
        errors = report.get("errors", 0)
        if errors:
            messages.warning(
                request,
                f"Restaurados {total} registros ({errors} erros — registros "
                f"existentes foram ignorados).",
            )
        else:
            messages.success(request, f"Restaurados {total} registros com sucesso.")
        return redirect("settings:index")


class WipeDataView(LoginRequiredMixin, View):
    """Apaga todos os dados financeiros do usuário (mantém conta)."""

    def get(self, request):
        form = WipeConfirmForm()
        return render(request, "settings/wipe.html", {"form": form})

    def post(self, request):
        form = WipeConfirmForm(request.POST)
        if form.is_valid():
            report = wipe_user_data(request.user)
            count = sum(report.values())
            messages.success(
                request,
                f"Dados financeiros apagados ({count} registros removidos). "
                "Sua conta e perfil foram mantidos.",
            )
            return redirect("dashboard:index")
        return render(request, "settings/wipe.html", {"form": form})


class DeleteAccountView(LoginRequiredMixin, View):
    """Deleta a conta do usuário e todos os dados (cascata)."""

    def get(self, request):
        form = DeleteAccountForm(user=request.user)
        return render(request, "settings/delete_account.html", {"form": form})

    def post(self, request):
        form = DeleteAccountForm(request.POST, user=request.user)
        if form.is_valid():
            delete_account(request.user)
            messages.success(request, "Conta deletada com sucesso. Sentiremos falta!")
            return redirect("accounts:login")
        return render(request, "settings/delete_account.html", {"form": form})
