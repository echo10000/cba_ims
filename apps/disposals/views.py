from django.shortcuts import render, get_object_or_404, redirect
from django.http import HttpResponse
from django.urls import reverse_lazy, reverse
from django.views.generic import ListView, DetailView, View
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Q

from apps.inventory.models import Asset
from apps.maintenance.models import AssetMaintenance
from .models import AssetDisposal
from .forms import (
    DisposalRequestForm, DisposalApproveForm, DisposalRejectForm,
    DisposalCancelForm, DisposalCompleteForm
)
from . import services


class AdminRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """Restricts view exclusively to System Administrators / Property Custodians."""
    def test_func(self):
        return self.request.user.is_authenticated and getattr(self.request.user, 'is_admin', False)


def check_admin_authority(user):
    """Raises PermissionDenied if user is not admin."""
    if not getattr(user, 'is_admin', False):
        raise PermissionDenied("Only administrators / property custodians can perform disposal actions.")


# ==============================================================================
# DISPOSAL LIST VIEWS
# ==============================================================================

class DisposalPendingListView(LoginRequiredMixin, ListView):
    """
    Lists pending and approved disposal requests awaiting action.
    Admin: all records. Dean: college-wide read. Chair: department-scoped. Faculty: 403.
    """
    model = AssetDisposal
    template_name = 'disposals/disposal_list.html'
    context_object_name = 'disposals'
    paginate_by = 15

    def dispatch(self, request, *args, **kwargs):
        user = request.user
        if not user.is_authenticated:
            return self.handle_no_permission()
        if getattr(user, 'role', '') == 'FACULTY':
            raise PermissionDenied("Faculty members do not have access to the disposal administration queue.")
        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self):
        user = self.request.user
        qs = AssetDisposal.objects.filter(
            status__in=[AssetDisposal.Status.PENDING, AssetDisposal.Status.APPROVED]
        ).select_related(
            'asset', 'asset__category', 'asset__department',
            'requested_by', 'reviewed_by'
        )

        # RBAC scoping
        if getattr(user, 'role', '') == 'DEPT_CHAIR':
            chair_dept = getattr(getattr(user, 'employee_profile', None), 'department', None)
            if chair_dept:
                qs = qs.filter(asset__department=chair_dept)
            else:
                return qs.none()

        # Search
        q = self.request.GET.get('q', '').strip()
        if q:
            qs = qs.filter(
                Q(disposal_number__icontains=q) |
                Q(asset__asset_code__icontains=q) |
                Q(asset__item_name__icontains=q) |
                Q(asset__property_number__icontains=q) |
                Q(reason__icontains=q)
            )

        # Status filter
        status = self.request.GET.get('status', '').strip()
        if status in [AssetDisposal.Status.PENDING, AssetDisposal.Status.APPROVED]:
            qs = qs.filter(status=status)

        # Department filter
        dept = self.request.GET.get('department', '').strip()
        if dept:
            qs = qs.filter(asset__department_id=dept)

        return qs.order_by('-requested_at')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['page_title'] = 'Pending Disposal Requests'
        context['view_type'] = 'pending'
        from apps.organizations.models import Department
        context['departments'] = Department.objects.filter(is_active=True).order_by('name')
        context['pending_count'] = AssetDisposal.objects.filter(status=AssetDisposal.Status.PENDING).count()
        context['approved_count'] = AssetDisposal.objects.filter(status=AssetDisposal.Status.APPROVED).count()
        return context


