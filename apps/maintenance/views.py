from django.views.generic import ListView, DetailView, FormView, View
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Q
from django.utils import timezone

from apps.inventory.models import Asset, AssetCategory
from apps.organizations.models import Department
from .models import AssetMaintenance
from .forms import (
    MaintenanceReportForm,
    MaintenanceAssessmentForm,
    MaintenanceStartRepairForm,
    MaintenanceCompleteRepairForm,
    MaintenanceCancelForm,
    MaintenanceForReplacementForm
)
from . import services


def check_admin_authority(user):
    """Enforces exclusive admin / property custodian authority."""
    if not (getattr(user, 'is_admin', False) or getattr(user, 'role', '') == 'ADMIN'):
        raise PermissionDenied("You do not have administrative authority to manage asset maintenance workflows.")


class AdminRequiredMixin(LoginRequiredMixin):
    """Restricts view exclusively to System Administrators / Property Custodians."""
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        check_admin_authority(request.user)
        return super().dispatch(request, *args, **kwargs)


class NonFacultyRequiredMixin(LoginRequiredMixin):
    """Restricts queue views to Admin, Dean, and Department Chair. Faculty redirected to My Reports."""
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if getattr(request.user, 'role', '') == 'FACULTY':
            messages.info(request, "Redirected to your personal equipment maintenance reports.")
            return redirect('maintenance:my_reports')
        return super().dispatch(request, *args, **kwargs)


def check_maintenance_view_permission(user, maintenance):
    """
    Validates whether the user is authorized to inspect this maintenance case.
    - Admin & Dean: full college-wide access.
    - Department Chair: scoped to their department's assets or reporter.
    - Faculty: access restricted exclusively to issues they filed, or for equipment currently
      assigned to them or on loan to them.
    """
    if getattr(user, 'is_admin', False) or getattr(user, 'role', '') in ['ADMIN', 'DEAN']:
        return True

    if getattr(user, 'role', '') == 'DEPT_CHAIR':
        chair_dept = getattr(getattr(user, 'employee_profile', None), 'department', None)
        if chair_dept and (
            maintenance.asset.department_id == chair_dept.pk or
            getattr(getattr(maintenance.reported_by, 'employee_profile', None), 'department_id', None) == chair_dept.pk
        ):
            return True
        raise PermissionDenied("You do not have permission to view maintenance cases outside your department.")

    if getattr(user, 'role', '') == 'FACULTY':
        is_reporter = maintenance.reported_by_id == user.pk
        is_assigned = maintenance.asset.assignments.filter(employee__user=user, status='ACTIVE').exists()
        is_borrowed = maintenance.asset.borrowings.filter(borrower__user=user, status__in=['RELEASED', 'OVERDUE']).exists()
        if is_reporter or is_assigned or is_borrowed:
            return True
        raise PermissionDenied("You do not have permission to view maintenance cases for equipment not assigned or reported by you.")

    raise PermissionDenied("You do not have permission to view this maintenance case.")


# ==============================================================================
# QUEUE & LIST VIEWS
# ==============================================================================

