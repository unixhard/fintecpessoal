"""Rotas de importação (/app/importar/)."""

from django.urls import path

from . import views

app_name = "imports"

urlpatterns = [
    path("", views.ImportUploadView.as_view(), name="import_upload"),
    path("lote/<int:pk>/", views.ImportReviewView.as_view(), name="review"),
    path("lote/<int:pk>/resultado/", views.ImportResultView.as_view(), name="result"),
]
