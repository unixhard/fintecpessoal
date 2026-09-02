"""Rotas dos lembretes (/app/lembretes/)."""

from django.urls import path

from . import views

app_name = "reminders"

urlpatterns = [
    path("", views.ReminderIndexView.as_view(), name="index"),
]