class MaintenanceCaseListView(NonFacultyRequiredMixin, ListView):
    """
    Primary administrative queue of open maintenance cases (REPORTED, ASSESSED, IN_REPAIR).
    URL: /maintenance/
    """
    model = AssetMaintenance
    template_name = 'maintenance/maintenance_list.html'
    context_object_name = 'cases'
    paginate_by = 20

    def get_queryset(self):
        user = self.request.user
        qs = AssetMaintenance.objects.filter(
            status__in=[
                AssetMaintenance.Status.REPORTED,
                AssetMaintenance.Status.ASSESSED,
                AssetMaintenance.Status.IN_REPAIR
            ]
        ).select_related(
            'asset', 'asset__category', 'asset__department', 'asset__current_location',
            'reported_by'
        )

        # Department scoping for Chairs
        if getattr(user, 'role', '') == 'DEPT_CHAIR':
            chair_dept = getattr(getattr(user, 'employee_profile', None), 'department', None)
            if chair_dept:
                qs = qs.filter(asset__department=chair_dept)
            else:
                return qs.none()

        # Filtering
        status = self.request.GET.get('status')
        severity = self.request.GET.get('severity')
        dept_id = self.request.GET.get('department')
        cat_id = self.request.GET.get('category')
        q = self.request.GET.get('q', '').strip()

        if q:
            qs = qs.filter(
                Q(case_number__icontains=q) |
                Q(asset__asset_code__icontains=q) |
                Q(asset__item_name__icontains=q) |
                Q(asset__property_number__icontains=q) |
                Q(asset__serial_number__icontains=q) |
                Q(issue_title__icontains=q) |
                Q(reported_by__first_name__icontains=q) |
                Q(reported_by__last_name__icontains=q) |
                Q(service_provider__icontains=q)
            )

        if status:
            qs = qs.filter(status=status)
        if severity:
            qs = qs.filter(severity=severity)
        if dept_id and not (getattr(user, 'role', '') == 'DEPT_CHAIR'):
            qs = qs.filter(asset__department_id=dept_id)
        if cat_id:
            qs = qs.filter(asset__category_id=cat_id)

        return qs.order_by('-reported_at')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        context['page_title'] = 'Active Maintenance & Repair Queue'

        base_qs = AssetMaintenance.objects.all()
        if getattr(user, 'role', '') == 'DEPT_CHAIR':
            chair_dept = getattr(getattr(user, 'employee_profile', None), 'department', None)
            if chair_dept:
                base_qs = base_qs.filter(asset__department=chair_dept)
            context['departments'] = Department.objects.filter(pk=chair_dept.pk) if chair_dept else Department.objects.none()
        else:
            context['departments'] = Department.objects.filter(is_active=True)

        context['categories'] = AssetCategory.objects.filter(is_active=True)
        context['statuses'] = [
            (s.value, s.label) for s in [
                AssetMaintenance.Status.REPORTED,
                AssetMaintenance.Status.ASSESSED,
                AssetMaintenance.Status.IN_REPAIR
            ]
        ]
        context['severities'] = AssetMaintenance.Severity.choices

        # Aggregate metrics
        context['total_open_count'] = base_qs.filter(
            status__in=[AssetMaintenance.Status.REPORTED, AssetMaintenance.Status.ASSESSED, AssetMaintenance.Status.IN_REPAIR]
        ).count()
        context['in_repair_count'] = base_qs.filter(status=AssetMaintenance.Status.IN_REPAIR).count()
        context['critical_count'] = base_qs.filter(
            status__in=[AssetMaintenance.Status.REPORTED, AssetMaintenance.Status.ASSESSED, AssetMaintenance.Status.IN_REPAIR],
            severity=AssetMaintenance.Severity.CRITICAL
        ).count()

        query_params = self.request.GET.copy()
        if 'page' in query_params:
            query_params.pop('page')
        context['query_string'] = query_params.urlencode()
        return context


class MaintenanceHistoryListView(NonFacultyRequiredMixin, ListView):
    """
    Completed, replaced, and cancelled maintenance records archive.
    URL: /maintenance/history/
    """
    model = AssetMaintenance
    template_name = 'maintenance/maintenance_history_list.html'
    context_object_name = 'cases'
    paginate_by = 25

    def get_queryset(self):
        user = self.request.user
        qs = AssetMaintenance.objects.filter(
            status__in=[
                AssetMaintenance.Status.COMPLETED,
                AssetMaintenance.Status.FOR_REPLACEMENT,
                AssetMaintenance.Status.CANCELLED
            ]
        ).select_related(
            'asset', 'asset__category', 'asset__department', 'reported_by', 'returned_to_service_by'
        )

        if getattr(user, 'role', '') == 'DEPT_CHAIR':
            chair_dept = getattr(getattr(user, 'employee_profile', None), 'department', None)
            if chair_dept:
                qs = qs.filter(asset__department=chair_dept)
            else:
                return qs.none()

        status = self.request.GET.get('status')
        dept_id = self.request.GET.get('department')
        cat_id = self.request.GET.get('category')
        q = self.request.GET.get('q', '').strip()

        if q:
            qs = qs.filter(
                Q(case_number__icontains=q) |
                Q(asset__asset_code__icontains=q) |
                Q(asset__item_name__icontains=q) |
                Q(asset__property_number__icontains=q) |
                Q(issue_title__icontains=q) |
                Q(action_taken__icontains=q) |
                Q(service_provider__icontains=q)
            )

        if status:
            qs = qs.filter(status=status)
        if dept_id and not (getattr(user, 'role', '') == 'DEPT_CHAIR'):
            qs = qs.filter(asset__department_id=dept_id)
        if cat_id:
            qs = qs.filter(asset__category_id=cat_id)

        return qs.order_by('-updated_at')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['page_title'] = 'Maintenance & Repair History'
        context['statuses'] = [
            (AssetMaintenance.Status.COMPLETED, 'Completed'),
            (AssetMaintenance.Status.FOR_REPLACEMENT, 'For Replacement'),
            (AssetMaintenance.Status.CANCELLED, 'Cancelled'),
        ]
        context['categories'] = AssetCategory.objects.filter(is_active=True)
        context['departments'] = Department.objects.filter(is_active=True)

        query_params = self.request.GET.copy()
        if 'page' in query_params:
            query_params.pop('page')
        context['query_string'] = query_params.urlencode()
        return context


