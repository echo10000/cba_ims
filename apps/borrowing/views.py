from django.views.generic import ListView, DetailView, CreateView, FormView, View
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Q
from django.utils import timezone

from apps.inventory.models import Asset
from apps.organizations.models import Department, Employee
from .models import AssetBorrowing
from .forms import (
    BorrowingRequestForm,
    BorrowingRejectionForm,
    BorrowingReleaseForm,
    BorrowingReturnForm
)
from . import services


class AdminRequiredMixin(LoginRequiredMixin):
    """Enforces Admin / Property Custodian authorization."""
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not (getattr(request.user, 'is_admin', False) or getattr(request.user, 'role', '') == 'ADMIN'):
            raise PermissionDenied("You do not have administrative authority to manage equipment borrowings.")
        return super().dispatch(request, *args, **kwargs)


class NonFacultyRequiredMixin(LoginRequiredMixin):
    """Restricts view to Admin, Dean, and Department Chair. Faculty redirected to My Borrowings."""
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if getattr(request.user, 'role', '') == 'FACULTY':
            messages.info(request, "Redirected to your personal equipment borrowings.")
            return redirect('borrowing:my_borrowings')
        return super().dispatch(request, *args, **kwargs)


def check_borrowing_view_permission(user, borrowing):
    """
    Validates view access for a borrowing record.
    - Admin & Dean: view all.
    - Dept Chair: view where borrower_department == chair_dept or asset.department == chair_dept.
    - Faculty: view only own borrowings.
    """
    if getattr(user, 'is_admin', False) or getattr(user, 'role', '') in ['ADMIN', 'DEAN']:
        return True

    if getattr(user, 'role', '') == 'DEPT_CHAIR':
        chair_dept = getattr(getattr(user, 'employee_profile', None), 'department', None)
        if chair_dept and (
            borrowing.borrower_department_id == chair_dept.pk or
            borrowing.asset.department_id == chair_dept.pk
        ):
            return True
        raise PermissionDenied("You do not have permission to view borrowing records outside your department.")

    if getattr(user, 'role', '') == 'FACULTY':
        if borrowing.borrower.user == user:
            return True
        raise PermissionDenied("You only have permission to view your own equipment borrowings.")

    raise PermissionDenied("Access denied.")


# ==============================================================================
# BORROWING LIST & QUEUE VIEWS (ADMIN, DEAN, CHAIR)
# ==============================================================================

class BorrowingRequestListView(NonFacultyRequiredMixin, ListView):
    """
    Administrative queue for incoming and active borrowing requests.
    Default view shows PENDING and APPROVED reservations.
    """
    model = AssetBorrowing
    template_name = 'borrowing/borrowing_list.html'
    context_object_name = 'borrowings'
    paginate_by = 20

    def get_queryset(self):
        user = self.request.user
        services.refresh_overdue_status()

        qs = AssetBorrowing.objects.select_related(
            'asset', 'asset__category', 'asset__department', 'asset__current_location',
            'borrower', 'borrower__department', 'reviewed_by', 'released_by', 'returned_to'
        )

        # Scoping for Department Chairs
        if getattr(user, 'role', '') == 'DEPT_CHAIR':
            chair_dept = getattr(getattr(user, 'employee_profile', None), 'department', None)
            if chair_dept:
                qs = qs.filter(Q(borrower_department=chair_dept) | Q(asset__department=chair_dept))
            else:
                return AssetBorrowing.objects.none()

        # Filtering
        q = self.request.GET.get('q', '').strip()
        status = self.request.GET.get('status', '').strip()
        dept_id = self.request.GET.get('department', '').strip()
        cat_id = self.request.GET.get('category', '').strip()

        if q:
            qs = qs.filter(
                Q(asset__asset_code__icontains=q) |
                Q(asset__item_name__icontains=q) |
                Q(asset__property_number__icontains=q) |
                Q(borrower__first_name__icontains=q) |
                Q(borrower__last_name__icontains=q) |
                Q(purpose__icontains=q)
            )

        if status:
            qs = qs.filter(status=status)
        else:
            # Default tab: show pending and approved queue
            tab = self.request.GET.get('tab', 'requests')
            if tab == 'requests':
                qs = qs.filter(status__in=[AssetBorrowing.Status.PENDING, AssetBorrowing.Status.APPROVED])
            elif tab == 'active':
                qs = qs.filter(status__in=[AssetBorrowing.Status.RELEASED, AssetBorrowing.Status.OVERDUE])

        if dept_id and getattr(user, 'role', '') != 'DEPT_CHAIR':
            qs = qs.filter(borrower_department_id=dept_id)

        if cat_id:
            qs = qs.filter(asset__category_id=cat_id)

        return qs.order_by('-requested_at')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        context['page_title'] = 'Equipment Borrowing Requests'
        context['current_tab'] = self.request.GET.get('tab', 'requests')

        # Base count query for stats
        base_qs = AssetBorrowing.objects.all()
        if getattr(user, 'role', '') == 'DEPT_CHAIR':
            chair_dept = getattr(getattr(user, 'employee_profile', None), 'department', None)
            base_qs = base_qs.filter(Q(borrower_department=chair_dept) | Q(asset__department=chair_dept)) if chair_dept else base_qs.none()

        context['pending_count'] = base_qs.filter(status=AssetBorrowing.Status.PENDING).count()
        context['approved_count'] = base_qs.filter(status=AssetBorrowing.Status.APPROVED).count()
        context['released_count'] = base_qs.filter(status__in=[AssetBorrowing.Status.RELEASED, AssetBorrowing.Status.OVERDUE]).count()
        context['overdue_count'] = base_qs.filter(
            status__in=[AssetBorrowing.Status.RELEASED, AssetBorrowing.Status.OVERDUE],
            requested_return__lt=timezone.now(),
            returned_at__isnull=True
        ).count()

        if getattr(user, 'role', '') == 'DEPT_CHAIR':
            chair_dept = getattr(getattr(user, 'employee_profile', None), 'department', None)
            context['departments'] = Department.objects.filter(pk=chair_dept.pk) if chair_dept else Department.objects.none()
        else:
            context['departments'] = Department.objects.filter(is_active=True)

        context['statuses'] = AssetBorrowing.Status.choices

        query_params = self.request.GET.copy()
        if 'page' in query_params:
            query_params.pop('page')
        context['query_string'] = query_params.urlencode()
        return context


