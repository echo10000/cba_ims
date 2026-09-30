from django.contrib.auth import views as auth_views
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.shortcuts import redirect, get_object_or_404
from django.urls import reverse_lazy
from django.views.generic import TemplateView, ListView, CreateView, UpdateView, View
from django.contrib import messages
from django.db.models import Q

from .models import User
from .forms import LoginForm, UserCreateForm, UserUpdateForm, PasswordChangeForm


class AdminRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """Mixin that requires the user to be an administrator."""
    def test_func(self):
        return self.request.user.is_admin


class DashboardView(LoginRequiredMixin, TemplateView):
    """Main dashboard view showing system overview."""
    template_name = 'accounts/dashboard.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['page_title'] = 'Dashboard'
        
        # Phase 1 and Inventory live stats
        try:
            from apps.inventory.models import Asset, AssetCategory, Brand
            from apps.organizations.models import Department, Location, Employee
            from apps.audit.models import AuditLog

            from apps.transfers.models import AssetTransfer
            from apps.borrowing.models import AssetBorrowing
            from apps.borrowing import services as borrowing_services

            # Synchronize overdue borrowings in background
            try:
                borrowing_services.refresh_overdue_status()
            except Exception:
                pass

            user = self.request.user
            chair_dept = None
            if getattr(user, 'role', '') == User.Role.DEPT_CHAIR:
                chair_dept = getattr(getattr(user, 'employee_profile', None), 'department', None)

            asset_qs = Asset.objects.all()
            if chair_dept:
                asset_qs = asset_qs.filter(department=chair_dept)

            context['total_assets'] = asset_qs.count()
            context['available_assets'] = asset_qs.filter(status=Asset.Status.AVAILABLE).count()
            context['assigned_assets'] = asset_qs.filter(status=Asset.Status.ASSIGNED).count()
            context['maintenance_assets'] = asset_qs.filter(status=Asset.Status.MAINTENANCE).count()
            context['borrowed_assets'] = asset_qs.filter(status=Asset.Status.BORROWED).count()
            context['damaged_assets'] = asset_qs.filter(status=Asset.Status.DAMAGED).count()

            # Chart datasets for operational analytics
            from django.db.models import Count
            # 1. Assets by Category
            cat_counts = (
                asset_qs.exclude(status=Asset.Status.DISPOSED)
                .values('category__name')
                .annotate(count=Count('id'))
                .order_by('-count')[:6]
            )
            context['category_chart_labels'] = [c['category__name'] or 'Uncategorized' for c in cat_counts]
            context['category_chart_data'] = [c['count'] for c in cat_counts]

            # 2. Assets by Condition
            cond_counts = (
                asset_qs.exclude(status=Asset.Status.DISPOSED)
                .values('condition')
                .annotate(count=Count('id'))
            )
            cond_dict = {c['condition']: c['count'] for c in cond_counts}
            context['condition_chart_labels'] = ['New', 'Good', 'Fair', 'Poor', 'Unserviceable']
            context['condition_chart_data'] = [
                cond_dict.get(Asset.Condition.NEW, 0),
                cond_dict.get(Asset.Condition.GOOD, 0),
                cond_dict.get(Asset.Condition.FAIR, 0),
                cond_dict.get(Asset.Condition.POOR, 0),
                cond_dict.get(Asset.Condition.UNSERVICEABLE, 0),
            ]

            # 3. Department or Location Distribution
            if not chair_dept:
                dept_counts = (
                    Asset.objects.exclude(status=Asset.Status.DISPOSED)
                    .values('department__name')
                    .annotate(count=Count('id'))
                    .order_by('-count')[:6]
                )
                context['department_chart_labels'] = [d['department__name'] or 'Unassigned' for d in dept_counts]
                context['department_chart_data'] = [d['count'] for d in dept_counts]
                context['department_chart_title'] = "Assets by Department"
            else:
                loc_counts = (
                    asset_qs.exclude(status=Asset.Status.DISPOSED)
                    .values('current_location__name')
                    .annotate(count=Count('id'))
                    .order_by('-count')[:6]
                )
                context['department_chart_labels'] = [l['current_location__name'] or 'Unassigned' for l in loc_counts]
                context['department_chart_data'] = [l['count'] for l in loc_counts]
                context['department_chart_title'] = f"Assets by Location ({chair_dept.name})"

            context['pending_transfers_count'] = AssetTransfer.objects.filter(
                status__in=[AssetTransfer.Status.PENDING, AssetTransfer.Status.APPROVED]
            ).count()

            context['pending_borrowings_count'] = AssetBorrowing.objects.filter(
                status=AssetBorrowing.Status.PENDING
            ).count()
            context['active_borrowings_count'] = AssetBorrowing.objects.filter(
                status__in=[AssetBorrowing.Status.RELEASED, AssetBorrowing.Status.OVERDUE]
            ).count()
            from django.utils import timezone
            context['overdue_borrowings_count'] = AssetBorrowing.objects.filter(
                Q(status=AssetBorrowing.Status.OVERDUE) |
                Q(status=AssetBorrowing.Status.RELEASED, requested_return__lt=timezone.now())
            ).count()

            from apps.maintenance.models import AssetMaintenance
            context['open_maintenance_count'] = AssetMaintenance.objects.filter(
                status__in=[
                    AssetMaintenance.Status.REPORTED,
                    AssetMaintenance.Status.ASSESSED,
                    AssetMaintenance.Status.IN_REPAIR
                ]
            ).count()
            context['critical_maintenance_count'] = AssetMaintenance.objects.filter(
                status__in=[
                    AssetMaintenance.Status.REPORTED,
                    AssetMaintenance.Status.ASSESSED,
                    AssetMaintenance.Status.IN_REPAIR
                ],
                severity=AssetMaintenance.Severity.CRITICAL
            ).count()

            from apps.supplies.models import Supply
            from apps.supplies import services as supply_services

            low_supplies = supply_services.get_low_stock_supplies()
            context['low_stock_supplies_count'] = len(low_supplies)
            context['out_of_stock_supplies_count'] = sum(1 for s in low_supplies if s.calculated_stock <= 0)

            from apps.disposals.models import AssetDisposal
            context['disposed_assets_count'] = Asset.objects.filter(status=Asset.Status.DISPOSED).count()
            context['pending_disposals_count'] = AssetDisposal.objects.filter(
                status__in=[AssetDisposal.Status.PENDING, AssetDisposal.Status.APPROVED]
            ).count()

            context['total_employees'] = Employee.objects.filter(is_active=True).count()
            context['total_departments'] = Department.objects.filter(is_active=True).count()
            context['total_locations'] = Location.objects.filter(is_active=True).count()
            context['total_categories'] = AssetCategory.objects.filter(is_active=True).count()
            context['total_brands'] = Brand.objects.filter(is_active=True).count()

            context['recent_activities'] = AuditLog.objects.select_related('user')[:7]
        except Exception:
            context['total_assets'] = 0
            context['available_assets'] = 0
            context['assigned_assets'] = 0
            context['maintenance_assets'] = 0
            context['borrowed_assets'] = 0
            context['damaged_assets'] = 0
            context['disposed_assets_count'] = 0
            context['pending_disposals_count'] = 0
            context['pending_transfers_count'] = 0
            context['pending_borrowings_count'] = 0
            context['active_borrowings_count'] = 0
            context['overdue_borrowings_count'] = 0
            context['open_maintenance_count'] = 0
            context['critical_maintenance_count'] = 0
            context['low_stock_supplies_count'] = 0
            context['out_of_stock_supplies_count'] = 0
            context['total_employees'] = 0
            context['total_departments'] = 0
            context['total_locations'] = 0
            context['recent_activities'] = []
            context['category_chart_labels'] = []
            context['category_chart_data'] = []
            context['condition_chart_labels'] = []
            context['condition_chart_data'] = []
            context['department_chart_labels'] = []
            context['department_chart_data'] = []
            context['department_chart_title'] = "Assets Distribution"

        return context


