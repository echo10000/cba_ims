from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse_lazy, reverse
from django.views.generic import ListView, DetailView, FormView, View
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Q
from django.utils import timezone

from .models import AssetTransfer
from .forms import AssetTransferRequestForm, TransferActionForm
from . import services
from apps.inventory.models import Asset
from apps.organizations.models import Department, Location


class TransferViewAccessMixin(LoginRequiredMixin, UserPassesTestMixin):
    """
    Grants access to transfer lists for ADMIN, DEAN, and DEPT_CHAIR.
    Restricts FACULTY.
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
            messages.warning(self.request, "Faculty accounts cannot browse administrative transfer records.")
            return redirect('assignments:my_accountability')
        return super().handle_no_permission()


class AdminRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """Restricts view exclusively to System Administrators / Property Custodians."""
    def test_func(self):
        return self.request.user.is_authenticated and getattr(self.request.user, 'is_admin', False)


# ==============================================================================
# TRANSFER LIST VIEWS
# ==============================================================================

class PendingTransferListView(TransferViewAccessMixin, ListView):
    """
    Displays active and open transfer requests (PENDING and APPROVED).
    Scoped by department for Department Chairs.
    """
    model = AssetTransfer
    template_name = 'transfers/pending_transfer_list.html'
    context_object_name = 'transfers'
    paginate_by = 15

    def get_queryset(self):
        user = self.request.user
        qs = AssetTransfer.objects.filter(
            status__in=[AssetTransfer.Status.PENDING, AssetTransfer.Status.APPROVED]
        ).select_related(
            'asset', 'asset__category', 'from_department', 'from_location',
            'to_department', 'to_location', 'requested_by', 'approved_by'
        )

        # Scoping: Department Chairs only see transfers involving their department
        if getattr(user, 'is_admin', False) or getattr(user, 'role', '') == 'DEAN':
            pass
        elif getattr(user, 'role', '') == 'DEPT_CHAIR':
            chair_dept = getattr(getattr(user, 'employee_profile', None), 'department', None)
            if chair_dept:
                qs = qs.filter(Q(from_department=chair_dept) | Q(to_department=chair_dept))
            else:
                return qs.none()
        else:
            return qs.none()

        # Multi-field search
        q = self.request.GET.get('q', '').strip()
        if q:
            qs = qs.filter(
                Q(asset__asset_code__icontains=q) |
                Q(asset__item_name__icontains=q) |
                Q(asset__property_number__icontains=q) |
                Q(asset__serial_number__icontains=q) |
                Q(from_location__name__icontains=q) |
                Q(to_location__name__icontains=q) |
                Q(reason__icontains=q)
            )

        # Department & Status Filters
        from_dept = self.request.GET.get('from_department')
        to_dept = self.request.GET.get('to_department')
        status = self.request.GET.get('status')

        if from_dept:
            qs = qs.filter(from_department_id=from_dept)
        if to_dept:
            qs = qs.filter(to_department_id=to_dept)
        if status:
            qs = qs.filter(status=status)

        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        context['page_title'] = 'Pending Asset Transfers'
        context['departments'] = Department.objects.filter(is_active=True)
        context['statuses'] = [
            (AssetTransfer.Status.PENDING, 'Pending Approval'),
            (AssetTransfer.Status.APPROVED, 'Approved'),
        ]

        query_params = self.request.GET.copy()
        if 'page' in query_params:
            query_params.pop('page')
        context['query_string'] = query_params.urlencode()

        return context


class TransferHistoryListView(TransferViewAccessMixin, ListView):
    """
    Displays permanent, read-only transfer history (COMPLETED, REJECTED, CANCELLED).
    """
    model = AssetTransfer
    template_name = 'transfers/transfer_history_list.html'
    context_object_name = 'transfers'
    paginate_by = 15

    def get_queryset(self):
        user = self.request.user
        qs = AssetTransfer.objects.filter(
            status__in=[
                AssetTransfer.Status.COMPLETED,
                AssetTransfer.Status.REJECTED,
                AssetTransfer.Status.CANCELLED
            ]
        ).select_related(
            'asset', 'asset__category', 'from_department', 'from_location',
            'to_department', 'to_location', 'requested_by', 'approved_by', 'processed_by'
        )

        if getattr(user, 'is_admin', False) or getattr(user, 'role', '') == 'DEAN':
            pass
        elif getattr(user, 'role', '') == 'DEPT_CHAIR':
            chair_dept = getattr(getattr(user, 'employee_profile', None), 'department', None)
            if chair_dept:
                qs = qs.filter(Q(from_department=chair_dept) | Q(to_department=chair_dept))
            else:
                return qs.none()
        else:
            return qs.none()

        q = self.request.GET.get('q', '').strip()
        if q:
            qs = qs.filter(
                Q(asset__asset_code__icontains=q) |
                Q(asset__item_name__icontains=q) |
                Q(reason__icontains=q) |
                Q(from_department__name__icontains=q) |
                Q(to_department__name__icontains=q)
            )

        department = self.request.GET.get('department')
        status = self.request.GET.get('status')

        if department:
            qs = qs.filter(Q(from_department_id=department) | Q(to_department_id=department))
        if status:
            qs = qs.filter(status=status)

        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['page_title'] = 'Asset Transfer History'
        context['departments'] = Department.objects.filter(is_active=True)
        context['statuses'] = [
            (AssetTransfer.Status.COMPLETED, 'Completed'),
            (AssetTransfer.Status.REJECTED, 'Rejected'),
            (AssetTransfer.Status.CANCELLED, 'Cancelled'),
        ]

        query_params = self.request.GET.copy()
        if 'page' in query_params:
            query_params.pop('page')
        context['query_string'] = query_params.urlencode()

        return context


# ==============================================================================
# TRANSFER WORKFLOW & ACTION VIEWS
# ==============================================================================

class TransferRequestView(AdminRequiredMixin, FormView):
    """
    Initiates a new asset transfer request.
    Displays read-only origin snapshots and preselected asset details.
    """
    form_class = AssetTransferRequestForm
    template_name = 'transfers/transfer_form.html'

    def get_asset(self):
        asset_code = self.kwargs.get('asset_code') or self.request.GET.get('asset')
        if asset_code:
            return get_object_or_404(
                Asset.objects.select_related('department', 'current_location', 'category'),
                asset_code=asset_code
            )
        return None

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['asset'] = self.get_asset()
        return kwargs

    def form_valid(self, form):
        asset = form.cleaned_data['asset']
        to_department = form.cleaned_data['to_department']
        to_location = form.cleaned_data.get('to_location')
        transfer_date = form.cleaned_data.get('transfer_date')
        reason = form.cleaned_data.get('reason', '')
        remarks = form.cleaned_data.get('remarks', '')

        try:
            transfer = services.request_transfer(
                asset=asset,
                to_department=to_department,
                to_location=to_location,
                requested_by=self.request.user,
                transfer_date=transfer_date,
                reason=reason,
                remarks=remarks,
                request=self.request
            )
            messages.success(
                self.request,
                f"Transfer request for asset '{asset.asset_code}' created successfully."
            )
            return redirect('transfers:pending_list')
        except ValidationError as e:
            form.add_error(None, e.message)
            return self.form_invalid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        asset = self.get_asset()
        context['page_title'] = 'Request Asset Transfer'
        context['preselected_asset'] = asset

        if asset:
            # Active assignment context (if assigned)
            context['current_assignment'] = asset.assignments.filter(
                status='ACTIVE'
            ).select_related('employee', 'employee__department').first()

        # Provide serialized location mapping for dynamic frontend dropdown filtering
        locations = Location.objects.filter(is_active=True).values('id', 'name', 'department_id', 'building', 'room_number')
        context['locations_json'] = list(locations)
        return context


class TransferDetailView(TransferViewAccessMixin, DetailView):
    """
    Dedicated detail view for an individual transfer transaction.
    """
    model = AssetTransfer
    template_name = 'transfers/transfer_detail.html'
    context_object_name = 'transfer'

    def get_object(self, queryset=None):
        obj = super().get_object(queryset)
        user = self.request.user

        if getattr(user, 'is_admin', False) or getattr(user, 'role', '') == 'DEAN':
            return obj
        if getattr(user, 'role', '') == 'DEPT_CHAIR':
            chair_dept = getattr(getattr(user, 'employee_profile', None), 'department', None)
            if chair_dept and (obj.from_department == chair_dept or obj.to_department == chair_dept):
                return obj
        raise PermissionDenied("You do not have permission to view this transfer record.")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['page_title'] = f"Transfer Details: {self.object.asset.asset_code}"
        return context


# ==============================================================================
# ACTION VIEWS (Admin only)
# ==============================================================================

class TransferApproveView(AdminRequiredMixin, View):
    """Admin endpoint to approve a pending transfer."""
    def post(self, request, pk):
        transfer = get_object_or_404(AssetTransfer, pk=pk)
        remarks = request.POST.get('remarks', '')
        try:
            services.approve_transfer(transfer=transfer, approved_by=request.user, remarks=remarks, request=request)
            messages.success(request, f"Transfer #{transfer.pk} for asset '{transfer.asset.asset_code}' approved.")
        except ValidationError as e:
            messages.error(request, e.message)
        return redirect('transfers:pending_list')


class TransferRejectView(AdminRequiredMixin, View):
    """Admin endpoint to reject a pending transfer."""
    def post(self, request, pk):
        transfer = get_object_or_404(AssetTransfer, pk=pk)
        reason = request.POST.get('reason', '') or request.POST.get('remarks', '')
        try:
            services.reject_transfer(transfer=transfer, rejected_by=request.user, reason=reason, request=request)
            messages.success(request, f"Transfer #{transfer.pk} for asset '{transfer.asset.asset_code}' rejected.")
        except ValidationError as e:
            messages.error(request, e.message)
        return redirect('transfers:pending_list')


class TransferCompleteView(AdminRequiredMixin, View):
    """Admin endpoint to execute and complete an authorized transfer."""
    def post(self, request, pk):
        transfer = get_object_or_404(AssetTransfer, pk=pk)
        remarks = request.POST.get('remarks', '')
        try:
            services.complete_transfer(transfer=transfer, processed_by=request.user, remarks=remarks, request=request)
            messages.success(
                request,
                f"Transfer #{transfer.pk} completed successfully. Asset '{transfer.asset.asset_code}' is now at "
                f"{transfer.to_department.name} / {transfer.to_location.name if transfer.to_location else 'No Location'}."
            )
            return redirect('inventory:asset_detail', asset_code=transfer.asset.asset_code)
        except ValidationError as e:
            messages.error(request, e.message)
            return redirect('transfers:pending_list')


class TransferCancelView(AdminRequiredMixin, View):
    """Admin endpoint to cancel an open transfer request."""
    def post(self, request, pk):
        transfer = get_object_or_404(AssetTransfer, pk=pk)
        reason = request.POST.get('reason', '') or request.POST.get('remarks', '')
        try:
            services.cancel_transfer(transfer=transfer, cancelled_by=request.user, reason=reason, request=request)
            messages.success(request, f"Transfer #{transfer.pk} cancelled.")
        except ValidationError as e:
            messages.error(request, e.message)
        return redirect('transfers:pending_list')
