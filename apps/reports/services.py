from decimal import Decimal
from datetime import datetime, date
from django.db import models
from django.db.models import Q, Sum, Count, Avg, F, Value, Prefetch
from django.db.models.functions import Coalesce
from django.utils import timezone
from django.core.exceptions import ValidationError, PermissionDenied

from apps.accounts.models import User
from apps.organizations.models import Department, Location, Employee
from apps.inventory.models import Asset, AssetCategory, Brand, AssetVerification
from apps.assignments.models import AssetAssignment
from apps.transfers.models import AssetTransfer
from apps.borrowing.models import AssetBorrowing
from apps.borrowing import services as borrowing_services
from apps.maintenance.models import AssetMaintenance
from apps.supplies.models import Supply, SupplyTransaction, SupplyCategory
from apps.supplies import services as supply_services
from apps.disposals.models import AssetDisposal
from apps.audit.models import AuditLog


# ==============================================================================
# AUTHORIZATION & SCOPING HELPERS
# ==============================================================================

def get_user_department_scope(user):
    """
    Authoritative department scoping rule:
    - ADMIN or DEAN: returns None (college-wide visibility allowed)
    - DEPT_CHAIR: returns user's assigned Department. NEVER allows querying other departments.
    - FACULTY: raises PermissionDenied (faculty must use personal portals)
    """
    if not user.is_authenticated:
        raise PermissionDenied("Authentication required to access reports.")

    if getattr(user, 'is_admin', False) or getattr(user, 'role', '') in [User.Role.ADMIN, User.Role.DEAN]:
        return None

    if getattr(user, 'role', '') == User.Role.DEPT_CHAIR:
        chair_dept = getattr(getattr(user, 'employee_profile', None), 'department', None)
        if not chair_dept:
            raise PermissionDenied("Department Chair profile is not linked to any active department.")
        return chair_dept

    raise PermissionDenied("Faculty members do not have access to administrative reporting.")


def parse_date_range(date_from_str, date_to_str):
    """
    Parses and validates ISO date range strings (YYYY-MM-DD).
    Returns (date_from, date_to, error_message).
    """
    date_from = None
    date_to = None

    if date_from_str:
        try:
            date_from = datetime.strptime(date_from_str.strip(), '%Y-%m-%d').date()
        except ValueError:
            return None, None, "Invalid 'Date From' format. Use YYYY-MM-DD."

    if date_to_str:
        try:
            date_to = datetime.strptime(date_to_str.strip(), '%Y-%m-%d').date()
        except ValueError:
            return None, None, "Invalid 'Date To' format. Use YYYY-MM-DD."

    if date_from and date_to and date_from > date_to:
        return None, None, "'Date From' cannot be later than 'Date To'."

    return date_from, date_to, None


# ==============================================================================
# 1. ASSET INVENTORY REPORTS
# ==============================================================================

def get_asset_inventory_report(user, filters=None):
    """
    Primary asset inventory report with multi-field search, filtering,
    summary counts, and strict RBAC scoping.
    """
    filters = filters or {}
    chair_dept = get_user_department_scope(user)

    qs = Asset.objects.select_related(
        'category', 'brand', 'department', 'current_location', 'created_by'
    ).prefetch_related(
        Prefetch(
            'assignments',
            queryset=AssetAssignment.objects.filter(status=AssetAssignment.Status.ACTIVE).select_related('employee'),
            to_attr='active_assignments'
        )
    )

    # Scoping enforcement
    if chair_dept:
        qs = qs.filter(department=chair_dept)
    elif filters.get('department'):
        qs = qs.filter(department_id=filters['department'])

    # Scope: active vs disposed vs all
    scope = filters.get('scope', 'active')
    if scope == 'active':
        qs = qs.exclude(status=Asset.Status.DISPOSED)
    elif scope == 'disposed':
        qs = qs.filter(status=Asset.Status.DISPOSED)
    # scope == 'all' includes both

    # Additional filters
    if filters.get('location'):
        qs = qs.filter(current_location_id=filters['location'])
    if filters.get('category'):
        qs = qs.filter(category_id=filters['category'])
    if filters.get('brand'):
        qs = qs.filter(brand_id=filters['brand'])
    if filters.get('condition'):
        qs = qs.filter(condition=filters['condition'])
    if filters.get('status'):
        qs = qs.filter(status=filters['status'])

    # Acquisition Date Range
    date_from, date_to, _ = parse_date_range(filters.get('date_from'), filters.get('date_to'))
    if date_from:
        qs = qs.filter(acquisition_date__gte=date_from)
    if date_to:
        qs = qs.filter(acquisition_date__lte=date_to)

    # Search
    q = filters.get('q', '').strip()
    if q:
        qs = qs.filter(
            Q(asset_code__icontains=q) |
            Q(property_number__icontains=q) |
            Q(item_name__icontains=q) |
            Q(serial_number__icontains=q) |
            Q(brand__name__icontains=q) |
            Q(model__icontains=q)
        )

    # Summary metrics calculated from this filtered queryset
    summary = qs.aggregate(
        total=Count('id'),
        available=Count('id', filter=Q(status=Asset.Status.AVAILABLE)),
        assigned=Count('id', filter=Q(status=Asset.Status.ASSIGNED)),
        borrowed=Count('id', filter=Q(status=Asset.Status.BORROWED)),
        maintenance=Count('id', filter=Q(status=Asset.Status.MAINTENANCE)),
        damaged=Count('id', filter=Q(status=Asset.Status.DAMAGED)),
        disposed=Count('id', filter=Q(status=Asset.Status.DISPOSED)),
        total_cost=Coalesce(Sum('acquisition_cost'), Value(Decimal('0.00'))),
    )

    return qs.order_by('asset_code'), summary


