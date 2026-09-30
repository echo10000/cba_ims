from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse_lazy, reverse
from django.views.generic import ListView, DetailView, FormView, TemplateView, View
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Q
from django.utils import timezone

from .models import AssetAssignment
from .forms import AssetAssignmentForm, AssetReturnForm
from . import services
from apps.inventory.models import Asset, AssetCategory
from apps.organizations.models import Department, Employee


class AssignmentViewAccessMixin(LoginRequiredMixin, UserPassesTestMixin):
    """
    Grants access to general assignment lists for ADMIN, DEAN, and DEPT_CHAIR.
    Directs FACULTY to their own 'My Accountability' page.
    """
    def test_func(self):
        user = self.request.user
        if not user.is_authenticated:
            return False
        return (
            getattr(user, 'is_admin', False) or 
            getattr(user, 'role', '') in [user.Role.ADMIN, user.Role.DEAN, user.Role.DEPT_CHAIR]
        )

    def handle_no_permission(self):
        if self.request.user.is_authenticated and getattr(self.request.user, 'role', '') == 'FACULTY':
            return redirect('assignments:my_accountability')
        return super().handle_no_permission()


class AdminRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """Restricts view exclusively to System Administrators / Property Custodians."""
    def test_func(self):
        return self.request.user.is_authenticated and getattr(self.request.user, 'is_admin', False)


# ==============================================================================
# ASSIGNMENT LIST VIEWS
# ==============================================================================

class CurrentAssignmentListView(AssignmentViewAccessMixin, ListView):
    """
    Displays currently active asset assignments with search, combined filters,
    and role-based department scoping.
    """
    model = AssetAssignment
    template_name = 'assignments/current_assignment_list.html'
    context_object_name = 'assignments'
    paginate_by = 15

    def get_queryset(self):
        user = self.request.user
        qs = AssetAssignment.objects.filter(status=AssetAssignment.Status.ACTIVE).select_related(
            'asset', 'asset__category', 'asset__brand', 'asset__current_location',
            'employee', 'employee__department', 'assigned_by'
        )

        # Scoping: Department chairs only see assignments for their department
        if getattr(user, 'is_admin', False) or getattr(user, 'role', '') == 'DEAN':
            pass
        elif getattr(user, 'role', '') == 'DEPT_CHAIR':
            chair_dept = getattr(getattr(user, 'employee_profile', None), 'department', None)
            if chair_dept:
                qs = qs.filter(Q(employee__department=chair_dept) | Q(asset__department=chair_dept))
            else:
                return qs.none()
        else:
            return qs.none()

        # Multi-field Search
        q = self.request.GET.get('q', '').strip()
        if q:
            qs = qs.filter(
                Q(asset__asset_code__icontains=q) |
                Q(asset__item_name__icontains=q) |
                Q(asset__property_number__icontains=q) |
                Q(asset__serial_number__icontains=q) |
                Q(employee__first_name__icontains=q) |
                Q(employee__last_name__icontains=q) |
                Q(employee__employee_id__icontains=q)
            )

        # Filters
        department = self.request.GET.get('department')
        category = self.request.GET.get('category')
        condition = self.request.GET.get('condition')

        if department and not (getattr(user, 'role', '') == 'DEPT_CHAIR'):
            qs = qs.filter(employee__department_id=department)
        if category:
            qs = qs.filter(asset__category_id=category)
        if condition:
            qs = qs.filter(condition_at_assignment=condition)

        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        context['page_title'] = 'Current Asset Assignments'
        context['categories'] = AssetCategory.objects.filter(is_active=True)
        context['conditions'] = Asset.Condition.choices

        if getattr(user, 'role', '') == 'DEPT_CHAIR':
            chair_dept = getattr(getattr(user, 'employee_profile', None), 'department', None)
            context['departments'] = Department.objects.filter(pk=chair_dept.pk) if chair_dept else Department.objects.none()
        else:
            context['departments'] = Department.objects.filter(is_active=True)

        query_params = self.request.GET.copy()
        if 'page' in query_params:
            query_params.pop('page')
        context['query_string'] = query_params.urlencode()

        return context


