"""Rotas financeiras (/app/finance/)."""

from django.urls import path

from . import views

app_name = "finance"

urlpatterns = [
    # Contas
    path("contas/", views.AccountListView.as_view(), name="account_list"),
    path("contas/nova/", views.AccountCreateView.as_view(), name="account_create"),
    path("contas/<int:pk>/", views.AccountDetailView.as_view(), name="account_detail"),
    path("contas/<int:pk>/editar/", views.AccountEditView.as_view(), name="account_edit"),
    path("contas/<int:pk>/arquivar/", views.AccountStatusView.as_view(action="archive"), name="account_archive"),
    path("contas/<int:pk>/reativar/", views.AccountStatusView.as_view(action="reactivate"), name="account_reactivate"),
    path("contas/<int:pk>/excluir/", views.AccountDeleteView.as_view(), name="account_delete"),
    # Categorias
    path("categorias/", views.CategoryListView.as_view(), name="category_list"),
    path("categorias/nova/", views.CategoryCreateView.as_view(), name="category_create"),
    path("categorias/<int:pk>/editar/", views.CategoryEditView.as_view(), name="category_edit"),
    path("categorias/<int:pk>/arquivar/", views.CategoryArchiveView.as_view(), name="category_archive"),
    # Lançamentos
    path("movimentacoes/", views.TransactionListView.as_view(), name="transaction_list"),
    path("movimentacoes/nova/", views.TransactionCreateView.as_view(), name="transaction_create"),
    path("receita/nova/", views.IncomeCreateView.as_view(), name="income_create"),
    path("despesa/nova/", views.ExpenseCreateView.as_view(), name="expense_create"),
    path("transferencia/nova/", views.TransferCreateView.as_view(), name="transfer_create"),
    path("movimentacoes/<int:pk>/", views.TransactionDetailView.as_view(), name="transaction_detail"),
    path("movimentacoes/<int:pk>/editar/", views.TransactionEditView.as_view(), name="transaction_edit"),
    path("movimentacoes/<int:pk>/excluir/", views.TransactionDeleteView.as_view(), name="transaction_delete"),
    # Recorrências
    path("recorrencias/", views.RecurringListView.as_view(), name="recurring_list"),
    path("recorrencias/nova/", views.RecurringCreateView.as_view(), name="recurring_create"),
    path("recorrencias/<int:pk>/editar/", views.RecurringEditView.as_view(), name="recurring_edit"),
    path("recorrencias/<int:pk>/pausar/", views.RecurringStatusView.as_view(new_status="paused"), name="recurring_pause"),
    path("recorrencias/<int:pk>/reativar/", views.RecurringStatusView.as_view(new_status="active"), name="recurring_activate"),
    path("recorrencias/<int:pk>/encerrar/", views.RecurringStatusView.as_view(new_status="ended"), name="recurring_end"),
    # Regras de classificação (Ordem 18 — FASE 6)
    path("regras/", views.RuleListView.as_view(), name="rule_list"),
    path("regras/nova/", views.RuleCreateView.as_view(), name="rule_create"),
    path("regras/<int:pk>/editar/", views.RuleEditView.as_view(), name="rule_edit"),
    path("regras/<int:pk>/alternar/", views.RuleToggleView.as_view(), name="rule_toggle"),
    path("regras/<int:pk>/excluir/", views.RuleDeleteView.as_view(), name="rule_delete"),
    # Fila de revisão / backfill (Ordem 18 — FASE 7/9)
    path("revisao/", views.ReviewQueueView.as_view(), name="review_queue"),
    path("revisao/corrigir-lote/", views.ReviewBulkView.as_view(), name="review_bulk"),
    path("revisao/corrigir/<int:pk>/", views.ReviewIndividualView.as_view(), name="review_individual"),
    path("revisao/reprocessar/", views.BackfillView.as_view(), name="backfill"),
    # Assistente Fintec (MÓDULO CHAT) — lançamento por linguagem natural
    path("assistente/interpretar/", views.ChatParseView.as_view(), name="chat_parse"),
    path("assistente/confirmar/", views.ChatConfirmView.as_view(), name="chat_confirm"),
]