def format_asset_inventory_rows(assets):
    """Formats asset records for CSV/XLSX export."""
    headers = [
        "Asset Code", "Property Number", "Item Name", "Category", "Brand",
        "Model", "Serial Number", "Department", "Location", "Condition",
        "Status", "Accountable Person", "Acquisition Date", "Acquisition Cost (PHP)"
    ]
    column_types = [
        "center", "center", "left", "left", "left",
        "left", "center", "left", "left", "center",
        "center", "left", "center", "currency"
    ]
    rows = []
    for a in assets:
        accountable = "—"
        if hasattr(a, 'active_assignments') and a.active_assignments:
            accountable = a.active_assignments[0].employee.full_name
        elif a.assignments.filter(status=AssetAssignment.Status.ACTIVE).exists():
            accountable = a.assignments.filter(status=AssetAssignment.Status.ACTIVE).first().employee.full_name

        rows.append([
            a.asset_code,
            a.property_number or "—",
            a.item_name,
            a.category.name if a.category else "—",
            a.brand.name if a.brand else "—",
            a.model or "—",
            a.serial_number or "—",
            a.department.name if a.department else "—",
            a.current_location.name if a.current_location else "—",
            a.get_condition_display(),
            a.get_status_display(),
            accountable,
            a.acquisition_date,
            a.acquisition_cost or Decimal('0.00'),
        ])
    return headers, rows, column_types


def get_asset_by_department_summary(user):
    """Aggregates inventory counts by department respecting user scope."""
    chair_dept = get_user_department_scope(user)
    dept_qs = Department.objects.filter(is_active=True)
    if chair_dept:
        dept_qs = dept_qs.filter(pk=chair_dept.pk)

    data = []
    for dept in dept_qs.order_by('name'):
        assets = dept.assets.all()
        counts = assets.aggregate(
            total=Count('id'),
            active=Count('id', filter=~Q(status=Asset.Status.DISPOSED)),
            available=Count('id', filter=Q(status=Asset.Status.AVAILABLE)),
            assigned=Count('id', filter=Q(status=Asset.Status.ASSIGNED)),
            borrowed=Count('id', filter=Q(status=Asset.Status.BORROWED)),
            maintenance=Count('id', filter=Q(status=Asset.Status.MAINTENANCE)),
            damaged=Count('id', filter=Q(status=Asset.Status.DAMAGED)),
            disposed=Count('id', filter=Q(status=Asset.Status.DISPOSED)),
            total_value=Coalesce(Sum('acquisition_cost', filter=~Q(status=Asset.Status.DISPOSED)), Value(Decimal('0.00'))),
        )
        data.append({
            'department': dept,
            'counts': counts,
        })
    return data


def get_asset_by_location_summary(user, department_id=None):
    """Aggregates inventory counts by physical room/location."""
    chair_dept = get_user_department_scope(user)
    loc_qs = Location.objects.select_related('department').filter(is_active=True)

    if chair_dept:
        loc_qs = loc_qs.filter(department=chair_dept)
    elif department_id:
        loc_qs = loc_qs.filter(department_id=department_id)

    data = []
    for loc in loc_qs.order_by('department__name', 'name'):
        assets = loc.assets.all()
        counts = assets.aggregate(
            total=Count('id'),
            active=Count('id', filter=~Q(status=Asset.Status.DISPOSED)),
            available=Count('id', filter=Q(status=Asset.Status.AVAILABLE)),
            assigned=Count('id', filter=Q(status=Asset.Status.ASSIGNED)),
            damaged=Count('id', filter=Q(status=Asset.Status.DAMAGED)),
            maintenance=Count('id', filter=Q(status=Asset.Status.MAINTENANCE)),
        )
        data.append({
            'location': loc,
            'counts': counts,
        })
    return data


# ==============================================================================
# 2. ACCOUNTABILITY REPORTS
# ==============================================================================

def get_accountability_report(user, filters=None, historical=False):
    """
    Generates employee accountability reports.
    - historical=False: Current active assignments only.
    - historical=True: Returned assignment turnover history.
    """
    filters = filters or {}
    chair_dept = get_user_department_scope(user)

    target_status = AssetAssignment.Status.RETURNED if historical else AssetAssignment.Status.ACTIVE

    qs = AssetAssignment.objects.filter(status=target_status).select_related(
        'asset', 'asset__category', 'asset__brand', 'asset__current_location',
        'employee', 'employee__department', 'assigned_by', 'returned_by'
    )

    if chair_dept:
        qs = qs.filter(Q(employee__department=chair_dept) | Q(asset__department=chair_dept))
    elif filters.get('department'):
        qs = qs.filter(employee__department_id=filters['department'])

    if filters.get('employee'):
        qs = qs.filter(employee_id=filters['employee'])

    if filters.get('condition'):
        if historical:
            qs = qs.filter(condition_at_return=filters['condition'])
        else:
            qs = qs.filter(condition_at_assignment=filters['condition'])

    date_from, date_to, _ = parse_date_range(filters.get('date_from'), filters.get('date_to'))
    if date_from:
        qs = qs.filter(assigned_date__gte=date_from)
    if date_to:
        qs = qs.filter(assigned_date__lte=date_to)

    q = filters.get('q', '').strip()
    if q:
        qs = qs.filter(
            Q(asset__asset_code__icontains=q) |
            Q(asset__property_number__icontains=q) |
            Q(asset__item_name__icontains=q) |
            Q(employee__first_name__icontains=q) |
            Q(employee__last_name__icontains=q) |
            Q(employee__employee_id__icontains=q) |
            Q(purpose__icontains=q)
        )

    val_aggr = qs.aggregate(v=Coalesce(Sum('asset__acquisition_cost'), Value(Decimal('0.00'))))
    summary = {
        'total_records': qs.count(),
        'total_assignments': qs.count(),
        'unique_employees': qs.values('employee').distinct().count(),
        'unique_assets': qs.values('asset').distinct().count(),
        'total_value': val_aggr['v'],
    }

    ordering = ['-returned_date', '-created_at'] if historical else ['employee__last_name', 'asset__asset_code']
    return qs.order_by(*ordering), summary


