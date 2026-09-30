from django.contrib import admin
from .models import AssetCategory, Brand, Asset


@admin.register(AssetCategory)
class AssetCategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'is_active', 'created_at')
    search_fields = ('name', 'code')
    list_filter = ('is_active',)


@admin.register(Brand)
class BrandAdmin(admin.ModelAdmin):
    list_display = ('name', 'is_active', 'created_at')
    search_fields = ('name',)
    list_filter = ('is_active',)


@admin.register(Asset)
class AssetAdmin(admin.ModelAdmin):
    list_display = (
        'asset_code', 'item_name', 'category', 'brand',
        'property_number', 'department', 'condition', 'status'
    )
    search_fields = (
        'asset_code', 'item_name', 'property_number',
        'serial_number', 'brand__name', 'model'
    )
    list_filter = ('status', 'condition', 'category', 'department', 'brand')
    readonly_fields = ('asset_code', 'uuid', 'created_at', 'updated_at')
    fieldsets = (
        ('System Identification', {
            'fields': ('asset_code', 'uuid', 'created_by')
        }),
        ('Basic Information', {
            'fields': ('item_name', 'category', 'brand', 'model', 'description')
        }),
        ('Identifiers', {
            'fields': ('property_number', 'serial_number')
        }),
        ('Location & Custody', {
            'fields': ('department', 'current_location')
        }),
        ('Acquisition & Valuation', {
            'fields': ('acquisition_date', 'acquisition_cost', 'supplier')
        }),
        ('Condition & Status', {
            'fields': ('condition', 'status', 'remarks')
        }),
        ('Media', {
            'fields': ('asset_image',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
