from django.contrib import admin

from .models import Comprovante


@admin.register(Comprovante)
class ComprovanteAdmin(admin.ModelAdmin):
    list_display = ("owner", "title", "kind", "warranty_expiry", "created_at")
    list_filter = ("kind",)
    search_fields = ("owner__username", "title", "notes")
