"""Rotas do Painel do Dono (superuser)."""

from django.urls import path

from . import views

app_name = "painel"

urlpatterns = [
    path("", views.PanelIndexView.as_view(), name="index"),
    path("usuarios/", views.UserListView.as_view(), name="user_list"),
    path("usuarios/<int:pk>/", views.UserDetailView.as_view(), name="user_detail"),
    path(
        "usuarios/<int:pk>/toggle/<str:field>/",
        views.UserToggleView.as_view(),
        name="user_toggle",
    ),
    path("monetizacao/", views.MonetizationView.as_view(), name="monetization"),
    path(
        "monetizacao/codigos/criar/",
        views.AccessCodeCreateView.as_view(),
        name="access_code_create",
    ),
    path(
        "monetizacao/codigos/<int:pk>/revogar/",
        views.AccessCodeRevokeView.as_view(),
        name="access_code_revoke",
    ),
    path("track/", views.TrackView.as_view(), name="track"),
]