class DisposalHistoryListView(LoginRequiredMixin, ListView):
    """
    Archive of completed, rejected, and cancelled disposal records.
    """
    model = AssetDisposal
    template_name = 'disposals/disposal_list.html'
    context_object_name = 'disposals'
    paginate_by = 15

    def dispatch(self, request, *args, **kwargs):
        user = request.user
        if not user.is_authenticated:
            return self.handle_no_permission()
        if getattr(user, 'role', '') == 'FACULTY':
            raise PermissionDenied("Faculty members do not have access to disposal records.")
        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self):
        user = self.request.user
        qs = AssetDisposal.objects.filter(
            status__in=[
                AssetDisposal.Status.COMPLETED,
                AssetDisposal.Status.REJECTED,
                AssetDisposal.Status.CANCELLED,
            ]
        ).select_related(
            'asset', 'asset__category', 'asset__department',
            'requested_by', 'reviewed_by', 'processed_by'
        )

        # RBAC scoping
        if getattr(user, 'role', '') == 'DEPT_CHAIR':
            chair_dept = getattr(getattr(user, 'employee_profile', None), 'department', None)
            if chair_dept:
                qs = qs.filter(asset__department=chair_dept)
            else:
                return qs.none()

        # Search
        q = self.request.GET.get('q', '').strip()
        if q:
            qs = qs.filter(
                Q(disposal_number__icontains=q) |
                Q(asset__asset_code__icontains=q) |
                Q(asset__item_name__icontains=q) |
                Q(asset__property_number__icontains=q) |
                Q(reference_number__icontains=q) |
                Q(reason__icontains=q)
            )

        # Status filter
        status = self.request.GET.get('status', '').strip()
        if status in [AssetDisposal.Status.COMPLETED, AssetDisposal.Status.REJECTED, AssetDisposal.Status.CANCELLED]:
            qs = qs.filter(status=status)

        # Method filter
        method = self.request.GET.get('method', '').strip()
        if method:
            qs = qs.filter(disposal_method=method)

        # Department filter
        dept = self.request.GET.get('department', '').strip()
        if dept:
            qs = qs.filter(asset__department_id=dept)

        # Condition filter
        condition = self.request.GET.get('condition', '').strip()
        if condition:
            qs = qs.filter(condition_at_disposal=condition)

        return qs.order_by('-completed_at', '-requested_at')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['page_title'] = 'Disposal History'
        context['view_type'] = 'history'
        from apps.organizations.models import Department
        context['departments'] = Department.objects.filter(is_active=True).order_by('name')
        context['disposal_methods'] = AssetDisposal.DisposalMethod.choices
        context['condition_choices'] = Asset.Condition.choices
        context['completed_count'] = AssetDisposal.objects.filter(status=AssetDisposal.Status.COMPLETED).count()
        return context


# ==============================================================================
# DISPOSAL DETAIL
# ==============================================================================

class DisposalDetailView(LoginRequiredMixin, DetailView):
    """
    Detailed view of a disposal record with lifecycle actions.
    """
    model = AssetDisposal
    template_name = 'disposals/disposal_detail.html'
    context_object_name = 'disposal'

    def get_queryset(self):
        return AssetDisposal.objects.select_related(
            'asset', 'asset__category', 'asset__brand', 'asset__department',
            'asset__current_location', 'requested_by', 'reviewed_by',
            'processed_by', 'recommended_by', 'maintenance_reference'
        )

    def get_object(self, queryset=None):
        obj = super().get_object(queryset)
        user = self.request.user

        if getattr(user, 'is_admin', False) or getattr(user, 'role', '') == 'DEAN':
            return obj

        if getattr(user, 'role', '') == 'DEPT_CHAIR':
            chair_dept = getattr(getattr(user, 'employee_profile', None), 'department', None)
            if not chair_dept or obj.asset.department != chair_dept:
                raise PermissionDenied("You do not have permission to view disposal records outside your department.")
            return obj

        raise PermissionDenied("You do not have permission to view this disposal record.")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['page_title'] = f"Disposal: {self.object.disposal_number}"
        context['is_admin'] = getattr(self.request.user, 'is_admin', False)
        return context


# ==============================================================================
# DISPOSAL WORKFLOW VIEWS
# ==============================================================================