def format_accountability_rows(assignments, historical=False):
    """Formats accountability assignments for export."""
    if not historical:
        headers = [
            "Employee ID", "Employee Name", "Department", "Position", "Asset Code",
            "Property Number", "Item Name", "Serial Number", "Location",
            "Condition at Assignment", "Assigned Date", "Assigned By", "Purpose"
        ]
        column_types = [
            "center", "left", "left", "left", "center",
            "center", "left", "center", "left",
            "center", "center", "left", "left"
        ]
        rows = []
        for a in assignments:
            rows.append([
                a.employee.employee_id,
                a.employee.full_name,
                a.employee.department.name if a.employee.department else "—",
                a.employee.position or "Staff",
                a.asset.asset_code,
                a.asset.property_number or "—",
                a.asset.item_name,
                a.asset.serial_number or "—",
                a.asset.current_location.name if a.asset.current_location else "—",
                a.get_condition_at_assignment_display(),
                a.assigned_date,
                a.assigned_by.get_full_name() if a.assigned_by else "—",
                a.purpose or "—",
            ])
        return headers, rows, column_types
    else:
        headers = [
            "Employee ID", "Employee Name", "Department", "Asset Code",
            "Item Name", "Assigned Date", "Returned Date", "Condition Out",
            "Condition In", "Assigned By", "Returned By", "Return Remarks"
        ]
        column_types = [
            "center", "left", "left", "center",
            "left", "center", "center", "center",
            "center", "left", "left", "left"
        ]
        rows = []
        for a in assignments:
            rows.append([
                a.employee.employee_id,
                a.employee.full_name,
                a.employee.department.name if a.employee.department else "—",
                a.asset.asset_code,
                a.asset.item_name,
                a.assigned_date,
                a.returned_date,
                a.get_condition_at_assignment_display(),
                a.get_condition_at_return_display() if a.condition_at_return else "—",
                a.assigned_by.get_full_name() if a.assigned_by else "—",
                a.returned_by.get_full_name() if a.returned_by else "—",
                a.remarks or "—",
            ])
        return headers, rows, column_types


# ==============================================================================
# 3. ASSET TRANSFER & MOVEMENT REPORT
# ==============================================================================

def get_transfer_report(user, filters=None):
    """Asset relocation and transfer movement report."""
    filters = filters or {}
    chair_dept = get_user_department_scope(user)

    qs = AssetTransfer.objects.select_related(
        'asset', 'asset__category', 'from_department', 'from_location',
        'to_department', 'to_location', 'requested_by', 'processed_by'
    )

    if chair_dept:
        qs = qs.filter(Q(from_department=chair_dept) | Q(to_department=chair_dept))
    elif filters.get('department'):
        dept_id = filters['department']
        qs = qs.filter(Q(from_department_id=dept_id) | Q(to_department_id=dept_id))

    if filters.get('status'):
        qs = qs.filter(status=filters['status'])

    date_from, date_to, _ = parse_date_range(filters.get('date_from'), filters.get('date_to'))
    if date_from:
        qs = qs.filter(transfer_date__gte=date_from)
    if date_to:
        qs = qs.filter(transfer_date__lte=date_to)

    q = filters.get('q', '').strip()
    if q:
        qs = qs.filter(
            Q(asset__asset_code__icontains=q) |
            Q(asset__item_name__icontains=q) |
            Q(reason__icontains=q) |
            Q(from_department__name__icontains=q) |
            Q(to_department__name__icontains=q)
        )

    summary = {
        'total': qs.count(),
        'completed': qs.filter(status=AssetTransfer.Status.COMPLETED).count(),
        'pending': qs.filter(status=AssetTransfer.Status.PENDING).count(),
        'approved': qs.filter(status=AssetTransfer.Status.APPROVED).count(),
        'rejected': qs.filter(status=AssetTransfer.Status.REJECTED).count(),
    }

    return qs.order_by('-created_at'), summary


def format_transfer_rows(transfers):
    headers = [
        "Transfer ID", "Asset Code", "Item Name", "From Department", "From Location",
        "To Department", "To Location", "Transfer Date", "Status", "Reason",
        "Requested By", "Processed By", "Completed Date"
    ]
    column_types = [
        "center", "center", "left", "left", "left",
        "left", "left", "center", "center", "left",
        "left", "left", "center"
    ]
    rows = []
    for t in transfers:
        rows.append([
            f"TRF-{t.pk:05d}",
            t.asset.asset_code,
            t.asset.item_name,
            t.from_department.name if t.from_department else "—",
            t.from_location.name if t.from_location else "—",
            t.to_department.name if t.to_department else "—",
            t.to_location.name if t.to_location else "—",
            t.transfer_date,
            t.get_status_display(),
            t.reason or "—",
            t.requested_by.get_full_name() if t.requested_by else "—",
            t.processed_by.get_full_name() if t.processed_by else "—",
            t.completed_at.strftime('%Y-%m-%d') if t.completed_at else "—",
        ])
    return headers, rows, column_types


# ==============================================================================
# 4. BORROWING & TEMPORARY LOAN REPORTS
# ==============================================================================