class ActiveBorrowingListView(NonFacultyRequiredMixin, ListView):
    """
    Shows currently released equipment out on loan (RELEASED and OVERDUE).
    """
    model = AssetBorrowing
    template_name = 'borrowing/borrowing_active_list.html'
    context_object_name = 'borrowings'
    paginate_by = 20

    def get_queryset(self):
        user = self.request.user
        services.refresh_overdue_status()

        qs = AssetBorrowing.objects.filter(
            status__in=[AssetBorrowing.Status.RELEASED, AssetBorrowing.Status.OVERDUE]
        ).select_related(
            'asset', 'asset__category', 'asset__department', 'asset__current_location',
            'borrower', 'borrower__department', 'released_by'
        )

        if getattr(user, 'role', '') == 'DEPT_CHAIR':
            chair_dept = getattr(getattr(user, 'employee_profile', None), 'department', None)
            if chair_dept:
                qs = qs.filter(Q(borrower_department=chair_dept) | Q(asset__department=chair_dept))
            else:
                return AssetBorrowing.objects.none()

        q = self.request.GET.get('q', '').strip()
        dept_id = self.request.GET.get('department', '').strip()

        if q:
            qs = qs.filter(
                Q(asset__asset_code__icontains=q) |
                Q(asset__item_name__icontains=q) |
                Q(borrower__first_name__icontains=q) |
                Q(borrower__last_name__icontains=q) |
                Q(purpose__icontains=q)
            )

        if dept_id and getattr(user, 'role', '') != 'DEPT_CHAIR':
            qs = qs.filter(borrower_department_id=dept_id)

        return qs.order_by('requested_return')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['page_title'] = 'Active Equipment Loans'
        context['departments'] = Department.objects.filter(is_active=True)
        query_params = self.request.GET.copy()
        if 'page' in query_params:
            query_params.pop('page')
        context['query_string'] = query_params.urlencode()
        return context