class DisposalRequestView(AdminRequiredMixin, View):
    """Initiates a disposal request."""

    def get(self, request, asset_code=None):
        asset_instance = None
        maintenance_ref = None
        if asset_code:
            asset_instance = get_object_or_404(Asset, asset_code=asset_code)
        # Check if coming from maintenance FOR_REPLACEMENT
        maint_pk = request.GET.get('maintenance_ref')
        if maint_pk:
            maintenance_ref = AssetMaintenance.objects.filter(
                pk=maint_pk, status=AssetMaintenance.Status.FOR_REPLACEMENT
            ).first()
            if maintenance_ref and not asset_instance:
                asset_instance = maintenance_ref.asset

        form = DisposalRequestForm(
            user=request.user,
            asset_instance=asset_instance,
            maintenance_ref=maintenance_ref,
        )
        return render(request, 'disposals/disposal_request_form.html', {
            'form': form,
            'asset': asset_instance,
            'maintenance_ref': maintenance_ref,
            'page_title': 'Request Asset Disposal',
        })

    def post(self, request, asset_code=None):
        asset_instance = None
        maintenance_ref = None
        if asset_code:
            asset_instance = get_object_or_404(Asset, asset_code=asset_code)
        maint_pk = request.POST.get('maintenance_ref') or request.GET.get('maintenance_ref')
        if maint_pk:
            maintenance_ref = AssetMaintenance.objects.filter(
                pk=maint_pk, status=AssetMaintenance.Status.FOR_REPLACEMENT
            ).first()
            if maintenance_ref and not asset_instance:
                asset_instance = maintenance_ref.asset

        form = DisposalRequestForm(
            request.POST,
            user=request.user,
            asset_instance=asset_instance,
            maintenance_ref=maintenance_ref,
        )
        if form.is_valid():
            asset = form.cleaned_data['asset']
            try:
                disposal = services.request_disposal(
                    asset=asset,
                    requested_by=request.user,
                    reason=form.cleaned_data['reason'],
                    condition_at_disposal=form.cleaned_data['condition_at_disposal'],
                    maintenance_reference=maintenance_ref,
                    remarks=form.cleaned_data.get('remarks', ''),
                    request=request,
                )
                messages.success(request, f"Disposal request {disposal.disposal_number} created successfully.")
                return redirect('disposals:disposal_detail', pk=disposal.pk)
            except ValidationError as e:
                messages.error(request, str(e.message if hasattr(e, 'message') else e))

        return render(request, 'disposals/disposal_request_form.html', {
            'form': form,
            'asset': asset_instance,
            'maintenance_ref': maintenance_ref,
            'page_title': 'Request Asset Disposal',
        })


class DisposalApproveView(AdminRequiredMixin, View):
    """Approves a pending disposal request."""

    def dispatch(self, request, *args, **kwargs):
        check_admin_authority(request.user)
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, pk):
        disposal = get_object_or_404(AssetDisposal, pk=pk)
        if disposal.status != AssetDisposal.Status.PENDING:
            messages.warning(request, f"Disposal {disposal.disposal_number} is not pending approval.")
            return redirect('disposals:disposal_detail', pk=pk)
        form = DisposalApproveForm()
        return render(request, 'disposals/disposal_approve_form.html', {
            'form': form,
            'disposal': disposal,
            'page_title': f"Approve: {disposal.disposal_number}",
        })

    def post(self, request, pk):
        disposal = get_object_or_404(AssetDisposal, pk=pk)
        form = DisposalApproveForm(request.POST)
        if form.is_valid():
            try:
                services.approve_disposal(
                    disposal=disposal,
                    reviewed_by=request.user,
                    review_remarks=form.cleaned_data.get('review_remarks', ''),
                    request=request,
                )
                messages.success(request, f"Disposal {disposal.disposal_number} approved.")
                return redirect('disposals:disposal_detail', pk=pk)
            except ValidationError as e:
                messages.error(request, str(e.message if hasattr(e, 'message') else e))
        return render(request, 'disposals/disposal_approve_form.html', {
            'form': form,
            'disposal': disposal,
            'page_title': f"Approve: {disposal.disposal_number}",
        })


class DisposalRejectView(AdminRequiredMixin, View):
    """Rejects a pending disposal request."""

    def dispatch(self, request, *args, **kwargs):
        check_admin_authority(request.user)
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, pk):
        disposal = get_object_or_404(AssetDisposal, pk=pk)
        if disposal.status != AssetDisposal.Status.PENDING:
            messages.warning(request, f"Disposal {disposal.disposal_number} is not pending.")
            return redirect('disposals:disposal_detail', pk=pk)
        form = DisposalRejectForm()
        return render(request, 'disposals/disposal_reject_form.html', {
            'form': form,
            'disposal': disposal,
            'page_title': f"Reject: {disposal.disposal_number}",
        })

    def post(self, request, pk):
        disposal = get_object_or_404(AssetDisposal, pk=pk)
        form = DisposalRejectForm(request.POST)
        if form.is_valid():
            try:
                services.reject_disposal(
                    disposal=disposal,
                    reviewed_by=request.user,
                    review_remarks=form.cleaned_data.get('review_remarks', ''),
                    request=request,
                )
                messages.success(request, f"Disposal {disposal.disposal_number} rejected.")
                return redirect('disposals:disposal_detail', pk=pk)
            except ValidationError as e:
                messages.error(request, str(e.message if hasattr(e, 'message') else e))
        return render(request, 'disposals/disposal_reject_form.html', {
            'form': form,
            'disposal': disposal,
            'page_title': f"Reject: {disposal.disposal_number}",
        })


