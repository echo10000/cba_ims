from django.db import transaction
from django.core.exceptions import ValidationError
from django.utils import timezone
from apps.inventory.models import Asset
from apps.organizations.models import Department, Location
from apps.audit.utils import log_action
from .models import AssetTransfer


def request_transfer(
    asset,
    to_department,
    to_location,
    requested_by,
    transfer_date=None,
    reason='',
    remarks='',
    request=None
):
    """
    Atomically creates a pending transfer request for an eligible asset.
    Snapshots origin department and location from the asset's current state.
    """
    if transfer_date is None:
        transfer_date = timezone.now().date()

    with transaction.atomic():
        # Lock asset row to avoid concurrent state changes
        locked_asset = Asset.objects.select_for_update().select_related('department', 'current_location').get(pk=asset.pk)

        # Operational status eligibility: only AVAILABLE or ASSIGNED assets can be transferred
        if locked_asset.status not in [Asset.Status.AVAILABLE, Asset.Status.ASSIGNED]:
            raise ValidationError(
                f"Asset '{locked_asset.asset_code}' cannot be transferred because its status is "
                f"'{locked_asset.get_status_display()}'. Only AVAILABLE or ASSIGNED assets are eligible for transfer."
            )

        # Check for conflicting open transfers
        if AssetTransfer.objects.filter(
            asset=locked_asset,
            status__in=[AssetTransfer.Status.PENDING, AssetTransfer.Status.APPROVED]
        ).exists():
            raise ValidationError(
                f"Asset '{locked_asset.asset_code}' already has an active or pending transfer request."
            )

        # Destination must differ from current origin
        from_dept = locked_asset.department
        from_loc = locked_asset.current_location

        if from_dept == to_department and from_loc == to_location:
            raise ValidationError(
                "Destination department and location cannot be identical to the current origin."
            )

        # Validate that destination location belongs to destination department (if location has a department)
        if to_location and to_location.department_id and to_location.department_id != to_department.pk:
            raise ValidationError(
                f"Location '{to_location.name}' belongs to {to_location.department.name}, not {to_department.name}."
            )

        # Create transfer record with immutable origin snapshots
        transfer = AssetTransfer.objects.create(
            asset=locked_asset,
            from_department=from_dept,
            from_location=from_loc,
            to_department=to_department,
            to_location=to_location,
            transfer_date=transfer_date,
            reason=reason.strip(),
            remarks=remarks.strip(),
            requested_by=requested_by,
            status=AssetTransfer.Status.PENDING,
        )

        # Log audit entry
        log_action(
            user=requested_by,
            action='TRANSFER_REQUESTED',
            instance=transfer,
            changes={
                'asset_code': locked_asset.asset_code,
                'item_name': locked_asset.item_name,
                'from_department': from_dept.name,
                'from_location': from_loc.name if from_loc else '',
                'to_department': to_department.name,
                'to_location': to_location.name if to_location else '',
                'reason': transfer.reason,
            },
            request=request
        )

        return transfer


def approve_transfer(transfer, approved_by, remarks='', request=None):
    """
    Authorizes a pending transfer request.
    """
    with transaction.atomic():
        locked_transfer = AssetTransfer.objects.select_for_update().select_related(
            'asset', 'from_department', 'from_location', 'to_department', 'to_location'
        ).get(pk=transfer.pk)

        if locked_transfer.status != AssetTransfer.Status.PENDING:
            raise ValidationError(
                f"Transfer #{locked_transfer.pk} cannot be approved because its status is "
                f"'{locked_transfer.get_status_display()}'. Only PENDING transfers can be approved."
            )

        locked_transfer.status = AssetTransfer.Status.APPROVED
        locked_transfer.approved_by = approved_by
        locked_transfer.approved_at = timezone.now()
        if remarks:
            existing = f"{locked_transfer.remarks}\n" if locked_transfer.remarks else ""
            locked_transfer.remarks = f"{existing}[Approval]: {remarks.strip()}".strip()
        locked_transfer.save()

        log_action(
            user=approved_by,
            action='TRANSFER_APPROVED',
            instance=locked_transfer,
            changes={
                'asset_code': locked_transfer.asset.asset_code,
                'status': locked_transfer.status,
                'approved_by': approved_by.username if approved_by else '',
            },
            request=request
        )

        return locked_transfer


def reject_transfer(transfer, rejected_by, reason='', request=None):
    """
    Rejects a pending transfer request.
    """
    with transaction.atomic():
        locked_transfer = AssetTransfer.objects.select_for_update().select_related(
            'asset', 'from_department', 'to_department'
        ).get(pk=transfer.pk)

        if locked_transfer.status != AssetTransfer.Status.PENDING:
            raise ValidationError(
                f"Transfer #{locked_transfer.pk} cannot be rejected because its status is "
                f"'{locked_transfer.get_status_display()}'. Only PENDING transfers can be rejected."
            )

        locked_transfer.status = AssetTransfer.Status.REJECTED
        if reason:
            existing = f"{locked_transfer.remarks}\n" if locked_transfer.remarks else ""
            locked_transfer.remarks = f"{existing}[Rejection]: {reason.strip()}".strip()
        locked_transfer.save()

        log_action(
            user=rejected_by,
            action='TRANSFER_REJECTED',
            instance=locked_transfer,
            changes={
                'asset_code': locked_transfer.asset.asset_code,
                'status': locked_transfer.status,
                'rejected_by': rejected_by.username if rejected_by else '',
                'reason': reason,
            },
            request=request
        )

        return locked_transfer


