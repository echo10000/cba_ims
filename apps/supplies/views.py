from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse_lazy, reverse
from django.views.generic import ListView, DetailView, CreateView, UpdateView, FormView, View
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.contrib import messages
from django.core.exceptions import ValidationError, PermissionDenied
from django.db import models
from django.db.models import Q
from django.utils import timezone

from .models import Supply, SupplyCategory, SupplyTransaction
from .forms import SupplyForm, SupplyCategoryForm, StockInForm, StockOutForm, StockAdjustmentForm
from . import services
from apps.inventory.models import Brand
from apps.organizations.models import Department, Location, Employee
from apps.audit.utils import log_action


class AdminRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """Enforces exclusive write access for System Administrators / Property Custodians."""
    def test_func(self):
        return self.request.user.is_authenticated and getattr(self.request.user, 'is_admin', False)


class SupplyViewAccessMixin(LoginRequiredMixin, UserPassesTestMixin):
    """
    Grants read access to Admin, Dean, and Department Chair.
    Restricts Faculty and redirects them to My Accountability.
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
            messages.warning(self.request, "Faculty accounts cannot browse administrative supply management records.")
            return redirect('assignments:my_accountability')
        return super().handle_no_permission()


# ==============================================================================
# SUPPLY DEFINITION CRUD VIEWS
# ==============================================================================

class SupplyListView(SupplyViewAccessMixin, ListView):
    """
    Catalogs consumable supplies with real-time stock balances and status badges.
    """
    template_name = 'supplies/supply_list.html'
    context_object_name = 'supplies'
    paginate_by = 20

    def get_queryset(self):
        qs = services.get_annotated_supplies_queryset()

        # Multi-field search
        q = self.request.GET.get('q', '').strip()
        if q:
            qs = qs.filter(
                Q(supply_code__icontains=q) |
                Q(item_name__icontains=q) |
                Q(brand__name__icontains=q) |
                Q(category__name__icontains=q)
            )

        # Filters
        category_id = self.request.GET.get('category')
        brand_id = self.request.GET.get('brand')
        status = self.request.GET.get('status')
        stock_status = self.request.GET.get('stock_status')

        if category_id:
            qs = qs.filter(category_id=category_id)
        if brand_id:
            qs = qs.filter(brand_id=brand_id)
        if status == 'active':
            qs = qs.filter(is_active=True)
        elif status == 'inactive':
            qs = qs.filter(is_active=False)

        # In-memory stock status filtering if specified (since it relies on calculated_stock vs reorder_level)
        if stock_status == 'OUT_OF_STOCK':
            qs = qs.filter(calculated_stock__lte=0)
        elif stock_status == 'LOW_STOCK':
            qs = qs.filter(calculated_stock__gt=0, calculated_stock__lte=models.F('reorder_level'))
        elif stock_status == 'IN_STOCK':
            qs = qs.filter(calculated_stock__gt=models.F('reorder_level'))

        return qs.order_by('item_name')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['page_title'] = 'Consumable Supplies Inventory'
        context['categories'] = SupplyCategory.objects.filter(is_active=True)
        context['brands'] = Brand.objects.filter(is_active=True)
        
        # Low stock quick badge count
        context['low_stock_count'] = len(services.get_low_stock_supplies())

        query_params = self.request.GET.copy()
        if 'page' in query_params:
            query_params.pop('page')
        context['query_string'] = query_params.urlencode()
        return context


class SupplyDetailView(SupplyViewAccessMixin, DetailView):
    """
    Dedicated view for an individual supply item showing stock status,
    historical metrics, and recent transaction log.
    """
    model = Supply
    template_name = 'supplies/supply_detail.html'
    context_object_name = 'supply'
    slug_field = 'supply_code'
    slug_url_kwarg = 'supply_code'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        supply = self.object
        current_stock = services.get_current_stock(supply)
        context['page_title'] = f"Supply: {supply.item_name}"
        context['current_stock'] = current_stock
        context['stock_status'] = services.get_stock_status(current_stock, supply.reorder_level)
        
        # Scoped transaction history for recent display
        user = self.request.user
        tx_qs = supply.transactions.select_related(
            'department', 'location', 'employee', 'processed_by'
        )
        if getattr(user, 'role', '') == 'DEPT_CHAIR':
            chair_dept = getattr(getattr(user, 'employee_profile', None), 'department', None)
            if chair_dept:
                tx_qs = tx_qs.filter(department=chair_dept)
            else:
                tx_qs = tx_qs.none()

        context['recent_transactions'] = tx_qs[:10]
        return context


class SupplyCreateView(AdminRequiredMixin, CreateView):
    """Admin view to register a new consumable supply item."""
    model = Supply
    form_class = SupplyForm
    template_name = 'supplies/supply_form.html'

    def form_valid(self, form):
        supply = form.save(commit=False)
        supply.created_by = self.request.user
        supply.save()
        log_action(
            user=self.request.user,
            action='SUPPLY_CREATED',
            instance=supply,
            changes={
                'supply_code': supply.supply_code,
                'item_name': supply.item_name,
                'category': supply.category.name,
                'unit': supply.unit,
                'reorder_level': supply.reorder_level,
            },
            request=self.request
        )
        messages.success(self.request, f"Supply '{supply.item_name}' ({supply.supply_code}) registered successfully.")
        return redirect('supplies:supply_detail', supply_code=supply.supply_code)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['page_title'] = 'Register New Supply'
        context['is_create'] = True
        return context


class SupplyUpdateView(AdminRequiredMixin, UpdateView):
    """Admin view to update an existing supply definition."""
    model = Supply
    form_class = SupplyForm
    template_name = 'supplies/supply_form.html'
    slug_field = 'supply_code'
    slug_url_kwarg = 'supply_code'

    def form_valid(self, form):
        supply = form.save()
        log_action(
            user=self.request.user,
            action='SUPPLY_UPDATED',
            instance=supply,
            changes={field: {'new': str(form.cleaned_data.get(field))} for field in form.changed_data},
            request=self.request
        )
        messages.success(self.request, f"Supply '{supply.item_name}' updated successfully.")
        return redirect('supplies:supply_detail', supply_code=supply.supply_code)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['page_title'] = f"Edit Supply: {self.object.item_name}"
        context['is_create'] = False
        return context


class SupplyToggleActiveView(AdminRequiredMixin, View):
    """Admin endpoint to activate/deactivate a supply item."""
    def post(self, request, supply_code):
        supply = get_object_or_404(Supply, supply_code=supply_code)
        services.toggle_supply_active(supply, request.user, request=request)
        state_str = "activated" if supply.is_active else "deactivated"
        messages.success(request, f"Supply '{supply.item_name}' has been {state_str}.")
        return redirect('supplies:supply_detail', supply_code=supply.supply_code)


class SupplyDeleteView(AdminRequiredMixin, View):
    """
    Guarded deletion view: Prevents hard-deletion if transaction history exists.
    """
    def post(self, request, supply_code):
        supply = get_object_or_404(Supply, supply_code=supply_code)
        if supply.transactions.exists():
            messages.error(
                request,
                f"Cannot delete supply '{supply.item_name}' ({supply.supply_code}) because stock transaction history exists. "
                "You may deactivate the supply instead to preserve audit records."
            )
            return redirect('supplies:supply_detail', supply_code=supply.supply_code)

        item_name = supply.item_name
        code = supply.supply_code
        log_action(
            user=request.user,
            action='SUPPLY_DELETED',
            instance=supply,
            changes={'item_name': item_name, 'supply_code': code},
            request=request
        )
        supply.delete()
        messages.success(request, f"Supply '{item_name}' has been permanently deleted.")
        return redirect('supplies:supply_list')


# ==============================================================================
# STOCK OPERATIONS (ADMIN ONLY)
# ==============================================================================

class StockInView(AdminRequiredMixin, FormView):
    """Records incoming supply stock."""
    template_name = 'supplies/stock_in_form.html'
    form_class = StockInForm

    def get_preselected_supply(self):
        supply_code = self.kwargs.get('supply_code') or self.request.GET.get('supply')
        if supply_code:
            return get_object_or_404(Supply, supply_code=supply_code)
        return None

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['preselected_supply'] = self.get_preselected_supply()
        return kwargs

    def form_valid(self, form):
        supply = form.cleaned_data['supply']
        quantity = form.cleaned_data['quantity']
        transaction_date = form.cleaned_data['transaction_date']
        reference_number = form.cleaned_data.get('reference_number', '')
        remarks = form.cleaned_data.get('remarks', '')

        try:
            tx = services.stock_in(
                supply=supply,
                quantity=quantity,
                processed_by=self.request.user,
                transaction_date=transaction_date,
                reference_number=reference_number,
                remarks=remarks,
                request=self.request
            )
            messages.success(
                self.request,
                f"Successfully recorded Stock In (+{quantity} {supply.get_unit_display()}) for '{supply.item_name}'. "
                f"New Balance: {services.get_current_stock(supply)} {supply.get_unit_display()}."
            )
            return redirect('supplies:supply_detail', supply_code=supply.supply_code)
        except ValidationError as e:
            form.add_error(None, e.message)
            return self.form_invalid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        supply = self.get_preselected_supply()
        context['page_title'] = 'Record Stock In'
        context['preselected_supply'] = supply
        if supply:
            context['current_stock'] = services.get_current_stock(supply)
        return context


class StockOutView(AdminRequiredMixin, FormView):
    """Issues supply stock to a department or employee."""
    template_name = 'supplies/stock_out_form.html'
    form_class = StockOutForm

    def get_preselected_supply(self):
        supply_code = self.kwargs.get('supply_code') or self.request.GET.get('supply')
        if supply_code:
            return get_object_or_404(Supply, supply_code=supply_code)
        return None

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['preselected_supply'] = self.get_preselected_supply()
        return kwargs

    def form_valid(self, form):
        supply = form.cleaned_data['supply']
        quantity = form.cleaned_data['quantity']
        department = form.cleaned_data.get('department')
        location = form.cleaned_data.get('location')
        employee = form.cleaned_data.get('employee')
        purpose = form.cleaned_data.get('purpose', '')
        reference_number = form.cleaned_data.get('reference_number', '')
        transaction_date = form.cleaned_data['transaction_date']
        remarks = form.cleaned_data.get('remarks', '')

        try:
            tx = services.stock_out(
                supply=supply,
                quantity=quantity,
                processed_by=self.request.user,
                department=department,
                location=location,
                employee=employee,
                purpose=purpose,
                transaction_date=transaction_date,
                reference_number=reference_number,
                remarks=remarks,
                request=self.request
            )
            recipient_str = f" to {employee.full_name}" if employee else (f" to {department.name}" if department else "")
            messages.success(
                self.request,
                f"Successfully issued -{quantity} {supply.get_unit_display()} of '{supply.item_name}'{recipient_str}. "
                f"Remaining Stock: {services.get_current_stock(supply)} {supply.get_unit_display()}."
            )
            return redirect('supplies:supply_detail', supply_code=supply.supply_code)
        except ValidationError as e:
            form.add_error(None, e.message)
            return self.form_invalid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        supply = self.get_preselected_supply()
        context['page_title'] = 'Issue Stock (Stock Out)'
        context['preselected_supply'] = supply
        if supply:
            context['current_stock'] = services.get_current_stock(supply)
        return context


class StockAdjustmentView(AdminRequiredMixin, FormView):
    """Executes inventory count adjustments (surplus or shrinkage/loss)."""
    template_name = 'supplies/stock_adjustment_form.html'
    form_class = StockAdjustmentForm

    def get_preselected_supply(self):
        supply_code = self.kwargs.get('supply_code') or self.request.GET.get('supply')
        if supply_code:
            return get_object_or_404(Supply, supply_code=supply_code)
        return None

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['preselected_supply'] = self.get_preselected_supply()
        return kwargs

    def form_valid(self, form):
        supply = form.cleaned_data['supply']
        adjustment_type = form.cleaned_data['adjustment_type']
        quantity = form.cleaned_data['quantity']
        purpose = form.cleaned_data['purpose']
        reference_number = form.cleaned_data.get('reference_number', '')
        transaction_date = form.cleaned_data['transaction_date']
        remarks = form.cleaned_data.get('remarks', '')

        try:
            tx = services.adjust_stock(
                supply=supply,
                adjustment_type=adjustment_type,
                quantity=quantity,
                processed_by=self.request.user,
                reason=purpose,
                remarks=remarks,
                transaction_date=transaction_date,
                reference_number=reference_number,
                request=self.request
            )
            sign = "+" if adjustment_type == SupplyTransaction.TransactionType.ADJUSTMENT_IN else "-"
            messages.success(
                self.request,
                f"Recorded inventory adjustment ({sign}{quantity} {supply.get_unit_display()}) for '{supply.item_name}'. "
                f"New Balance: {services.get_current_stock(supply)} {supply.get_unit_display()}."
            )
            return redirect('supplies:supply_detail', supply_code=supply.supply_code)
        except ValidationError as e:
            form.add_error(None, e.message)
            return self.form_invalid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        supply = self.get_preselected_supply()
        context['page_title'] = 'Adjust Inventory Stock'
        context['preselected_supply'] = supply
        if supply:
            context['current_stock'] = services.get_current_stock(supply)
        return context


# ==============================================================================
# REPORTING & MONITORING VIEWS
# ==============================================================================

class SupplyTransactionListView(SupplyViewAccessMixin, ListView):
    """
    Permanent, read-only transaction audit archive for all supply movements.
    Scoped to department for Department Chairs.
    """
    model = SupplyTransaction
    template_name = 'supplies/transaction_list.html'
    context_object_name = 'transactions'
    paginate_by = 25

    def get_queryset(self):
        user = self.request.user
        qs = SupplyTransaction.objects.select_related(
            'supply', 'supply__category', 'supply__brand',
            'department', 'location', 'employee', 'processed_by'
        )

        # Scoping: Department Chairs only see transactions issued to their department
        if getattr(user, 'is_admin', False) or getattr(user, 'role', '') == 'DEAN':
            pass
        elif getattr(user, 'role', '') == 'DEPT_CHAIR':
            chair_dept = getattr(getattr(user, 'employee_profile', None), 'department', None)
            if chair_dept:
                qs = qs.filter(department=chair_dept)
            else:
                return qs.none()
        else:
            return qs.none()

        # Multi-field search
        q = self.request.GET.get('q', '').strip()
        if q:
            qs = qs.filter(
                Q(supply__supply_code__icontains=q) |
                Q(supply__item_name__icontains=q) |
                Q(reference_number__icontains=q) |
                Q(employee__first_name__icontains=q) |
                Q(employee__last_name__icontains=q) |
                Q(department__name__icontains=q)
            )

        # Filters
        tx_type = self.request.GET.get('transaction_type')
        dept_id = self.request.GET.get('department')
        supply_id = self.request.GET.get('supply')
        date_from = self.request.GET.get('date_from')
        date_to = self.request.GET.get('date_to')

        if tx_type:
            qs = qs.filter(transaction_type=tx_type)
        if dept_id:
            qs = qs.filter(department_id=dept_id)
        if supply_id:
            qs = qs.filter(supply_id=supply_id)
        if date_from:
            qs = qs.filter(transaction_date__gte=date_from)
        if date_to:
            qs = qs.filter(transaction_date__lte=date_to)

        return qs.order_by('-transaction_date', '-created_at')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['page_title'] = 'Supply Stock Transaction History'
        context['transaction_types'] = SupplyTransaction.TransactionType.choices
        context['departments'] = Department.objects.filter(is_active=True)
        context['supplies_list'] = Supply.objects.filter(is_active=True).order_by('item_name')

        query_params = self.request.GET.copy()
        if 'page' in query_params:
            query_params.pop('page')
        context['query_string'] = query_params.urlencode()
        return context


class LowStockListView(SupplyViewAccessMixin, ListView):
    """
    Dedicated view surfacing supplies at or below their reorder threshold,
    sorted most urgent (zero stock) first.
    """
    template_name = 'supplies/low_stock_list.html'
    context_object_name = 'supplies'
    paginate_by = 25

    def get_queryset(self):
        # Annotate and filter by calculated_stock <= reorder_level
        qs = services.get_annotated_supplies_queryset().filter(
            is_active=True,
            calculated_stock__lte=models.F('reorder_level')
        ).order_by('calculated_stock', 'item_name')
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['page_title'] = 'Low Stock & Depleted Supplies'
        context['out_of_stock_count'] = self.get_queryset().filter(calculated_stock__lte=0).count()
        context['low_stock_count'] = self.get_queryset().filter(calculated_stock__gt=0).count()
        return context
