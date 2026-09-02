"""Admin do app cards (cartões, faturas e parcelas)."""

from django.contrib import admin

from . import models


@admin.register(models.CreditCard)
class CreditCardAdmin(admin.ModelAdmin):
    list_display = ("name", "owner", "limit", "closing_day", "due_day", "status")
    list_filter = ("status", "owner")
    search_fields = ("name", "institution", "owner__username")
    raw_id_fields = ("owner", "payment_account")


class InstallmentInline(admin.TabularInline):
    model = models.Installment
    extra = 0
    fields = ("number", "amount", "due_date", "status", "invoice")


@admin.register(models.InstallmentPurchase)
class InstallmentPurchaseAdmin(admin.ModelAdmin):
    list_display = ("description", "card", "total_amount", "installment_count", "status", "owner")
    list_filter = ("status", "owner")
    search_fields = ("description", "owner__username")
    raw_id_fields = ("owner", "card")
    inlines = (InstallmentInline,)


@admin.register(models.CreditCardInvoice)
class CreditCardInvoiceAdmin(admin.ModelAdmin):
    list_display = ("card", "period_start", "period_end", "status", "due_date", "owner")
    list_filter = ("status", "owner")
    raw_id_fields = ("owner", "card", "payment_transaction", "payment_account")
