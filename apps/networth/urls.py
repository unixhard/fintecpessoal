"""Rotas do patrimônio (/app/patrimonio/)."""

from django.urls import path

from . import views

app_name = "networth"

urlpatterns = [
    path("", views.NetWorthIndexView.as_view(), name="index"),
    path("registrar/", views.NetWorthRegisterView.as_view(), name="register"),
]
