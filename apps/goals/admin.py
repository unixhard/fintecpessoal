"""Admin do app goals."""

from django.contrib import admin

from .models import Goal


@admin.register(Goal)
class GoalAdmin(admin.ModelAdmin):
    list_display = ("name", "owner", "target_amount", "current_amount", "priority", "status")
    list_filter = ("priority", "status", "owner")
    search_fields = ("name", "owner__username")
    raw_id_fields = ("owner",)