class MyMaintenanceListView(LoginRequiredMixin, ListView):
    """
    Mobile-first faculty portal showing maintenance issues filed by the logged-in user,
    or involving equipment currently assigned to their accountability.
    URL: /maintenance/my-reports/
    """
    model = AssetMaintenance
    template_name = 'maintenance/my_maintenance_list.html'
    context_object_name = 'cases'
    paginate_by = 15

    def get_queryset(self):
        user = self.request.user
        return AssetMaintenance.objects.filter(
            Q(reported_by=user) |
            Q(asset__assignments__employee__user=user, asset__assignments__status='ACTIVE') |
            Q(asset__borrowings__borrower__user=user, asset__borrowings__status__in=['RELEASED', 'OVERDUE'])
        ).distinct().select_related(
            'asset', 'asset__category', 'reported_by'
        ).order_by('-reported_at')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['page_title'] = 'My Equipment Maintenance Reports'
        user = self.request.user
        qs = self.get_queryset()
        context['open_count'] = qs.filter(
            status__in=[AssetMaintenance.Status.REPORTED, AssetMaintenance.Status.ASSESSED, AssetMaintenance.Status.IN_REPAIR]
        ).count()
        context['completed_count'] = qs.filter(status=AssetMaintenance.Status.COMPLETED).count()
        return context


# ==============================================================================
# REPORT INITIATION VIEW
# ==============================================================================

class MaintenanceReportCreateView(LoginRequiredMixin, FormView):
    """
    Files a defect/damage report.
    Pre-populates asset if specified via URL or GET parameter.
    URL: /maintenance/report/ or /maintenance/report/<str:asset_code>/
    """
    template_name = 'maintenance/maintenance_report_form.html'
    form_class = MaintenanceReportForm

    def dispatch(self, request, *args, **kwargs):
        self.initial_asset = None
        asset_code = kwargs.get('asset_code') or request.GET.get('asset_code')
        if asset_code:
            self.initial_asset = get_object_or_404(Asset, asset_code=asset_code)
            # Verify reporting authority for this specific asset
            services.validate_can_report(request.user, self.initial_asset)
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        kwargs['initial_asset'] = self.initial_asset
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['page_title'] = 'Report Equipment Defect / Damage'
        context['asset'] = self.initial_asset
        context['source'] = self.request.GET.get('source', '')
        return context

    def form_valid(self, form):
        asset = form.cleaned_data['asset']
        issue_title = form.cleaned_data['issue_title']
        issue_description = form.cleaned_data['issue_description']
        remarks = form.cleaned_data.get('remarks', '')

        source_param = self.request.GET.get('source')
        source = AssetMaintenance.ReportSource.MANUAL_REPORT
        if source_param in dict(AssetMaintenance.ReportSource.choices):
            source = source_param

        borrowing_ref = None
        borrowing_id = self.request.GET.get('borrowing')
        if borrowing_id:
            from apps.borrowing.models import AssetBorrowing
            borrowing_ref = AssetBorrowing.objects.filter(pk=borrowing_id, asset=asset).first()

        verification_ref = None
        verification_id = self.request.GET.get('verification')
        if verification_id:
            from apps.inventory.models import AssetVerification
            verification_ref = AssetVerification.objects.filter(pk=verification_id, asset=asset).first()

        try:
            maintenance = services.report_issue(
                asset=asset,
                reported_by=self.request.user,
                issue_title=issue_title,
                issue_description=issue_description,
                source=source,
                borrowing_ref=borrowing_ref,
                verification_ref=verification_ref,
                remarks=remarks,
                request=self.request
            )
            messages.success(
                self.request,
                f"Maintenance incident '{maintenance.case_number}' successfully reported for {asset.asset_code}."
            )
            return redirect('maintenance:maintenance_detail', pk=maintenance.pk)
        except ValidationError as e:
            form.add_error(None, e.message if hasattr(e, 'message') else str(e))
            return self.form_invalid(form)