def get_borrowing_report(user, filters=None, overdue_only=False):
    """
    Equipment loan report featuring dynamic overdue detection.
    """
    filters = filters or {}
    chair_dept = get_user_department_scope(user)

    # Sync real-time overdue statuses in DB
    borrowing_services.refresh_overdue_status()

    qs = AssetBorrowing.objects.select_related(
        'asset', 'asset__department', 'borrower', 'borrower__department',
        'reviewed_by', 'released_by', 'returned_to'
    )

    if chair_dept:
        qs = qs.filter(Q(borrower__department=chair_dept) | Q(asset__department=chair_dept))
    elif filters.get('department'):
        dept_id = filters['department']
        qs = qs.filter(Q(borrower__department_id=dept_id) | Q(asset__department_id=dept_id))

    if overdue_only:
        now = timezone.now()
        qs = qs.filter(
            Q(status=AssetBorrowing.Status.OVERDUE) |
            (Q(status=AssetBorrowing.Status.RELEASED) & Q(requested_return__lt=now))
        )
    elif filters.get('status'):
        if filters['status'] == 'ACTIVE_LOANS':
            qs = qs.filter(status__in=[AssetBorrowing.Status.RELEASED, AssetBorrowing.Status.OVERDUE])
        else:
            qs = qs.filter(status=filters['status'])

    if filters.get('borrower'):
        qs = qs.filter(borrower_id=filters['borrower'])

    date_from, date_to, _ = parse_date_range(filters.get('date_from'), filters.get('date_to'))
    if date_from:
        qs = qs.filter(requested_start__date__gte=date_from)
    if date_to:
        qs = qs.filter(requested_start__date__lte=date_to)

    q = filters.get('q', '').strip()
    if q:
        qs = qs.filter(
            Q(asset__asset_code__icontains=q) |
            Q(asset__item_name__icontains=q) |
            Q(borrower__first_name__icontains=q) |
            Q(borrower__last_name__icontains=q) |
            Q(purpose__icontains=q)
        )

    summary = {
        'total': qs.count(),
        'released': qs.filter(status=AssetBorrowing.Status.RELEASED).count(),
        'overdue': qs.filter(
            Q(status=AssetBorrowing.Status.OVERDUE) |
            (Q(status=AssetBorrowing.Status.RELEASED) & Q(requested_return__lt=timezone.now()))
        ).count(),
        'returned': qs.filter(status=AssetBorrowing.Status.RETURNED).count(),
        'pending': qs.filter(status=AssetBorrowing.Status.PENDING).count(),
    }

    return qs.order_by('-requested_at'), summary


def format_borrowing_rows(borrowings):
    headers = [
        "Loan ID", "Asset Code", "Item Name", "Borrower", "Borrower Dept",
        "Requested Start", "Expected Return", "Status", "Effective State",
        "Condition Out", "Condition In", "Released By", "Returned Date"
    ]
    column_types = [
        "center", "center", "left", "left", "left",
        "center", "center", "center", "center",
        "center", "center", "left", "center"
    ]
    rows = []
    for b in borrowings:
        effective_state = "Overdue" if b.is_overdue else b.get_status_display()
        rows.append([
            f"BRW-{b.pk:05d}",
            b.asset.asset_code,
            b.asset.item_name,
            b.borrower.full_name,
            b.borrower.department.name if b.borrower.department else "—",
            b.requested_start.strftime('%Y-%m-%d %H:%M'),
            b.requested_return.strftime('%Y-%m-%d %H:%M'),
            b.get_status_display(),
            effective_state,
            b.get_condition_at_release_display() if b.condition_at_release else "—",
            b.get_condition_at_return_display() if b.condition_at_return else "—",
            b.released_by.get_full_name() if b.released_by else "—",
            b.returned_at.strftime('%Y-%m-%d %H:%M') if b.returned_at else "—",
        ])
    return headers, rows, column_types


# ==============================================================================
# 5. MAINTENANCE & REPAIR REPORTS
# ==============================================================================

def get_maintenance_report(user, filters=None, replacement_only=False):
    """Equipment maintenance, damage incidents, and repair records."""
    filters = filters or {}
    chair_dept = get_user_department_scope(user)

    qs = AssetMaintenance.objects.select_related(
        'asset', 'asset__department', 'asset__category', 'reported_by',
        'assessed_by', 'returned_to_service_by'
    )

    if chair_dept:
        qs = qs.filter(asset__department=chair_dept)
    elif filters.get('department'):
        qs = qs.filter(asset__department_id=filters['department'])

    if replacement_only:
        qs = qs.filter(status=AssetMaintenance.Status.FOR_REPLACEMENT)
    elif filters.get('status'):
        qs = qs.filter(status=filters['status'])

    if filters.get('severity'):
        qs = qs.filter(severity=filters['severity'])

    if filters.get('category'):
        qs = qs.filter(asset__category_id=filters['category'])

    if filters.get('service_provider'):
        qs = qs.filter(service_provider__icontains=filters['service_provider'])

    date_from, date_to, _ = parse_date_range(filters.get('date_from'), filters.get('date_to'))
    if date_from:
        qs = qs.filter(reported_at__date__gte=date_from)
    if date_to:
        qs = qs.filter(reported_at__date__lte=date_to)

    q = filters.get('q', '').strip()
    if q:
        qs = qs.filter(
            Q(case_number__icontains=q) |
            Q(asset__asset_code__icontains=q) |
            Q(asset__item_name__icontains=q) |
            Q(issue_title__icontains=q) |
            Q(diagnosis__icontains=q) |
            Q(service_provider__icontains=q)
        )

    summary = qs.aggregate(
        total=Count('id'),
        completed=Count('id', filter=Q(status=AssetMaintenance.Status.COMPLETED)),
        in_repair=Count('id', filter=Q(status=AssetMaintenance.Status.IN_REPAIR)),
        for_replacement=Count('id', filter=Q(status=AssetMaintenance.Status.FOR_REPLACEMENT)),
        critical=Count('id', filter=Q(severity=AssetMaintenance.Severity.CRITICAL)),
        total_cost=Coalesce(Sum('repair_cost', filter=Q(status=AssetMaintenance.Status.COMPLETED)), Value(Decimal('0.00'))),
        avg_cost=Coalesce(Avg('repair_cost', filter=Q(status=AssetMaintenance.Status.COMPLETED)), Value(Decimal('0.00'))),
    )

    return qs.order_by('-reported_at'), summary


def format_maintenance_rows(cases):
    headers = [
        "Case Number", "Asset Code", "Item Name", "Department", "Issue Title",
        "Severity", "Status", "Reported Date", "Service Provider",
        "Repair Cost (PHP)", "Final Condition", "Completion Date"
    ]
    column_types = [
        "center", "center", "left", "left", "left",
        "center", "center", "center", "left",
        "currency", "center", "center"
    ]
    rows = []
    for c in cases:
        rows.append([
            c.case_number,
            c.asset.asset_code,
            c.asset.item_name,
            c.asset.department.name if c.asset.department else "—",
            c.issue_title,
            c.get_severity_display() if c.severity else "—",
            c.get_status_display(),
            c.reported_at.strftime('%Y-%m-%d'),
            c.service_provider or "—",
            c.repair_cost or Decimal('0.00'),
            c.get_final_condition_display() if c.final_condition else "—",
            c.repair_completed_at.strftime('%Y-%m-%d') if c.repair_completed_at else "—",
        ])
    return headers, rows, column_types


