"""Admin do app debts."""

from django.contrib import admin

from .models import Debt


@admin.register(Debt)
class DebtAdmin(admin.ModelAdmin):
    list_display = ("name", "owner", "type", "total_amount", "paid_amount", "status")
    list_filter = ("type", "status", "owner")
    search_fields = ("name", "creditor", "owner__username")
    raw_id_fields = ("owner",)