# ==============================================================================
# DETAIL & ACTION VIEWS
# ==============================================================================

class MaintenanceDetailView(LoginRequiredMixin, DetailView):
    """
    Detailed inspection page for a maintenance case.
    Renders timeline, diagnostics, repair details, and authorized action buttons.
    URL: /maintenance/<int:pk>/
    """
    model = AssetMaintenance
    template_name = 'maintenance/maintenance_detail.html'
    context_object_name = 'case'

    def get_object(self, queryset=None):
        obj = super().get_object(queryset)
        check_maintenance_view_permission(self.request.user, obj)
        return obj

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        case = self.object
        context['page_title'] = f"Maintenance Case: {case.case_number}"
        context['asset'] = case.asset

        # Permissions
        is_admin = getattr(self.request.user, 'is_admin', False) or getattr(self.request.user, 'role', '') == 'ADMIN'
        context['can_assess'] = is_admin and case.status in [AssetMaintenance.Status.REPORTED, AssetMaintenance.Status.ASSESSED]
        context['can_start_repair'] = is_admin and case.status == AssetMaintenance.Status.ASSESSED
        context['can_complete'] = is_admin and case.status == AssetMaintenance.Status.IN_REPAIR
        context['can_replace'] = is_admin and case.status in [AssetMaintenance.Status.REPORTED, AssetMaintenance.Status.ASSESSED, AssetMaintenance.Status.IN_REPAIR]

        # Cancellation: Admin can cancel any open case; Faculty can only cancel their own REPORTED case
        can_cancel = False
        if is_admin and case.is_active:
            can_cancel = True
        elif case.reported_by_id == self.request.user.pk and case.status == AssetMaintenance.Status.REPORTED:
            can_cancel = True
        context['can_cancel'] = can_cancel

        return context


class MaintenanceAssessView(AdminRequiredMixin, FormView):
    """
    Admin diagnostic assessment and severity evaluation form.
    URL: /maintenance/<int:pk>/assess/
    """
    template_name = 'maintenance/maintenance_assess_form.html'
    form_class = MaintenanceAssessmentForm

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        check_admin_authority(request.user)
        self.maintenance = get_object_or_404(AssetMaintenance.objects.select_related('asset'), pk=kwargs['pk'])
        if self.maintenance.status not in [AssetMaintenance.Status.REPORTED, AssetMaintenance.Status.ASSESSED]:
            messages.error(request, f"Cannot assess case {self.maintenance.case_number}: current status is '{self.maintenance.get_status_display()}'.")
            return redirect('maintenance:maintenance_detail', pk=self.maintenance.pk)
        return super().dispatch(request, *args, **kwargs)

    def get_initial(self):
        return {
            'severity': self.maintenance.severity or AssetMaintenance.Severity.MEDIUM,
            'diagnosis': self.maintenance.diagnosis,
            'recommended_action': self.maintenance.recommended_action,
        }

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['case'] = self.maintenance
        context['asset'] = self.maintenance.asset
        context['page_title'] = f"Technical Assessment: {self.maintenance.case_number}"
        return context

    def form_valid(self, form):
        severity = form.cleaned_data['severity']
        diagnosis = form.cleaned_data['diagnosis']
        recommended_action = form.cleaned_data['recommended_action']
        remarks = form.cleaned_data['remarks']

        try:
            services.assess_issue(
                maintenance=self.maintenance,
                assessed_by=self.request.user,
                severity=severity,
                diagnosis=diagnosis,
                recommended_action=recommended_action,
                remarks=remarks,
                request=self.request
            )
            messages.success(self.request, f"Assessment recorded for case {self.maintenance.case_number}. Status updated to ASSESSED.")
            return redirect('maintenance:maintenance_detail', pk=self.maintenance.pk)
        except ValidationError as e:
            form.add_error(None, e.message if hasattr(e, 'message') else str(e))
            return self.form_invalid(form)


