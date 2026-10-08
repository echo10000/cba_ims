from django.db import transaction
from django.core.exceptions import ValidationError
from django.utils import timezone
from apps.inventory.models import Asset
from apps.organizations.models import Employee
from apps.audit.utils import log_action
from .models import AssetAssignment


def assign_asset(
    asset,
    employee,
    assigned_by,
    assigned_date=None,
    expected_return_date=None,
    purpose='',
    remarks='',
    request=None
):
    """
    Atomically assign an eligible asset to an active faculty member/staff.
    Acquires row-level database lock and synchronizes asset status to ASSIGNED.
    """
    if assigned_date is None:
        assigned_date = timezone.now().date()

    with transaction.atomic():
        # Lock asset record to prevent race conditions
        locked_asset = Asset.objects.select_for_update().get(pk=asset.pk)

        # Validate eligibility
        if locked_asset.status != Asset.Status.AVAILABLE:
            raise ValidationError(
                f"Asset '{locked_asset.asset_code}' cannot be assigned because its status is "
                f"'{locked_asset.get_status_display()}'. Only AVAILABLE assets may be assigned."
            )

        # Ensure no active assignment exists
        if AssetAssignment.objects.filter(asset=locked_asset, status=AssetAssignment.Status.ACTIVE).exists():
            raise ValidationError(
                f"Asset '{locked_asset.asset_code}' already has an active assignment."
            )

        # Ensure no active or approved student reservations exist
        from apps.student_reservations.models import StudentReservation
        from apps.student_reservations.services import auto_expire_uncollected_reservations
        auto_expire_uncollected_reservations()

        active_student_res = StudentReservation.objects.filter(
            asset=locked_asset,
            status__in=[
                StudentReservation.Status.APPROVED,
                StudentReservation.Status.RELEASED,
                StudentReservation.Status.RETURNED_TO_GUARD
            ]
        )
        valid_student_res = [
            r for r in active_student_res
            if not (r.status == StudentReservation.Status.APPROVED and r.is_pickup_expired)
        ]
        if valid_student_res:
            raise ValidationError(
                f"Asset '{locked_asset.asset_code}' has an approved or active student reservation and cannot be assigned."
            )

        # Ensure no active or approved borrowings exist
        from apps.borrowing.models import AssetBorrowing
        if AssetBorrowing.objects.filter(
            asset=locked_asset,
            status__in=[AssetBorrowing.Status.APPROVED, AssetBorrowing.Status.RELEASED, AssetBorrowing.Status.OVERDUE]
        ).exists():
            raise ValidationError(
                f"Asset '{locked_asset.asset_code}' has an approved or active borrowing and cannot be assigned."
            )

        # Ensure employee is active
        if not employee.is_active:
            raise ValidationError(
                f"Cannot assign property to inactive employee '{employee.full_name}'."
            )

        # Create assignment record preserving snapshot of condition
        assignment = AssetAssignment.objects.create(
            asset=locked_asset,
            employee=employee,
            assigned_date=assigned_date,
            expected_return_date=expected_return_date,
            purpose=purpose.strip(),
            condition_at_assignment=locked_asset.condition,
            assigned_by=assigned_by,
            status=AssetAssignment.Status.ACTIVE,
            remarks=remarks.strip(),
        )

        # Synchronize asset status
        locked_asset.status = Asset.Status.ASSIGNED
        locked_asset.save(update_fields=['status', 'updated_at'])

        # Audit Log
        log_action(
            user=assigned_by,
            action='ASSET_ASSIGNED',
            instance=assignment,
            changes={
                'asset_code': locked_asset.asset_code,
                'item_name': locked_asset.item_name,
                'employee': employee.full_name,
                'department': employee.department.name if employee.department else '',
                'assigned_date': str(assigned_date),
                'condition_at_assignment': assignment.condition_at_assignment,
            },
            request=request
        )

        return assignment


def return_asset(
    assignment,
    returned_by,
    returned_date=None,
    condition_at_return=None,
    remarks='',
    request=None
):
    """
    Atomically process return of an assigned asset.
    Releases accountability, records historical condition, and updates asset availability.
    """
    if returned_date is None:
        returned_date = timezone.now().date()

    with transaction.atomic():
        # Lock assignment and asset records
        locked_assignment = AssetAssignment.objects.select_for_update().select_related('asset', 'employee').get(pk=assignment.pk)
        locked_asset = Asset.objects.select_for_update().get(pk=locked_assignment.asset.pk)

        if locked_assignment.status != AssetAssignment.Status.ACTIVE:
            raise ValidationError(
                f"Assignment #{locked_assignment.pk} is already marked as {locked_assignment.get_status_display()}."
            )

        if condition_at_return is None:
            condition_at_return = locked_assignment.condition_at_assignment

        # Update assignment
        locked_assignment.status = AssetAssignment.Status.RETURNED
        locked_assignment.returned_date = returned_date
        locked_assignment.returned_by = returned_by
        locked_assignment.condition_at_return = condition_at_return
        if remarks:
            existing = f"{locked_assignment.remarks}\n" if locked_assignment.remarks else ""
            locked_assignment.remarks = f"{existing}[Return]: {remarks.strip()}".strip()
        locked_assignment.save()

        # Update Asset condition and status
        locked_asset.condition = condition_at_return
        if condition_at_return == Asset.Condition.UNSERVICEABLE:
            locked_asset.status = Asset.Status.DAMAGED
        else:
            locked_asset.status = Asset.Status.AVAILABLE
        locked_asset.save(update_fields=['condition', 'status', 'updated_at'])

        # Audit Log
        log_action(
            user=returned_by,
            action='ASSET_RETURNED',
            instance=locked_assignment,
            changes={
                'asset_code': locked_asset.asset_code,
                'item_name': locked_asset.item_name,
                'employee': locked_assignment.employee.full_name,
                'returned_date': str(returned_date),
                'condition_at_return': condition_at_return,
                'resulting_asset_status': locked_asset.status,
            },
            request=request
        )

        return locked_assignment
