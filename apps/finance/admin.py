"""Admin do app finance (núcleo do razão)."""

from django.contrib import admin

from . import models


@admin.register(models.Account)
class AccountAdmin(admin.ModelAdmin):
    list_display = ("name", "owner", "type", "initial_balance", "currency", "status")
    list_filter = ("type", "status", "owner")
    search_fields = ("name", "institution")
    raw_id_fields = ("owner",)


@admin.register(models.Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "parent", "owner", "kind", "is_default", "status")
    list_filter = ("kind", "status", "is_default", "owner")
    search_fields = ("name", "owner__username")
    raw_id_fields = ("owner", "parent")


class TransactionAdmin(admin.ModelAdmin):
    list_display = ("date", "type", "amount", "description", "account", "category", "owner")
    list_filter = ("type", "source", "is_reconciled", "owner")
    search_fields = ("description", "external_id", "owner__username")
    raw_id_fields = (
        "owner",
        "account",
        "category",
        "transfer",
        "recurrence",
        "card_purchase",
    )


admin.site.register(models.Transaction, TransactionAdmin)


@admin.register(models.Transfer)
class TransferAdmin(admin.ModelAdmin):
    list_display = ("date", "from_account", "to_account", "amount", "owner")
    list_filter = ("owner",)
    raw_id_fields = ("owner", "from_account", "to_account", "out_transaction", "in_transaction")


@admin.register(models.RecurringRule)
class RecurringRuleAdmin(admin.ModelAdmin):
    list_display = ("title", "kind", "amount", "frequency", "account", "card", "status", "owner")
    list_filter = ("kind", "frequency", "status", "owner")
    search_fields = ("title", "owner__username")
    raw_id_fields = ("owner", "category", "account", "card")