class MaintenanceStartRepairView(AdminRequiredMixin, FormView):
    """
    Admin action to dispatch asset to repair facility and transition asset to UNDER_MAINTENANCE.
    URL: /maintenance/<int:pk>/start-repair/
    """
    template_name = 'maintenance/maintenance_start_repair_form.html'
    form_class = MaintenanceStartRepairForm

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        check_admin_authority(request.user)
        self.maintenance = get_object_or_404(AssetMaintenance.objects.select_related('asset'), pk=kwargs['pk'])
        if self.maintenance.status != AssetMaintenance.Status.ASSESSED:
            messages.error(request, f"Case {self.maintenance.case_number} must be ASSESSED before starting repair.")
            return redirect('maintenance:maintenance_detail', pk=self.maintenance.pk)
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['case'] = self.maintenance
        context['asset'] = self.maintenance.asset
        context['page_title'] = f"Start Repair: {self.maintenance.case_number}"
        return context

    def form_valid(self, form):
        service_provider = form.cleaned_data['service_provider']
        technician = form.cleaned_data.get('technician', '')
        repair_started_at = form.cleaned_data.get('repair_started_at')
        remarks = form.cleaned_data.get('remarks', '')

        try:
            services.start_repair(
                maintenance=self.maintenance,
                user=self.request.user,
                service_provider=service_provider,
                technician=technician,
                repair_started_at=repair_started_at,
                remarks=remarks,
                request=self.request
            )
            messages.success(
                self.request,
                f"Repair started for {self.maintenance.case_number}. Asset '{self.maintenance.asset.asset_code}' is now marked UNDER MAINTENANCE."
            )
            return redirect('maintenance:maintenance_detail', pk=self.maintenance.pk)
        except ValidationError as e:
            form.add_error(None, e.message if hasattr(e, 'message') else str(e))
            return self.form_invalid(form)


class MaintenanceCompleteRepairView(AdminRequiredMixin, FormView):
    """
    Admin action to record completed repair details and restore asset to appropriate operational status.
    URL: /maintenance/<int:pk>/complete/
    """
    template_name = 'maintenance/maintenance_complete_form.html'
    form_class = MaintenanceCompleteRepairForm

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        check_admin_authority(request.user)
        self.maintenance = get_object_or_404(AssetMaintenance.objects.select_related('asset'), pk=kwargs['pk'])
        if self.maintenance.status != AssetMaintenance.Status.IN_REPAIR:
            messages.error(request, f"Case {self.maintenance.case_number} is not currently IN REPAIR.")
            return redirect('maintenance:maintenance_detail', pk=self.maintenance.pk)
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['case'] = self.maintenance
        context['asset'] = self.maintenance.asset
        context['page_title'] = f"Complete Repair: {self.maintenance.case_number}"
        return context

    def form_valid(self, form):
        final_condition = form.cleaned_data['final_condition']
        action_taken = form.cleaned_data.get('action_taken', '')
        parts_replaced = form.cleaned_data.get('parts_replaced', '')
        repair_cost = form.cleaned_data.get('repair_cost')
        repair_completed_at = form.cleaned_data.get('repair_completed_at')
        remarks = form.cleaned_data.get('remarks', '')

        try:
            services.complete_repair(
                maintenance=self.maintenance,
                user=self.request.user,
                final_condition=final_condition,
                action_taken=action_taken,
                parts_replaced=parts_replaced,
                repair_cost=repair_cost,
                repair_completed_at=repair_completed_at,
                remarks=remarks,
                request=self.request
            )
            self.maintenance.refresh_from_db()
            restored_status = self.maintenance.asset.get_status_display()
            messages.success(
                self.request,
                f"Maintenance {self.maintenance.case_number} completed. "
                f"Asset '{self.maintenance.asset.asset_code}' restored to service (Condition: {self.maintenance.get_final_condition_display()}, Status: {restored_status})."
            )
            return redirect('maintenance:maintenance_detail', pk=self.maintenance.pk)
        except ValidationError as e:
            form.add_error(None, e.message if hasattr(e, 'message') else str(e))
            return self.form_invalid(form)


