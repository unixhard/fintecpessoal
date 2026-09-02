"""Admin do app budgets."""

from django.contrib import admin

from .models import Budget


@admin.register(Budget)
class BudgetAdmin(admin.ModelAdmin):
    list_display = ("kind", "category", "period", "limit_amount", "is_active", "owner")
    list_filter = ("kind", "period", "is_active", "owner")
    raw_id_fields = ("owner", "category")
