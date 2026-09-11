"""Rotas de cartão de crédito (/app/cards/)."""

from django.urls import path

from . import views

app_name = "cards"

urlpatterns = [
    path("cartoes/", views.CardListView.as_view(), name="card_list"),
    path("cartoes/novo/", views.CardCreateView.as_view(), name="card_create"),
    path("cartoes/<int:pk>/", views.CardDetailView.as_view(), name="card_detail"),
    path("cartoes/<int:pk>/editar/", views.CardEditView.as_view(), name="card_edit"),
    path("cartoes/<int:pk>/bloquear/", views.CardStatusView.as_view(new_status="blocked"), name="card_block"),
    path("cartoes/<int:pk>/fechar/", views.CardStatusView.as_view(new_status="closed"), name="card_close"),
    path("cartoes/<int:pk>/reativar/", views.CardStatusView.as_view(new_status="active"), name="card_reactivate"),
    path("cartoes/<int:pk>/excluir/", views.CardDeleteView.as_view(), name="card_delete"),
    path("compras/", views.PurchaseListView.as_view(), name="purchase_list"),
    path("compras/nova/", views.PurchaseCreateView.as_view(), name="purchase_create"),
    path("compras/<int:pk>/editar/", views.PurchaseEditView.as_view(), name="purchase_edit"),
    path("compras/<int:pk>/excluir/", views.PurchaseDeleteView.as_view(), name="purchase_delete"),
    path("faturas/", views.InvoiceListView.as_view(), name="invoice_list"),
    path("faturas/<int:pk>/", views.InvoiceDetailView.as_view(), name="invoice_detail"),
    path("faturas/<int:pk>/pagar/", views.InvoicePayView.as_view(), name="invoice_pay"),
    path("faturas/<int:pk>/estornar/", views.InvoiceReverseView.as_view(), name="invoice_reverse"),
]
