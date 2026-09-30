from django.contrib import admin
from .models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    """Read-only admin for audit logs."""
    list_display = ('timestamp', 'user', 'action', 'model_name', 'object_repr')
    list_filter = ('action', 'model_name', 'timestamp')
    search_fields = ('action', 'model_name', 'object_repr', 'user__username')
    readonly_fields = ('user', 'action', 'model_name', 'object_id', 'object_repr',
                       'changes', 'ip_address', 'timestamp')
    ordering = ('-timestamp',)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
