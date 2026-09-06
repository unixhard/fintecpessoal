"""Rotas da tela de Configurações."""

from django.urls import path

from . import views

app_name = "settings"

urlpatterns = [
    path("", views.SettingsIndexView.as_view(), name="index"),
    path("perfil/", views.ProfileUpdateView.as_view(), name="profile"),
    path("senha/", views.PasswordChangeView.as_view(), name="password"),
    path("backup/", views.BackupExportView.as_view(), name="backup_export"),
    path("restaurar/", views.BackupRestoreView.as_view(), name="backup_restore"),
    path("limpar/", views.WipeDataView.as_view(), name="wipe"),
    path("deletar/", views.DeleteAccountView.as_view(), name="delete_account"),
]
