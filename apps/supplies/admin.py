from django.contrib import admin
from .models import SupplyCategory, Supply, SupplyTransaction


@admin.register(SupplyCategory)
class SupplyCategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'is_active', 'created_at')
    search_fields = ('name', 'code')
    list_filter = ('is_active',)


@admin.register(Supply)
class SupplyAdmin(admin.ModelAdmin):
    list_display = ('supply_code', 'item_name', 'category', 'brand', 'unit', 'reorder_level', 'is_active')
    search_fields = ('supply_code', 'item_name', 'brand__name')
    list_filter = ('category', 'unit', 'is_active')
    readonly_fields = ('supply_code', 'created_at', 'updated_at')


@admin.register(SupplyTransaction)
class SupplyTransactionAdmin(admin.ModelAdmin):
    list_display = ('transaction_date', 'transaction_type', 'supply', 'quantity', 'department', 'employee', 'processed_by')
    search_fields = ('supply__supply_code', 'supply__item_name', 'reference_number', 'employee__first_name', 'employee__last_name')
    list_filter = ('transaction_type', 'department', 'transaction_date')
    readonly_fields = [f.name for f in SupplyTransaction._meta.fields]

    def has_add_permission(self, request):
        return True

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