class BorrowingHistoryListView(NonFacultyRequiredMixin, ListView):
    """
    Archive of completed, rejected, and cancelled borrowings.
    """
    model = AssetBorrowing
    template_name = 'borrowing/borrowing_history_list.html'
    context_object_name = 'borrowings'
    paginate_by = 25

    def get_queryset(self):
        user = self.request.user
        qs = AssetBorrowing.objects.filter(
            status__in=[
                AssetBorrowing.Status.RETURNED,
                AssetBorrowing.Status.REJECTED,
                AssetBorrowing.Status.CANCELLED
            ]
        ).select_related(
            'asset', 'asset__category', 'asset__department',
            'borrower', 'borrower__department', 'reviewed_by', 'released_by', 'returned_to'
        )

        if getattr(user, 'role', '') == 'DEPT_CHAIR':
            chair_dept = getattr(getattr(user, 'employee_profile', None), 'department', None)
            if chair_dept:
                qs = qs.filter(Q(borrower_department=chair_dept) | Q(asset__department=chair_dept))
            else:
                return AssetBorrowing.objects.none()

        q = self.request.GET.get('q', '').strip()
        status = self.request.GET.get('status', '').strip()
        if q:
            qs = qs.filter(
                Q(asset__asset_code__icontains=q) |
                Q(asset__item_name__icontains=q) |
                Q(borrower__first_name__icontains=q) |
                Q(borrower__last_name__icontains=q)
            )
        if status:
            qs = qs.filter(status=status)

        return qs.order_by('-returned_at', '-updated_at', '-requested_at')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['page_title'] = 'Borrowing & Turnover History'
        query_params = self.request.GET.copy()
        if 'page' in query_params:
            query_params.pop('page')
        context['query_string'] = query_params.urlencode()
        return context


# ==============================================================================
# FACULTY MY BORROWINGS VIEW
# ==============================================================================

class MyBorrowingsView(LoginRequiredMixin, ListView):
    """
    Faculty-facing portal to track personal equipment requests, approved reservations,
    active loans, and borrowing history.
    """
    model = AssetBorrowing
    template_name = 'borrowing/my_borrowings.html'
    context_object_name = 'borrowings'

    def get_queryset(self):
        employee = getattr(self.request.user, 'employee_profile', None)
        if not employee:
            return AssetBorrowing.objects.none()

        services.refresh_overdue_status()

        return AssetBorrowing.objects.filter(
            borrower=employee
        ).select_related(
            'asset', 'asset__category', 'asset__current_location', 'asset__department'
        ).order_by('-requested_at')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        employee = getattr(self.request.user, 'employee_profile', None)
        context['employee'] = employee
        context['page_title'] = 'My Equipment Borrowings'

        all_borrowings = list(self.get_queryset())
        context['pending_requests'] = [b for b in all_borrowings if b.status == AssetBorrowing.Status.PENDING]
        context['approved_reservations'] = [b for b in all_borrowings if b.status == AssetBorrowing.Status.APPROVED]
        context['active_borrowings'] = [b for b in all_borrowings if b.status in [AssetBorrowing.Status.RELEASED, AssetBorrowing.Status.OVERDUE]]
        context['history_borrowings'] = [b for b in all_borrowings if b.status in [AssetBorrowing.Status.RETURNED, AssetBorrowing.Status.REJECTED, AssetBorrowing.Status.CANCELLED]]

        return context


# ==============================================================================
# REQUEST CREATION WORKFLOW
# ==============================================================================

class BorrowingRequestCreateView(LoginRequiredMixin, FormView):
    """
    Submits a temporary borrowing request for an available durable asset.
    """
    template_name = 'borrowing/borrowing_form.html'
    form_class = BorrowingRequestForm

    def dispatch(self, request, *args, **kwargs):
        self.initial_asset = None
        asset_code = kwargs.get('asset_code')
        if asset_code:
            self.initial_asset = get_object_or_404(
                Asset.objects.select_related('department', 'current_location', 'category'),
                asset_code=asset_code
            )
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        kwargs['initial_asset'] = self.initial_asset
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['page_title'] = 'Request Equipment Borrowing'
        context['initial_asset'] = self.initial_asset
        return context

    def form_valid(self, form):
        asset = form.cleaned_data['asset']
        borrower = form.cleaned_data['borrower']
        requested_start = form.cleaned_data['requested_start']
        requested_return = form.cleaned_data['requested_return']
        purpose = form.cleaned_data['purpose']
        remarks = form.cleaned_data.get('remarks', '')

        try:
            borrowing = services.request_borrowing(
                asset=asset,
                borrower=borrower,
                purpose=purpose,
                requested_start=requested_start,
                requested_return=requested_return,
                remarks=remarks,
                created_by=self.request.user,
                request=self.request
            )
        except ValidationError as e:
            form.add_error(None, e.message if hasattr(e, 'message') else str(e))
            return self.form_invalid(form)

        messages.success(
            self.request,
            f"Borrowing request for {asset.asset_code} ({asset.item_name}) submitted successfully. "
            "Awaiting property custodian review."
        )

        if getattr(self.request.user, 'role', '') == 'FACULTY':
            return redirect('borrowing:my_borrowings')
        return redirect('borrowing:borrowing_detail', pk=borrowing.pk)


