def get_client_ip(request):
    """Extract client IP address from request."""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        return x_forwarded_for.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')


def log_action(user, action, instance, changes=None, request=None):
    """
    Create an audit log entry.

    Args:
        user: The user performing the action
        action: String describing the action (e.g., 'CREATED', 'UPDATED', 'DELETED')
        instance: The model instance being acted upon
        changes: Optional dict of changes (old/new values)
        request: Optional HTTP request for IP extraction
    """
    from .models import AuditLog

    ip_address = None
    if request:
        ip_address = get_client_ip(request)

    AuditLog.objects.create(
        user=user,
        action=action,
        model_name=instance.__class__.__name__,
        object_id=str(instance.pk) if instance.pk else '',
        object_repr=str(instance)[:300],
        changes=changes or {},
        ip_address=ip_address,
    )
