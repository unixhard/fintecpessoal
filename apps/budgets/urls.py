"""Rotas de orçamentos (/app/orcamentos/)."""

from django.urls import path

from . import views

app_name = "budgets"

urlpatterns = [
    path("", views.BudgetListView.as_view(), name="budget_list"),
    path("novo/", views.BudgetCreateView.as_view(), name="budget_create"),
    path("<int:pk>/", views.BudgetDetailView.as_view(), name="budget_detail"),
    path("<int:pk>/editar/", views.BudgetEditView.as_view(), name="budget_edit"),
    path("<int:pk>/alternar/", views.BudgetToggleView.as_view(), name="budget_toggle"),
    path("<int:pk>/excluir/", views.BudgetDeleteView.as_view(), name="budget_delete"),
]