# ==============================================================================
# BORROWING DETAIL & LIFECYCLE ACTION VIEWS
# ==============================================================================

class BorrowingDetailView(LoginRequiredMixin, DetailView):
    """
    Displays complete borrowing record, custody information, and authorized actions.
    """
    model = AssetBorrowing
    template_name = 'borrowing/borrowing_detail.html'
    context_object_name = 'borrowing'

    def get_object(self, queryset=None):
        borrowing = super().get_object(queryset)
        check_borrowing_view_permission(self.request.user, borrowing)
        services.refresh_overdue_status(borrowing)
        return borrowing

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        b = self.object
        user = self.request.user
        is_admin = getattr(user, 'is_admin', False) or getattr(user, 'role', '') == 'ADMIN'

        context['page_title'] = f"Borrowing #{b.pk}: {b.asset.asset_code}"
        context['is_admin'] = is_admin
        context['can_approve'] = is_admin and b.status == AssetBorrowing.Status.PENDING
        context['can_reject'] = is_admin and b.status == AssetBorrowing.Status.PENDING
        context['can_release'] = is_admin and b.status == AssetBorrowing.Status.APPROVED
        context['can_return'] = is_admin and b.status in [AssetBorrowing.Status.RELEASED, AssetBorrowing.Status.OVERDUE]
        context['can_cancel'] = (
            (is_admin and b.status in [AssetBorrowing.Status.PENDING, AssetBorrowing.Status.APPROVED]) or
            (b.borrower.user == user and b.status == AssetBorrowing.Status.PENDING)
        )
        return context


class BorrowingApproveView(AdminRequiredMixin, View):
    """Admin approves a pending borrowing request."""
    def post(self, request, pk):
        borrowing = get_object_or_404(AssetBorrowing, pk=pk)
        remarks = request.POST.get('remarks', '')
        try:
            services.approve_borrowing(borrowing, reviewed_by=request.user, remarks=remarks, request=request)
            messages.success(request, f"Request #{borrowing.pk} approved. Equipment is reserved for {borrowing.borrower.full_name}.")
        except ValidationError as e:
            messages.error(request, e.message if hasattr(e, 'message') else str(e))
        return redirect('borrowing:borrowing_detail', pk=borrowing.pk)


class BorrowingRejectView(AdminRequiredMixin, FormView):
    """Admin rejects a pending borrowing request."""
    template_name = 'borrowing/borrowing_reject_form.html'
    form_class = BorrowingRejectionForm

    def dispatch(self, request, *args, **kwargs):
        self.borrowing = get_object_or_404(AssetBorrowing, pk=kwargs['pk'])
        if self.borrowing.status != AssetBorrowing.Status.PENDING:
            messages.error(request, f"Borrowing #{self.borrowing.pk} is not in PENDING status.")
            return redirect('borrowing:borrowing_detail', pk=self.borrowing.pk)
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['borrowing'] = self.borrowing
        context['page_title'] = f"Reject Borrowing Request #{self.borrowing.pk}"
        return context

    def form_valid(self, form):
        reason = form.cleaned_data['rejection_reason']
        try:
            services.reject_borrowing(self.borrowing, reviewed_by=self.request.user, rejection_reason=reason, request=self.request)
            messages.warning(self.request, f"Borrowing request #{self.borrowing.pk} rejected.")
        except ValidationError as e:
            messages.error(self.request, e.message if hasattr(e, 'message') else str(e))
        return redirect('borrowing:borrowing_detail', pk=self.borrowing.pk)


class BorrowingCancelView(LoginRequiredMixin, View):
    """Cancels a pending request (by borrower or admin) or approved reservation (by admin)."""
    def post(self, request, pk):
        borrowing = get_object_or_404(AssetBorrowing, pk=pk)
        reason = request.POST.get('reason', '')
        try:
            services.cancel_borrowing(borrowing, cancelled_by=request.user, reason=reason, request=request)
            messages.info(request, f"Borrowing reservation #{borrowing.pk} was cancelled.")
        except ValidationError as e:
            messages.error(request, e.message if hasattr(e, 'message') else str(e))

        if getattr(request.user, 'role', '') == 'FACULTY':
            return redirect('borrowing:my_borrowings')
        return redirect('borrowing:borrowing_detail', pk=borrowing.pk)