def complete_transfer(transfer, processed_by, remarks='', request=None):
    """
    Atomically completes an authorized transfer.
    Synchronizes Asset department and location while preserving asset operational status
    and existing personal accountability.
    Guards against stale origin conflicts.
    """
    with transaction.atomic():
        locked_transfer = AssetTransfer.objects.select_for_update().select_related(
            'asset', 'from_department', 'from_location', 'to_department', 'to_location'
        ).get(pk=transfer.pk)

        locked_asset = Asset.objects.select_for_update().get(pk=locked_transfer.asset.pk)

        # Must be in an allowed state (APPROVED or PENDING if directly authorized)
        if locked_transfer.status not in [AssetTransfer.Status.APPROVED, AssetTransfer.Status.PENDING]:
            raise ValidationError(
                f"Transfer #{locked_transfer.pk} cannot be completed because its status is "
                f"'{locked_transfer.get_status_display()}'. Only APPROVED or PENDING transfers can be completed."
            )

        # Source State Conflict Check:
        # Confirm asset's current state still matches the recorded origin snapshot
        if locked_asset.department_id != locked_transfer.from_department_id or \
           locked_asset.current_location_id != locked_transfer.from_location_id:
            curr_loc_str = locked_asset.current_location.name if locked_asset.current_location else 'No Location'
            exp_loc_str = locked_transfer.from_location.name if locked_transfer.from_location else 'No Location'
            raise ValidationError(
                f"Origin conflict: Asset '{locked_asset.asset_code}' is currently at "
                f"'{locked_asset.department.name} / {curr_loc_str}', but this transfer originated from "
                f"'{locked_transfer.from_department.name} / {exp_loc_str}'. The transfer cannot be completed with stale origin data."
            )

        # Update Asset location & department
        # Architectural rule: Preserve asset status (AVAILABLE remains AVAILABLE, ASSIGNED remains ASSIGNED)
        old_dept = locked_asset.department.name
        old_loc = locked_asset.current_location.name if locked_asset.current_location else 'None'

        locked_asset.department = locked_transfer.to_department
        locked_asset.current_location = locked_transfer.to_location
        locked_asset.save(update_fields=['department', 'current_location', 'updated_at'])

        # Update Transfer record
        locked_transfer.status = AssetTransfer.Status.COMPLETED
        locked_transfer.completed_at = timezone.now()
        locked_transfer.processed_by = processed_by
        if not locked_transfer.approved_by:
            locked_transfer.approved_by = processed_by
            locked_transfer.approved_at = timezone.now()

        if remarks:
            existing = f"{locked_transfer.remarks}\n" if locked_transfer.remarks else ""
            locked_transfer.remarks = f"{existing}[Completion]: {remarks.strip()}".strip()

        locked_transfer.save()

        # Audit log
        log_action(
            user=processed_by,
            action='TRANSFER_COMPLETED',
            instance=locked_transfer,
            changes={
                'asset_code': locked_asset.asset_code,
                'from_department': old_dept,
                'from_location': old_loc,
                'to_department': locked_transfer.to_department.name,
                'to_location': locked_transfer.to_location.name if locked_transfer.to_location else '',
                'asset_status': locked_asset.status,
            },
            request=request
        )

        return locked_transfer


def cancel_transfer(transfer, cancelled_by, reason='', request=None):
    """
    Cancels an open (PENDING or APPROVED) transfer.
    """
    with transaction.atomic():
        locked_transfer = AssetTransfer.objects.select_for_update().select_related(
            'asset', 'from_department', 'to_department'
        ).get(pk=transfer.pk)

        if locked_transfer.status not in [AssetTransfer.Status.PENDING, AssetTransfer.Status.APPROVED]:
            raise ValidationError(
                f"Transfer #{locked_transfer.pk} cannot be cancelled because its status is "
                f"'{locked_transfer.get_status_display()}'."
            )

        locked_transfer.status = AssetTransfer.Status.CANCELLED
        locked_transfer.cancelled_at = timezone.now()
        if reason:
            existing = f"{locked_transfer.remarks}\n" if locked_transfer.remarks else ""
            locked_transfer.remarks = f"{existing}[Cancellation]: {reason.strip()}".strip()

        locked_transfer.save()

        log_action(
            user=cancelled_by,
            action='TRANSFER_CANCELLED',
            instance=locked_transfer,
            changes={
                'asset_code': locked_transfer.asset.asset_code,
                'status': locked_transfer.status,
                'cancelled_by': cancelled_by.username if cancelled_by else '',
                'reason': reason,
            },
            request=request
        )

        return locked_transfer