def get_maintenance_cost_summary(user, filters=None):
    """
    Aggregates operational repair expenditures across departments and vendors.
    Clearly designated as recorded operational maintenance expenses.
    """
    filters = filters or {}
    chair_dept = get_user_department_scope(user)

    qs = AssetMaintenance.objects.filter(
        status=AssetMaintenance.Status.COMPLETED
    ).select_related('asset', 'asset__department')

    if chair_dept:
        qs = qs.filter(asset__department=chair_dept)
    elif filters.get('department'):
        qs = qs.filter(asset__department_id=filters['department'])

    date_from, date_to, _ = parse_date_range(filters.get('date_from'), filters.get('date_to'))
    if date_from:
        qs = qs.filter(repair_completed_at__date__gte=date_from)
    if date_to:
        qs = qs.filter(repair_completed_at__date__lte=date_to)

    summary = qs.aggregate(
        completed_count=Count('id'),
        completed_repairs_count=Count('id'),
        total_cost=Coalesce(Sum('repair_cost'), Value(Decimal('0.00'))),
        avg_cost=Coalesce(Avg('repair_cost'), Value(Decimal('0.00'))),
        average_cost=Coalesce(Avg('repair_cost'), Value(Decimal('0.00'))),
    )

    # Departmental breakdown
    dept_breakdown = qs.values(
        'asset__department__name'
    ).annotate(
        repairs=Count('id'),
        total=Coalesce(Sum('repair_cost'), Value(Decimal('0.00'))),
        avg=Coalesce(Avg('repair_cost'), Value(Decimal('0.00'))),
    ).order_by('-total')

    by_department = []
    for d in dept_breakdown:
        by_department.append({
            'department': d['asset__department__name'] or 'Unassigned',
            'repairs_count': d['repairs'],
            'total_cost': d['total'],
            'average_cost': d['avg'],
        })

    # Top highest cost repairs
    top_cases = qs.order_by('-repair_cost')[:10]

    return qs.order_by('-repair_completed_at'), summary, by_department, top_cases


# ==============================================================================
# 6. PHYSICAL INVENTORY VERIFICATION REPORTS
# ==============================================================================

def get_verification_report(user, filters=None, mode='all'):
    """
    Physical inventory verification audits.
    - mode='all': All verification audit logs.
    - mode='mismatches': Location, Condition, or Location & Condition discrepancies.
    - mode='never_verified': Active assets that have never undergone audit.
    """
    filters = filters or {}
    chair_dept = get_user_department_scope(user)

    if mode == 'never_verified':
        # Assets that have never had a verification record
        asset_qs = Asset.objects.select_related(
            'department', 'current_location', 'category', 'brand'
        ).filter(
            verifications__isnull=True
        ).exclude(
            status=Asset.Status.DISPOSED
        )

        if chair_dept:
            asset_qs = asset_qs.filter(department=chair_dept)
        elif filters.get('department'):
            asset_qs = asset_qs.filter(department_id=filters['department'])

        q = filters.get('q', '').strip()
        if q:
            asset_qs = asset_qs.filter(
                Q(asset_code__icontains=q) |
                Q(property_number__icontains=q) |
                Q(item_name__icontains=q)
            )

        summary = {
            'total_never_verified': asset_qs.count(),
            'never_verified': asset_qs.count(),
        }
        return asset_qs.order_by('department__name', 'asset_code'), summary

    # Otherwise AssetVerification records
    qs = AssetVerification.objects.select_related(
        'asset', 'verified_by', 'expected_department', 'expected_location',
        'observed_department', 'observed_location'
    )

    if chair_dept:
        qs = qs.filter(Q(expected_department=chair_dept) | Q(observed_department=chair_dept))
    elif filters.get('department'):
        dept_id = filters['department']
        qs = qs.filter(Q(expected_department_id=dept_id) | Q(observed_department_id=dept_id))

    if mode == 'mismatches':
        qs = qs.exclude(result=AssetVerification.VerificationResult.VERIFIED)
    elif filters.get('result'):
        qs = qs.filter(result=filters['result'])

    date_from, date_to, _ = parse_date_range(filters.get('date_from'), filters.get('date_to'))
    if date_from:
        qs = qs.filter(verified_at__date__gte=date_from)
    if date_to:
        qs = qs.filter(verified_at__date__lte=date_to)

    q = filters.get('q', '').strip()
    if q:
        qs = qs.filter(
            Q(asset__asset_code__icontains=q) |
            Q(asset__item_name__icontains=q) |
            Q(remarks__icontains=q)
        )

    loc_mismatches = qs.filter(result=AssetVerification.VerificationResult.LOCATION_MISMATCH).count()
    cond_mismatches = qs.filter(result=AssetVerification.VerificationResult.CONDITION_MISMATCH).count()
    matches = qs.filter(result=AssetVerification.VerificationResult.VERIFIED).count()
    both = qs.filter(result=AssetVerification.VerificationResult.LOCATION_AND_CONDITION_MISMATCH).count()

    summary = {
        'total': qs.count(),
        'verified_matches': matches,
        'matched': matches,
        'location_mismatches': loc_mismatches,
        'location_mismatch': loc_mismatches,
        'condition_mismatches': cond_mismatches,
        'condition_mismatch': cond_mismatches,
        'both_mismatches': both,
        'verified_count': qs.count(),
        'not_found': 0,
        'never_verified': 0,
    }

    return qs.order_by('-verified_at'), summary


