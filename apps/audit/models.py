from django.db import models
from django.conf import settings


class AuditLog(models.Model):
    """Immutable audit trail for tracking important system actions."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='audit_logs',
    )
    action = models.CharField(max_length=50, db_index=True)
    model_name = models.CharField(max_length=100, db_index=True)
    object_id = models.CharField(max_length=50, blank=True)
    object_repr = models.CharField(max_length=300, blank=True)
    changes = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-timestamp']
        verbose_name = 'Audit Log'
        verbose_name_plural = 'Audit Logs'

    def __str__(self):
        return f'{self.user} - {self.action} - {self.model_name} ({self.timestamp:%Y-%m-%d %H:%M})'

    def delete(self, *args, **kwargs):
        """Prevent casual deletion of audit logs."""
        raise PermissionError("Audit logs cannot be deleted.")

    def save(self, *args, **kwargs):
        """Prevent modification of existing audit logs."""
        if self.pk:
            raise PermissionError("Audit logs cannot be modified after creation.")
        super().save(*args, **kwargs)
