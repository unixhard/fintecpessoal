from django.contrib import admin

from .models import NetWorthSnapshot


@admin.register(NetWorthSnapshot)
class NetWorthSnapshotAdmin(admin.ModelAdmin):
    list_display = ("owner", "recorded_on", "assets", "liabilities", "net_worth")
    search_fields = ("owner__username", "owner__email")
