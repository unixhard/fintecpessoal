from django.contrib import admin

from .models import AccessCode, FeatureEvent, MonetizationConfig


@admin.register(FeatureEvent)
class FeatureEventAdmin(admin.ModelAdmin):
    list_display = ("feature", "user", "date", "count")
    list_filter = ("feature", "date")
    search_fields = ("feature", "user__username")
    date_hierarchy = "date"


@admin.register(AccessCode)
class AccessCodeAdmin(admin.ModelAdmin):
    list_display = ("code", "note", "created_by", "created_at", "used_by", "used_at", "revoked")
    list_filter = ("revoked", "created_at")
    search_fields = ("code", "note")


@admin.register(MonetizationConfig)
class MonetizationConfigAdmin(admin.ModelAdmin):
    list_display = ("signup_requires_payment", "price_label", "updated_at")