"""Rotas do shell da aplicação autenticada (/app/)."""

from django.urls import path

from . import views

app_name = "dashboard"

urlpatterns = [
    path("", views.DashboardIndexView.as_view(), name="index"),
    path(
        "<section>/",
        views.AppPlaceholderView.as_view(),
        name="section",
    ),
]