class DisposalCancelView(AdminRequiredMixin, View):
    """Cancels a pending or approved disposal request."""

    def dispatch(self, request, *args, **kwargs):
        check_admin_authority(request.user)
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, pk):
        disposal = get_object_or_404(AssetDisposal, pk=pk)
        if disposal.status not in [AssetDisposal.Status.PENDING, AssetDisposal.Status.APPROVED]:
            messages.warning(request, f"Disposal {disposal.disposal_number} cannot be cancelled.")
            return redirect('disposals:disposal_detail', pk=pk)
        form = DisposalCancelForm()
        return render(request, 'disposals/disposal_cancel_form.html', {
            'form': form,
            'disposal': disposal,
            'page_title': f"Cancel: {disposal.disposal_number}",
        })

    def post(self, request, pk):
        disposal = get_object_or_404(AssetDisposal, pk=pk)
        form = DisposalCancelForm(request.POST)
        if form.is_valid():
            try:
                services.cancel_disposal(
                    disposal=disposal,
                    cancelled_by=request.user,
                    cancellation_reason=form.cleaned_data.get('cancellation_reason', ''),
                    request=request,
                )
                messages.success(request, f"Disposal {disposal.disposal_number} cancelled.")
                return redirect('disposals:disposal_detail', pk=pk)
            except ValidationError as e:
                messages.error(request, str(e.message if hasattr(e, 'message') else e))
        return render(request, 'disposals/disposal_cancel_form.html', {
            'form': form,
            'disposal': disposal,
            'page_title': f"Cancel: {disposal.disposal_number}",
        })


class DisposalCompleteView(AdminRequiredMixin, View):
    """Records the physical disposal execution and transitions asset to DISPOSED."""

    def dispatch(self, request, *args, **kwargs):
        check_admin_authority(request.user)
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, pk):
        disposal = get_object_or_404(AssetDisposal, pk=pk)
        if disposal.status != AssetDisposal.Status.APPROVED:
            messages.warning(request, f"Disposal {disposal.disposal_number} must be approved before completion.")
            return redirect('disposals:disposal_detail', pk=pk)
        form = DisposalCompleteForm()
        return render(request, 'disposals/disposal_complete_form.html', {
            'form': form,
            'disposal': disposal,
            'page_title': f"Complete: {disposal.disposal_number}",
        })

    def post(self, request, pk):
        disposal = get_object_or_404(AssetDisposal, pk=pk)
        form = DisposalCompleteForm(request.POST)
        if form.is_valid():
            try:
                services.complete_disposal(
                    disposal=disposal,
                    processed_by=request.user,
                    disposal_method=form.cleaned_data['disposal_method'],
                    disposal_date=form.cleaned_data.get('disposal_date'),
                    recipient_or_destination=form.cleaned_data.get('recipient_or_destination', ''),
                    reference_number=form.cleaned_data.get('reference_number', ''),
                    proceeds_amount=form.cleaned_data.get('proceeds_amount'),
                    remarks=form.cleaned_data.get('remarks', ''),
                    request=request,
                )
                messages.success(request, f"Disposal {disposal.disposal_number} completed. Asset is now DISPOSED.")
                return redirect('disposals:disposal_detail', pk=pk)
            except ValidationError as e:
                messages.error(request, str(e.message if hasattr(e, 'message') else e))
        return render(request, 'disposals/disposal_complete_form.html', {
            'form': form,
            'disposal': disposal,
            'page_title': f"Complete: {disposal.disposal_number}",
        })


# ==============================================================================
# PRINTABLE DISPOSAL RECORD
# ==============================================================================

class DisposalPrintView(LoginRequiredMixin, View):
    """Generates a printable disposal record summary."""

    def get(self, request, pk):
        disposal = get_object_or_404(
            AssetDisposal.objects.select_related(
                'asset', 'asset__category', 'asset__brand', 'asset__department',
                'asset__current_location', 'requested_by', 'reviewed_by',
                'processed_by', 'maintenance_reference'
            ),
            pk=pk
        )
        user = request.user
        if getattr(user, 'role', '') == 'FACULTY':
            raise PermissionDenied("Faculty members cannot access disposal print records.")
        if getattr(user, 'role', '') == 'DEPT_CHAIR':
            chair_dept = getattr(getattr(user, 'employee_profile', None), 'department', None)
            if not chair_dept or disposal.asset.department != chair_dept:
                raise PermissionDenied("You can only access disposal records for your department's assets.")

        return render(request, 'disposals/disposal_print.html', {
            'disposal': disposal,
            'page_title': f"Disposal Record: {disposal.disposal_number}",
        })