class MaintenanceForReplacementView(AdminRequiredMixin, FormView):
    """
    Admin action to mark asset as unviable for repair and recommended for replacement.
    URL: /maintenance/<int:pk>/for-replacement/
    """
    template_name = 'maintenance/maintenance_for_replacement_form.html'
    form_class = MaintenanceForReplacementForm

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        check_admin_authority(request.user)
        self.maintenance = get_object_or_404(AssetMaintenance.objects.select_related('asset'), pk=kwargs['pk'])
        if self.maintenance.status not in [AssetMaintenance.Status.REPORTED, AssetMaintenance.Status.ASSESSED, AssetMaintenance.Status.IN_REPAIR]:
            messages.error(request, f"Case {self.maintenance.case_number} is already closed.")
            return redirect('maintenance:maintenance_detail', pk=self.maintenance.pk)
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['case'] = self.maintenance
        context['asset'] = self.maintenance.asset
        context['page_title'] = f"Mark For Replacement: {self.maintenance.case_number}"
        return context

    def form_valid(self, form):
        remarks = form.cleaned_data.get('remarks', '')
        try:
            services.mark_for_replacement(
                maintenance=self.maintenance,
                user=self.request.user,
                remarks=remarks,
                request=self.request
            )
            messages.warning(
                self.request,
                f"Case {self.maintenance.case_number} marked FOR REPLACEMENT. Asset '{self.maintenance.asset.asset_code}' is retained as DAMAGED pending future disposal."
            )
            return redirect('maintenance:maintenance_detail', pk=self.maintenance.pk)
        except ValidationError as e:
            form.add_error(None, e.message if hasattr(e, 'message') else str(e))
            return self.form_invalid(form)


class MaintenanceCancelView(LoginRequiredMixin, FormView):
    """
    Form for cancelling an open maintenance case.
    Enforces authorization: Admin can cancel open cases; Faculty can cancel only their own REPORTED cases.
    URL: /maintenance/<int:pk>/cancel/
    """
    template_name = 'maintenance/maintenance_cancel_form.html'
    form_class = MaintenanceCancelForm

    def dispatch(self, request, *args, **kwargs):
        self.maintenance = get_object_or_404(AssetMaintenance.objects.select_related('asset'), pk=kwargs['pk'])
        user = request.user
        is_admin = getattr(user, 'is_admin', False) or getattr(user, 'role', '') == 'ADMIN'
        is_owner = self.maintenance.reported_by_id == user.pk

        if not self.maintenance.is_active:
            messages.error(request, f"Case {self.maintenance.case_number} is already closed and cannot be cancelled.")
            return redirect('maintenance:maintenance_detail', pk=self.maintenance.pk)

        if not is_admin:
            if not is_owner or self.maintenance.status != AssetMaintenance.Status.REPORTED:
                raise PermissionDenied("You can only cancel equipment issue reports you personally filed that have not yet begun assessment or repair.")

        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['case'] = self.maintenance
        context['asset'] = self.maintenance.asset
        context['page_title'] = f"Cancel Maintenance Case: {self.maintenance.case_number}"
        return context

    def form_valid(self, form):
        reason = form.cleaned_data['cancellation_reason']
        try:
            services.cancel_maintenance(
                maintenance=self.maintenance,
                user=self.request.user,
                cancellation_reason=reason,
                request=self.request
            )
            messages.info(self.request, f"Maintenance case {self.maintenance.case_number} was successfully cancelled.")
            return redirect('maintenance:maintenance_detail', pk=self.maintenance.pk)
        except ValidationError as e:
            form.add_error(None, e.message if hasattr(e, 'message') else str(e))
            return self.form_invalid(form)
