"""Rotas dos relatórios (/app/relatorios/)."""

from django.urls import path

from . import views

app_name = "reports"

urlpatterns = [
    path("", views.ReportIndexView.as_view(), name="index"),
    path("ia/", views.AIReportView.as_view(), name="ai_report"),
    path("csv/", views.ReportCsvView.as_view(), name="csv"),
    path("imprimir/", views.ReportPrintableView.as_view(), name="print"),
]
