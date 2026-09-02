"""Rotas de dívidas (/app/dividas/)."""

from django.urls import path

from . import views

app_name = "debts"

urlpatterns = [
    path("", views.DebtListView.as_view(), name="debt_list"),
    path("nova/", views.DebtCreateView.as_view(), name="debt_create"),
    path("<int:pk>/", views.DebtDetailView.as_view(), name="debt_detail"),
    path("<int:pk>/editar/", views.DebtEditView.as_view(), name="debt_edit"),
    path("<int:pk>/pagar/", views.DebtPaymentView.as_view(), name="debt_pay"),
    path("<int:pk>/inadimplente/", views.DebtStatusView.as_view(new_status="defaulted", label="marcada como inadimplente"), name="debt_default"),
    path("<int:pk>/reativar/", views.DebtStatusView.as_view(new_status="active", label="reativada"), name="debt_activate"),
    path("<int:pk>/arquivar/", views.DebtStatusView.as_view(new_status="archived", label="arquivada"), name="debt_archive"),
    path("<int:pk>/excluir/", views.DebtDeleteView.as_view(), name="debt_delete"),
]
