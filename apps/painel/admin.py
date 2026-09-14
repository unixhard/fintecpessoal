from django.contrib import admin

from .models import AccessCode, Coupon, FeatureEvent, MonetizationConfig, Payment, Plan, Subscription


@admin.register(FeatureEvent)
class FeatureEventAdmin(admin.ModelAdmin):
    list_display = ("feature", "user", "date", "count")
    list_filter = ("feature", "date")
    search_fields = ("feature", "user__username")
    date_hierarchy = "date"


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "price", "billing_cycle", "duration_days", "is_active", "order")
    list_filter = ("is_active", "billing_cycle")
    search_fields = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Coupon)
class CouponAdmin(admin.ModelAdmin):
    list_display = ("code", "discount_type", "discount_value", "valid_until", "max_uses", "times_used", "is_active")
    list_filter = ("is_active", "discount_type")
    search_fields = ("code",)


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ("user", "plan", "status", "started_at", "expires_at", "canceled_at")
    list_filter = ("status",)
    search_fields = ("user__username", "user__email")
    date_hierarchy = "created_at"


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("pk", "user", "amount", "discount", "method", "status", "paid_at", "created_at")
    list_filter = ("status", "method")
    search_fields = ("user__username", "reference")
    date_hierarchy = "created_at"


@admin.register(AccessCode)
class AccessCodeAdmin(admin.ModelAdmin):
    list_display = ("code", "plan", "note", "created_by", "created_at", "used_by", "used_at", "revoked")
    list_filter = ("revoked", "plan")
    search_fields = ("code", "note")


@admin.register(MonetizationConfig)
class MonetizationConfigAdmin(admin.ModelAdmin):
    list_display = ("signup_requires_payment", "default_plan", "price_label", "support_contact", "updated_at")