def format_verification_rows(records, mode='all'):
    if mode == 'never_verified':
        headers = ["Asset Code", "Property Number", "Item Name", "Department", "Current Location", "Status", "Acquisition Date"]
        column_types = ["center", "center", "left", "left", "left", "center", "center"]
        rows = []
        for a in records:
            rows.append([
                a.asset_code,
                a.property_number or "—",
                a.item_name,
                a.department.name if a.department else "—",
                a.current_location.name if a.current_location else "—",
                a.get_status_display(),
                a.acquisition_date,
            ])
        return headers, rows, column_types
    else:
        headers = [
            "Asset Code", "Item Name", "Expected Dept", "Observed Dept",
            "Expected Location", "Observed Location", "Expected Cond",
            "Observed Cond", "Audit Result", "Verified By", "Verified Date", "Remarks"
        ]
        column_types = [
            "center", "left", "left", "left",
            "left", "left", "center",
            "center", "center", "left", "center", "left"
        ]
        rows = []
        for v in records:
            rows.append([
                v.asset.asset_code,
                v.asset.item_name,
                v.expected_department.name if v.expected_department else "—",
                v.observed_department.name if v.observed_department else "—",
                v.expected_location.name if v.expected_location else "—",
                v.observed_location.name if v.observed_location else "—",
                v.get_expected_condition_display(),
                v.get_observed_condition_display(),
                v.get_result_display(),
                v.verified_by.get_full_name() if v.verified_by else "—",
                v.verified_at.strftime('%Y-%m-%d %H:%M'),
                v.remarks or "—",
            ])
        return headers, rows, column_types


# ==============================================================================
# 7. CONSUMABLE SUPPLIES REPORTS
# ==============================================================================

def get_supply_stock_report(user, filters=None, low_stock_only=False):
    """
    Authoritative supply stock report derived from the immutable ledger.
    Never relies on manual or static quantity fields.
    """
    filters = filters or {}
    _ = get_user_department_scope(user)  # Validates role

    # Annotated queryset computes total_in and total_out in SQL
    qs = supply_services.get_annotated_supplies_queryset().annotate(
        calculated_stock=F('total_in') - F('total_out')
    )

    if low_stock_only:
        # Stock at or below reorder level
        qs = qs.filter(calculated_stock__lte=F('reorder_level'))

    if filters.get('category'):
        qs = qs.filter(category_id=filters['category'])
    if filters.get('brand'):
        qs = qs.filter(brand_id=filters['brand'])

    status_filter = filters.get('stock_status')
    if status_filter == 'OUT_OF_STOCK':
        qs = qs.filter(calculated_stock__lte=0)
    elif status_filter == 'LOW_STOCK':
        qs = qs.filter(calculated_stock__gt=0, calculated_stock__lte=F('reorder_level'))
    elif status_filter == 'IN_STOCK':
        qs = qs.filter(calculated_stock__gt=F('reorder_level'))

    q = filters.get('q', '').strip()
    if q:
        qs = qs.filter(
            Q(item_name__icontains=q) |
            Q(supply_code__icontains=q) |
            Q(brand__name__icontains=q)
        )

    # Summary metrics
    all_annotated = list(qs)
    for s in all_annotated:
        s.shortfall = max(0, s.reorder_level - s.calculated_stock)

    summary = {
        'total_items': len(all_annotated),
        'in_stock_items': sum(1 for s in all_annotated if s.calculated_stock > s.reorder_level),
        'in_stock': sum(1 for s in all_annotated if s.calculated_stock > s.reorder_level),
        'low_stock_items': sum(1 for s in all_annotated if 0 < s.calculated_stock <= s.reorder_level),
        'low_stock': sum(1 for s in all_annotated if 0 < s.calculated_stock <= s.reorder_level),
        'out_of_stock_items': sum(1 for s in all_annotated if s.calculated_stock <= 0),
        'out_of_stock': sum(1 for s in all_annotated if s.calculated_stock <= 0),
    }

    if low_stock_only:
        # Sort by replenishment urgency (shortfall descending)
        all_annotated.sort(key=lambda s: (s.reorder_level - s.calculated_stock), reverse=True)
    else:
        all_annotated.sort(key=lambda s: s.item_name)

    return all_annotated, summary


def format_supply_stock_rows(supplies):
    headers = ["Supply Code", "Item Name", "Category", "Brand", "Unit", "Current Stock", "Reorder Level", "Stock Status", "Shortfall"]
    column_types = ["center", "left", "left", "left", "center", "integer", "integer", "center", "integer"]
    rows = []
    for s in supplies:
        stock = s.calculated_stock
        status_label = "Out of Stock" if stock <= 0 else ("Low Stock" if stock <= s.reorder_level else "In Stock")
        shortfall = max(0, s.reorder_level - stock)
        rows.append([
            s.supply_code,
            s.item_name,
            s.category.name if s.category else "—",
            s.brand.name if s.brand else "—",
            s.unit,
            stock,
            s.reorder_level,
            status_label,
            shortfall,
        ])
    return headers, rows, column_types


def get_supply_transactions_report(user, filters=None):
    """Immutable supply ledger transaction audit log."""
    filters = filters or {}
    chair_dept = get_user_department_scope(user)

    qs = SupplyTransaction.objects.select_related(
        'supply', 'supply__category', 'department', 'employee', 'processed_by'
    )

    if chair_dept:
        qs = qs.filter(department=chair_dept)
    elif filters.get('department'):
        qs = qs.filter(department_id=filters['department'])

    if filters.get('transaction_type'):
        qs = qs.filter(transaction_type=filters['transaction_type'])

    if filters.get('supply'):
        qs = qs.filter(supply_id=filters['supply'])

    if filters.get('employee'):
        qs = qs.filter(employee_id=filters['employee'])

    date_from, date_to, _ = parse_date_range(filters.get('date_from'), filters.get('date_to'))
    if date_from:
        qs = qs.filter(transaction_date__gte=date_from)
    if date_to:
        qs = qs.filter(transaction_date__lte=date_to)

    q = filters.get('q', '').strip()
    if q:
        qs = qs.filter(
            Q(supply__item_name__icontains=q) |
            Q(reference_number__icontains=q) |
            Q(purpose__icontains=q) |
            Q(employee__first_name__icontains=q) |
            Q(employee__last_name__icontains=q)
        )

    summary = {
        'total_transactions': qs.count(),
        'stock_in_count': qs.filter(transaction_type=SupplyTransaction.TransactionType.STOCK_IN).count(),
        'stock_out_count': qs.filter(transaction_type=SupplyTransaction.TransactionType.STOCK_OUT).count(),
        'adjustment_count': qs.filter(transaction_type__in=[
            SupplyTransaction.TransactionType.ADJUSTMENT_IN,
            SupplyTransaction.TransactionType.ADJUSTMENT_OUT
        ]).count(),
    }

    return qs.order_by('-transaction_date', '-created_at'), summary