class BorrowingReleaseView(AdminRequiredMixin, FormView):
    """Admin physically releases equipment to borrower and snapshots condition."""
    template_name = 'borrowing/borrowing_release_form.html'
    form_class = BorrowingReleaseForm

    def dispatch(self, request, *args, **kwargs):
        self.borrowing = get_object_or_404(AssetBorrowing, pk=kwargs['pk'])
        if self.borrowing.status != AssetBorrowing.Status.APPROVED:
            messages.error(request, f"Borrowing #{self.borrowing.pk} must be in APPROVED status before release.")
            return redirect('borrowing:borrowing_detail', pk=self.borrowing.pk)
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['initial_condition'] = self.borrowing.asset.condition
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['borrowing'] = self.borrowing
        context['page_title'] = f"Release Equipment: {self.borrowing.asset.asset_code}"
        return context

    def form_valid(self, form):
        cond = form.cleaned_data['condition_at_release']
        remarks = form.cleaned_data.get('remarks', '')
        try:
            services.release_asset(
                self.borrowing,
                released_by=self.request.user,
                condition_at_release=cond,
                remarks=remarks,
                request=self.request
            )
            messages.success(
                self.request,
                f"Equipment {self.borrowing.asset.asset_code} released to {self.borrowing.borrower.full_name}. "
                "Asset status is now BORROWED."
            )
        except ValidationError as e:
            messages.error(self.request, e.message if hasattr(e, 'message') else str(e))
        return redirect('borrowing:borrowing_detail', pk=self.borrowing.pk)


class BorrowingReturnView(AdminRequiredMixin, FormView):
    """Admin inspects and processes the return of borrowed equipment."""
    template_name = 'borrowing/borrowing_return_form.html'
    form_class = BorrowingReturnForm

    def dispatch(self, request, *args, **kwargs):
        self.borrowing = get_object_or_404(AssetBorrowing, pk=kwargs['pk'])
        services.refresh_overdue_status(self.borrowing)
        if self.borrowing.status not in [AssetBorrowing.Status.RELEASED, AssetBorrowing.Status.OVERDUE]:
            messages.error(request, f"Borrowing #{self.borrowing.pk} is not currently released or overdue.")
            return redirect('borrowing:borrowing_detail', pk=self.borrowing.pk)
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['initial_condition'] = self.borrowing.condition_at_release or self.borrowing.asset.condition
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['borrowing'] = self.borrowing
        context['page_title'] = f"Process Return: {self.borrowing.asset.asset_code}"
        return context

    def form_valid(self, form):
        cond = form.cleaned_data['condition_at_return']
        return_remarks = form.cleaned_data.get('return_remarks', '')

        try:
            services.return_borrowed_asset(
                self.borrowing,
                returned_to=self.request.user,
                condition_at_return=cond,
                return_remarks=return_remarks,
                request=self.request
            )
            if cond == Asset.Condition.UNSERVICEABLE:
                messages.warning(
                    self.request,
                    f"Equipment {self.borrowing.asset.asset_code} returned in UNSERVICEABLE condition. "
                    "Asset status updated to DAMAGED."
                )
            else:
                messages.success(
                    self.request,
                    f"Equipment {self.borrowing.asset.asset_code} successfully returned by "
                    f"{self.borrowing.borrower.full_name}. Asset is now AVAILABLE."
                )
        except ValidationError as e:
            messages.error(self.request, e.message if hasattr(e, 'message') else str(e))

        if self.request.GET.get('from') == 'qr':
            return redirect('qr_asset_lookup', asset_code=self.borrowing.asset.asset_code)
        return redirect('borrowing:borrowing_detail', pk=self.borrowing.pk)


class AssetReturnBorrowingView(AdminRequiredMixin, View):
    """
    Convenience endpoint for QR scanner and Asset Detail to immediately process return
    of an actively borrowed asset.
    """
    def get(self, request, asset_code):
        asset = get_object_or_404(Asset, asset_code=asset_code)
        active_borrowing = AssetBorrowing.objects.filter(
            asset=asset,
            status__in=[AssetBorrowing.Status.RELEASED, AssetBorrowing.Status.OVERDUE]
        ).first()

        if not active_borrowing:
            messages.warning(request, f"Asset '{asset.asset_code}' does not have an active released borrowing.")
            return redirect('inventory:asset_detail', asset_code=asset.asset_code)

        from_param = '?from=qr' if request.GET.get('from') == 'qr' else ''
        return redirect(f"{reverse('borrowing:borrowing_return', kwargs={'pk': active_borrowing.pk})}{from_param}")
