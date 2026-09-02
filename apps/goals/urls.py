"""Rotas de metas (/app/metas/)."""

from django.urls import path

from . import views

app_name = "goals"

urlpatterns = [
    path("", views.GoalListView.as_view(), name="goal_list"),
    path("nova/", views.GoalCreateView.as_view(), name="goal_create"),
    path("<int:pk>/", views.GoalDetailView.as_view(), name="goal_detail"),
    path("<int:pk>/editar/", views.GoalEditView.as_view(), name="goal_edit"),
    path("<int:pk>/aporte/", views.GoalContributionView.as_view(), name="goal_contribute"),
    path("<int:pk>/pausar/", views.GoalStatusView.as_view(new_status="paused", label="pausada"), name="goal_pause"),
    path("<int:pk>/reativar/", views.GoalStatusView.as_view(new_status="active", label="reativada"), name="goal_activate"),
    path("<int:pk>/arquivar/", views.GoalStatusView.as_view(new_status="archived", label="arquivada"), name="goal_archive"),
    path("<int:pk>/excluir/", views.GoalDeleteView.as_view(), name="goal_delete"),
]