class AssignmentHistoryListView(AssignmentViewAccessMixin, ListView):
    """
    Displays permanent, read-only historical assignment records (returned equipment).
    """
    model = AssetAssignment
    template_name = 'assignments/assignment_history_list.html'
    context_object_name = 'assignments'
    paginate_by = 15

    def get_queryset(self):
        user = self.request.user
        qs = AssetAssignment.objects.filter(status=AssetAssignment.Status.RETURNED).select_related(
            'asset', 'asset__category', 'asset__brand',
            'employee', 'employee__department', 'assigned_by', 'returned_by'
        )

        if getattr(user, 'is_admin', False) or getattr(user, 'role', '') == 'DEAN':
            pass
        elif getattr(user, 'role', '') == 'DEPT_CHAIR':
            chair_dept = getattr(getattr(user, 'employee_profile', None), 'department', None)
            if chair_dept:
                qs = qs.filter(Q(employee__department=chair_dept) | Q(asset__department=chair_dept))
            else:
                return qs.none()
        else:
            return qs.none()

        q = self.request.GET.get('q', '').strip()
        if q:
            qs = qs.filter(
                Q(asset__asset_code__icontains=q) |
                Q(asset__item_name__icontains=q) |
                Q(employee__first_name__icontains=q) |
                Q(employee__last_name__icontains=q)
            )

        department = self.request.GET.get('department')
        if department and not (getattr(user, 'role', '') == 'DEPT_CHAIR'):
            qs = qs.filter(employee__department_id=department)

        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['page_title'] = 'Assignment & Accountability History'
        context['departments'] = Department.objects.filter(is_active=True)

        query_params = self.request.GET.copy()
        if 'page' in query_params:
            query_params.pop('page')
        context['query_string'] = query_params.urlencode()

        return context


# ==============================================================================
# ASSIGN & RETURN ACTION WORKFLOWS
# ==============================================================================

class AssetAssignView(AdminRequiredMixin, FormView):
    """
    Processes the formal allocation of a durable asset to an employee.
    Uses atomic service with database row locking.
    """
    form_class = AssetAssignmentForm
    template_name = 'assignments/assignment_form.html'

    def get_asset(self):
        asset_code = self.kwargs.get('asset_code') or self.request.GET.get('asset')
        if asset_code:
            return get_object_or_404(Asset, asset_code=asset_code)
        return None

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['asset'] = self.get_asset()
        return kwargs

    def form_valid(self, form):
        asset = form.cleaned_data['asset']
        employee = form.cleaned_data['employee']
        assigned_date = form.cleaned_data['assigned_date']
        expected_return_date = form.cleaned_data.get('expected_return_date')
        purpose = form.cleaned_data.get('purpose', '')
        remarks = form.cleaned_data.get('remarks', '')

        try:
            assignment = services.assign_asset(
                asset=asset,
                employee=employee,
                assigned_by=self.request.user,
                assigned_date=assigned_date,
                expected_return_date=expected_return_date,
                purpose=purpose,
                remarks=remarks,
                request=self.request
            )
            messages.success(
                self.request,
                f"Asset '{asset.asset_code}' successfully assigned to {employee.full_name}."
            )
            return redirect('inventory:asset_detail', asset_code=asset.asset_code)
        except ValidationError as e:
            form.add_error(None, e.message)
            return self.form_invalid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['page_title'] = 'Assign Asset'
        context['preselected_asset'] = self.get_asset()
        return context


class AssetReturnView(AdminRequiredMixin, View):
    """
    Dedicated return workflow: GET confirms return, POST executes atomic return.
    """
    template_name = 'assignments/assignment_confirm_return.html'

    def get_assignment(self, pk):
        return get_object_or_404(
            AssetAssignment.objects.select_related('asset', 'employee', 'employee__department'),
            pk=pk,
            status=AssetAssignment.Status.ACTIVE
        )

    def get(self, request, pk):
        assignment = self.get_assignment(pk)
        form = AssetReturnForm(initial={
            'returned_date': timezone.now().date(),
            'condition_at_return': assignment.asset.condition
        })
        return render(request, self.template_name, {
            'assignment': assignment,
            'form': form,
            'page_title': f"Return Asset: {assignment.asset.asset_code}"
        })

    def post(self, request, pk):
        assignment = self.get_assignment(pk)
        form = AssetReturnForm(request.POST)

        if form.is_valid():
            try:
                services.return_asset(
                    assignment=assignment,
                    returned_by=request.user,
                    returned_date=form.cleaned_data['returned_date'],
                    condition_at_return=form.cleaned_data['condition_at_return'],
                    remarks=form.cleaned_data.get('remarks', ''),
                    request=request
                )
                messages.success(
                    request,
                    f"Asset '{assignment.asset.asset_code}' returned successfully by {assignment.employee.full_name}."
                )
                return redirect('inventory:asset_detail', asset_code=assignment.asset.asset_code)
            except ValidationError as e:
                form.add_error(None, e.message)

        return render(request, self.template_name, {
            'assignment': assignment,
            'form': form,
            'page_title': f"Return Asset: {assignment.asset.asset_code}"
        })