class LoginView(auth_views.LoginView):
    """Custom login view with Bootstrap-styled form."""
    form_class = LoginForm
    template_name = 'accounts/login.html'
    redirect_authenticated_user = True


class LogoutView(auth_views.LogoutView):
    """Logout view that redirects to login page."""
    next_page = '/accounts/login/'


class PasswordChangeView(auth_views.PasswordChangeView):
    """Password change view for authenticated users."""
    form_class = PasswordChangeForm
    template_name = 'accounts/password_change.html'
    success_url = reverse_lazy('dashboard')

    def form_valid(self, form):
        messages.success(self.request, 'Your password was successfully updated!')
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['page_title'] = 'Change Password'
        return context


class UserListView(AdminRequiredMixin, ListView):
    """List all users with search and role filtering (admin only)."""
    model = User
    template_name = 'accounts/user_list.html'
    context_object_name = 'users'
    paginate_by = 20

    def get_queryset(self):
        queryset = super().get_queryset()
        query = self.request.GET.get('q')
        role = self.request.GET.get('role')
        if query:
            queryset = queryset.filter(
                Q(username__icontains=query) |
                Q(first_name__icontains=query) |
                Q(last_name__icontains=query) |
                Q(email__icontains=query)
            )
        if role:
            queryset = queryset.filter(role=role)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['roles'] = User.Role.choices
        context['page_title'] = 'User Management'
        return context


class UserCreateView(AdminRequiredMixin, CreateView):
    """Create a new user (admin only)."""
    model = User
    form_class = UserCreateForm
    template_name = 'accounts/user_form.html'
    success_url = reverse_lazy('accounts:user_list')

    def form_valid(self, form):
        messages.success(self.request, f"User '{form.cleaned_data['username']}' created successfully.")
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['page_title'] = 'Create User'
        return context


class UserUpdateView(AdminRequiredMixin, UpdateView):
    """Update an existing user (admin only)."""
    model = User
    form_class = UserUpdateForm
    template_name = 'accounts/user_form.html'
    success_url = reverse_lazy('accounts:user_list')

    def form_valid(self, form):
        messages.success(self.request, f"User '{form.cleaned_data['username']}' updated successfully.")
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['page_title'] = 'Edit User'
        return context


class UserToggleActiveView(AdminRequiredMixin, View):
    """Toggle user active status (admin only, POST only)."""
    def post(self, request, pk, *args, **kwargs):
        user = get_object_or_404(User, pk=pk)
        if user == request.user:
            messages.error(request, "You cannot deactivate your own account.")
        else:
            user.is_active = not user.is_active
            user.save(update_fields=['is_active'])
            status = "activated" if user.is_active else "deactivated"
            messages.success(request, f"User '{user.username}' has been {status}.")
        return redirect('accounts:user_list')