def format_supply_transaction_rows(transactions):
    headers = ["Date", "Supply Code", "Item Name", "Transaction Type", "Quantity", "Department", "Recipient", "Reference #", "Purpose", "Logged By"]
    column_types = ["center", "center", "left", "center", "integer", "left", "left", "center", "left", "left"]
    rows = []
    for t in transactions:
        rows.append([
            t.transaction_date,
            t.supply.supply_code,
            t.supply.item_name,
            t.get_transaction_type_display(),
            t.quantity,
            t.department.name if t.department else "—",
            t.employee.full_name if t.employee else "—",
            t.reference_number or "—",
            t.purpose or "—",
            t.processed_by.get_full_name() if t.processed_by else "—",
        ])
    return headers, rows, column_types


def get_supply_department_usage_report(user, filters=None):
    """
    Aggregates consumable supplies issued (STOCK_OUT) by department.
    Guarantees that quantities are grouped strictly per supply item and unit,
    never mixing different measurement units.
    """
    filters = filters or {}
    chair_dept = get_user_department_scope(user)

    qs = SupplyTransaction.objects.filter(
        transaction_type=SupplyTransaction.TransactionType.STOCK_OUT,
        department__isnull=False
    ).select_related('department', 'supply')

    if chair_dept:
        qs = qs.filter(department=chair_dept)
    elif filters.get('department'):
        qs = qs.filter(department_id=filters['department'])

    date_from, date_to, _ = parse_date_range(filters.get('date_from'), filters.get('date_to'))
    if date_from:
        qs = qs.filter(transaction_date__gte=date_from)
    if date_to:
        qs = qs.filter(transaction_date__lte=date_to)

    # Group by department, supply item, unit
    usage_data = qs.values(
        'department__name',
        'supply__supply_code',
        'supply__item_name',
        'supply__unit'
    ).annotate(
        total_issued=Sum('quantity'),
        issuance_count=Count('id')
    ).order_by('department__name', '-total_issued')

    return list(usage_data)


# ==============================================================================
# 8. ASSET DISPOSAL REPORTS
# ==============================================================================

def get_disposal_report(user, filters=None):
    """Formal property disposal, condemnation, and retirement records."""
    filters = filters or {}
    chair_dept = get_user_department_scope(user)

    qs = AssetDisposal.objects.select_related(
        'asset', 'asset__department', 'asset__category', 'requested_by',
        'reviewed_by', 'processed_by'
    )

    if chair_dept:
        qs = qs.filter(asset__department=chair_dept)
    elif filters.get('department'):
        qs = qs.filter(asset__department_id=filters['department'])

    if filters.get('status'):
        qs = qs.filter(status=filters['status'])

    if filters.get('method'):
        qs = qs.filter(disposal_method=filters['method'])

    date_from, date_to, _ = parse_date_range(filters.get('date_from'), filters.get('date_to'))
    if date_from:
        qs = qs.filter(disposal_date__gte=date_from)
    if date_to:
        qs = qs.filter(disposal_date__lte=date_to)

    q = filters.get('q', '').strip()
    if q:
        qs = qs.filter(
            Q(disposal_number__icontains=q) |
            Q(asset__asset_code__icontains=q) |
            Q(asset__item_name__icontains=q) |
            Q(reason__icontains=q) |
            Q(recipient_or_destination__icontains=q) |
            Q(reference_number__icontains=q)
        )

    summary = qs.aggregate(
        total=Count('id'),
        completed=Count('id', filter=Q(status=AssetDisposal.Status.COMPLETED)),
        pending=Count('id', filter=Q(status=AssetDisposal.Status.PENDING)),
        approved=Count('id', filter=Q(status=AssetDisposal.Status.APPROVED)),
        total_proceeds=Coalesce(Sum('proceeds_amount', filter=Q(status=AssetDisposal.Status.COMPLETED)), Value(Decimal('0.00'))),
    )

    return qs.order_by('-requested_at'), summary


def format_disposal_rows(disposals):
    headers = [
        "Disposal ID", "Asset Code", "Property Number", "Item Name", "Department",
        "Condition", "Status", "Method", "Disposal Date", "Recipient / Destination",
        "Reference #", "Proceeds (PHP)", "Processed By"
    ]
    column_types = [
        "center", "center", "center", "left", "left",
        "center", "center", "center", "center", "left",
        "center", "currency", "left"
    ]
    rows = []
    for d in disposals:
        rows.append([
            d.disposal_number,
            d.asset.asset_code,
            d.asset.property_number or "—",
            d.asset.item_name,
            d.asset.department.name if d.asset.department else "—",
            d.get_condition_at_disposal_display(),
            d.get_status_display(),
            d.get_disposal_method_display() if d.disposal_method else "—",
            d.disposal_date or "—",
            d.recipient_or_destination or "—",
            d.reference_number or "—",
            d.proceeds_amount or Decimal('0.00'),
            d.processed_by.get_full_name() if d.processed_by else "—",
        ])
    return headers, rows, column_types


# ==============================================================================
# 9. SYSTEM AUDIT LOG REPORT (ADMIN ONLY)
# ==============================================================================

