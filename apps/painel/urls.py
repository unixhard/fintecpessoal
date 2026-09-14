"""Rotas do Painel do Dono (superuser)."""

from django.urls import path

from . import views

app_name = "painel"

urlpatterns = [
    # Dashboard
    path("", views.PanelIndexView.as_view(), name="index"),
    path("relatorios/", views.ReportsView.as_view(), name="reports"),

    # Usuários
    path("usuarios/", views.UserListView.as_view(), name="user_list"),
    path("usuarios/<int:pk>/", views.UserDetailView.as_view(), name="user_detail"),
    path(
        "usuarios/<int:pk>/toggle/<str:field>/",
        views.UserToggleView.as_view(),
        name="user_toggle",
    ),

    # Planos
    path("planos/", views.PlanListView.as_view(), name="plan_list"),
    path("planos/novo/", views.PlanCreateView.as_view(), name="plan_create"),
    path("planos/<int:pk>/editar/", views.PlanEditView.as_view(), name="plan_edit"),
    path("planos/<int:pk>/toggle/", views.PlanToggleView.as_view(), name="plan_toggle"),

    # Cupons
    path("cupons/", views.CouponListView.as_view(), name="coupon_list"),
    path("cupons/novo/", views.CouponCreateView.as_view(), name="coupon_create"),
    path("cupons/<int:pk>/toggle/", views.CouponToggleView.as_view(), name="coupon_toggle"),

    # Assinaturas
    path("assinaturas/", views.SubscriptionListView.as_view(), name="subscription_list"),
    path(
        "usuarios/<int:pk>/assinaturas/conceder/",
        views.SubscriptionGrantView.as_view(),
        name="subscription_grant",
    ),
    path(
        "assinaturas/<int:pk>/cancelar/",
        views.SubscriptionCancelView.as_view(),
        name="subscription_cancel",
    ),

    # Pagamentos
    path("pagamentos/", views.PaymentListView.as_view(), name="payment_list"),
    path(
        "usuarios/<int:pk>/pagamentos/registrar/",
        views.PaymentCreateView.as_view(),
        name="payment_create",
    ),
    path(
        "pagamentos/<int:pk>/pagar/",
        views.PaymentMarkPaidView.as_view(),
        name="payment_mark_paid",
    ),
    path(
        "pagamentos/<int:pk>/reembolsar/",
        views.PaymentRefundView.as_view(),
        name="payment_refund",
    ),

    # Monetização
    path("monetizacao/", views.MonetizationView.as_view(), name="monetization"),
    path(
        "monetizacao/codigos/criar/",
        views.AccessCodeCreateView.as_view(),
        name="access_code_create",
    ),
    path(
        "monetizacao/codigos/<int:pk>/revogar/",
        views.AccessCodeRevokeView.as_view(),
        name="access_code_revoke",
    ),

    # Telemetria
    path("track/", views.TrackView.as_view(), name="track"),
]