# ==============================================================================
# FACULTY & STAFF ACCOUNTABILITY PROFILES
# ==============================================================================

class MyAccountabilityView(LoginRequiredMixin, TemplateView):
    """
    Mobile-first personal accountability view for faculty and staff members.
    Shows current assets, turnover history, and printable report button.
    """
    template_name = 'assignments/my_accountability.html'

    def get_employee(self):
        user = self.request.user
        if hasattr(user, 'employee_profile'):
            return user.employee_profile
        return None

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        employee = self.get_employee()
        context['employee'] = employee
        context['page_title'] = 'My Property Accountability'

        if employee:
            context['active_assignments'] = employee.assignments.filter(
                status=AssetAssignment.Status.ACTIVE
            ).select_related('asset', 'asset__category', 'asset__brand', 'asset__current_location')

            context['historical_assignments'] = employee.assignments.filter(
                status=AssetAssignment.Status.RETURNED
            ).select_related('asset', 'asset__category', 'assigned_by', 'returned_by')

            context['my_supply_issuances'] = employee.supply_issuances.select_related(
                'supply', 'supply__category', 'supply__brand', 'processed_by'
            ).order_by('-transaction_date', '-created_at')[:20]

            # Phase 7: Temporary Borrowings & Reservations
            context['my_active_borrowings'] = employee.borrowings.filter(
                status__in=['RELEASED', 'OVERDUE']
            ).select_related('asset', 'asset__category', 'asset__brand', 'released_by').order_by('requested_return')

            context['my_pending_reservations'] = employee.borrowings.filter(
                status__in=['PENDING', 'APPROVED']
            ).select_related('asset', 'asset__category', 'asset__brand', 'reviewed_by').order_by('requested_start')

            context['my_past_borrowings'] = employee.borrowings.filter(
                status__in=['RETURNED', 'REJECTED', 'CANCELLED']
            ).select_related('asset', 'asset__category', 'returned_to', 'reviewed_by').order_by('-requested_at')[:10]
        else:
            context['active_assignments'] = []
            context['historical_assignments'] = []
            context['my_supply_issuances'] = []
            context['my_active_borrowings'] = []
            context['my_pending_reservations'] = []
            context['my_past_borrowings'] = []

        return context


class PrintableAccountabilityView(LoginRequiredMixin, DetailView):
    """
    Printable browser report of an employee's property accountability with signature blocks.
    Enforces authorization: Admin, Dean, Department Chair (own dept), or the Employee themselves.
    """
    model = Employee
    template_name = 'assignments/printable_accountability.html'
    context_object_name = 'employee'
    pk_url_kwarg = 'employee_id'

    def get_object(self, queryset=None):
        emp = super().get_object(queryset)
        user = self.request.user

        # Authorization check
        if getattr(user, 'is_admin', False) or getattr(user, 'role', '') == 'DEAN':
            return emp
        if getattr(user, 'role', '') == 'DEPT_CHAIR':
            chair_dept = getattr(getattr(user, 'employee_profile', None), 'department', None)
            if chair_dept and emp.department == chair_dept:
                return emp
        if hasattr(user, 'employee_profile') and user.employee_profile.pk == emp.pk:
            return emp

        raise PermissionDenied("You are not authorized to view this employee's accountability report.")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        employee = self.object

        context['active_assignments'] = employee.assignments.filter(
            status=AssetAssignment.Status.ACTIVE
        ).select_related('asset', 'asset__category', 'asset__brand', 'asset__current_location')

        context['report_date'] = timezone.now().date()
        context['page_title'] = f"Accountability Certificate: {employee.full_name}"
        return context
