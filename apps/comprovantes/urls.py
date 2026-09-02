"""Rotas dos comprovantes (/app/comprovantes/)."""

from django.urls import path

from . import views

app_name = "comprovantes"

urlpatterns = [
    path("", views.ComprovanteListView.as_view(), name="list"),
    path("novo/", views.ComprovanteCreateView.as_view(), name="create"),
    path("parse-ai/", views.ComprovanteParseAIView.as_view(), name="parse_ai"),
    path("<int:pk>/editar/", views.ComprovanteEditView.as_view(), name="edit"),
    path("<int:pk>/excluir/", views.ComprovanteDeleteView.as_view(), name="delete"),
    path("<int:pk>/baixar/", views.ComprovanteDownloadView.as_view(), name="download"),
]
