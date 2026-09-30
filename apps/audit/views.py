from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.views.generic import ListView
from django.db.models import Q

from .models import AuditLog


class AdminRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    def test_func(self):
        return self.request.user.is_admin


class AuditLogListView(AdminRequiredMixin, ListView):
    """List audit log entries (admin only, read-only)."""
    model = AuditLog
    template_name = 'audit/audit_log_list.html'
    context_object_name = 'logs'
    paginate_by = 50

    def get_queryset(self):
        queryset = super().get_queryset().select_related('user')
        q = self.request.GET.get('q')
        action = self.request.GET.get('action')

        if q:
            queryset = queryset.filter(
                Q(action__icontains=q) |
                Q(model_name__icontains=q) |
                Q(object_repr__icontains=q) |
                Q(user__username__icontains=q)
            )
        if action:
            queryset = queryset.filter(action=action)

        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['page_title'] = 'Audit Logs'
        # Get distinct action types for filtering
        context['action_types'] = (
            AuditLog.objects.values_list('action', flat=True)
            .distinct()
            .order_by('action')
        )
        return context