def get_audit_log_report(user, filters=None):
    """
    Searchable administrative audit trail report.
    Strictly restricted to administrators.
    """
    if not getattr(user, 'is_admin', False):
        raise PermissionDenied("Only System Administrators can inspect the audit log report.")

    filters = filters or {}
    qs = AuditLog.objects.select_related('user')

    if filters.get('action'):
        qs = qs.filter(action=filters['action'])

    if filters.get('user'):
        qs = qs.filter(user_id=filters['user'])

    date_from, date_to, _ = parse_date_range(filters.get('date_from'), filters.get('date_to'))
    if date_from:
        qs = qs.filter(timestamp__date__gte=date_from)
    if date_to:
        qs = qs.filter(timestamp__date__lte=date_to)

    q = filters.get('q', '').strip()
    if q:
        qs = qs.filter(
            Q(action__icontains=q) |
            Q(model_name__icontains=q) |
            Q(object_repr__icontains=q) |
            Q(object_id__icontains=q) |
            Q(user__username__icontains=q) |
            Q(ip_address__icontains=q)
        )

    summary = {
        'total_logs': qs.count(),
        'unique_actions': qs.values('action').distinct().count(),
        'unique_users': qs.values('user').distinct().count(),
    }

    return qs.order_by('-timestamp'), summary


def format_audit_log_rows(logs):
    headers = ["Timestamp", "User", "Action", "Model Target", "Object ID", "Object Summary", "IP Address"]
    column_types = ["center", "left", "center", "left", "center", "left", "center"]
    rows = []
    for l in logs:
        rows.append([
            l.timestamp.strftime('%Y-%m-%d %H:%M:%S'),
            l.user.username if l.user else "System",
            l.action,
            l.model_name,
            l.object_id or "—",
            l.object_repr or "—",
            l.ip_address or "—",
        ])
    return headers, rows, column_types


# ==============================================================================
# 10. CONSOLIDATED EXECUTIVE MULTI-SHEET WORKBOOK
# ==============================================================================

def get_executive_summary_workbook_data(user):
    """
    Compiles data across all domains into a multi-sheet executive workbook.
    """
    chair_dept = get_user_department_scope(user)

    # 1. Summary Sheet
    summary_headers = ["Domain / Operational Metric", "Quantity / Aggregate Total", "Remarks"]
    summary_types = ["left", "integer", "left"]
    
    asset_qs = Asset.objects.all()
    if chair_dept:
        asset_qs = asset_qs.filter(department=chair_dept)

    total_assets = asset_qs.count()
    active_assets = asset_qs.exclude(status=Asset.Status.DISPOSED).count()
    assigned_assets = asset_qs.filter(status=Asset.Status.ASSIGNED).count()
    borrowed_assets = asset_qs.filter(status=Asset.Status.BORROWED).count()
    maintenance_assets = asset_qs.filter(status=Asset.Status.MAINTENANCE).count()
    damaged_assets = asset_qs.filter(status=Asset.Status.DAMAGED).count()
    disposed_assets = asset_qs.filter(status=Asset.Status.DISPOSED).count()

    # Supplies
    all_supplies = supply_services.get_annotated_supplies_queryset().annotate(
        calculated_stock=F('total_in') - F('total_out')
    )
    low_supplies_count = sum(1 for s in all_supplies if s.calculated_stock <= s.reorder_level)

    summary_rows = [
        ["Total Assets Registered", total_assets, "All durable assets in institutional record"],
        ["Active Assets in Operation", active_assets, "Excludes retired / disposed equipment"],
        ["Assets Assigned to Personnel", assigned_assets, "Under formal faculty/staff accountability"],
        ["Assets Currently on Loan", borrowed_assets, "Temporary classroom/activity borrowing"],
        ["Assets Under Maintenance", maintenance_assets, "Under active repair or diagnostic evaluation"],
        ["Assets Marked Damaged", damaged_assets, "Non-operational / unserviceable condition"],
        ["Permanently Disposed Assets", disposed_assets, "Condemned, scrapped, or donated"],
        ["Supplies at / Below Reorder Threshold", low_supplies_count, "Requires immediate replenishment"],
    ]

    # 2. Asset Inventory Sheet
    assets_qs, _ = get_asset_inventory_report(user, {'scope': 'all'})
    asset_headers, asset_rows, asset_types = format_asset_inventory_rows(assets_qs[:500])

    # 3. Accountability Sheet
    acc_qs, _ = get_accountability_report(user, {}, historical=False)
    acc_headers, acc_rows, acc_types = format_accountability_rows(acc_qs[:500], historical=False)

    # 4. Borrowing Sheet
    brw_qs, _ = get_borrowing_report(user, {})
    brw_headers, brw_rows, brw_types = format_borrowing_rows(brw_qs[:500])

    # 5. Maintenance Sheet
    mnt_qs, _ = get_maintenance_report(user, {})
    mnt_headers, mnt_rows, mnt_types = format_maintenance_rows(mnt_qs[:500])

    # 6. Supplies Sheet
    supplies_list, _ = get_supply_stock_report(user, {})
    sup_headers, sup_rows, sup_types = format_supply_stock_rows(supplies_list[:500])

    # 7. Disposals Sheet
    dsp_qs, _ = get_disposal_report(user, {})
    dsp_headers, dsp_rows, dsp_types = format_disposal_rows(dsp_qs[:500])

    sheets = [
        {
            'sheet_name': 'Executive Summary',
            'headers': summary_headers,
            'rows': summary_rows,
            'column_types': summary_types,
        },
        {
            'sheet_name': 'Asset Inventory',
            'headers': asset_headers,
            'rows': asset_rows,
            'column_types': asset_types,
        },
        {
            'sheet_name': 'Faculty Accountability',
            'headers': acc_headers,
            'rows': acc_rows,
            'column_types': acc_types,
        },
        {
            'sheet_name': 'Equipment Borrowing',
            'headers': brw_headers,
            'rows': brw_rows,
            'column_types': brw_types,
        },
        {
            'sheet_name': 'Maintenance & Repairs',
            'headers': mnt_headers,
            'rows': mnt_rows,
            'column_types': mnt_types,
        },
        {
            'sheet_name': 'Consumable Supplies',
            'headers': sup_headers,
            'rows': sup_rows,
            'column_types': sup_types,
        },
        {
            'sheet_name': 'Asset Disposals',
            'headers': dsp_headers,
            'rows': dsp_rows,
            'column_types': dsp_types,
        },
    ]

    return sheets
