from django.contrib import admin
from .models import AssetTransfer


@admin.register(AssetTransfer)
class AssetTransferAdmin(admin.ModelAdmin):
    list_display = (
        'asset', 'from_department', 'from_location', 'to_department',
        'to_location', 'status', 'transfer_date', 'requested_by', 'created_at'
    )
    list_filter = ('status', 'to_department', 'from_department', 'transfer_date')
    search_fields = (
        'asset__asset_code', 'asset__item_name', 'reason',
        'from_department__name', 'to_department__name'
    )
    readonly_fields = ('created_at', 'updated_at', 'approved_at', 'completed_at', 'cancelled_at')
