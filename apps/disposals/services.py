from decimal import Decimal
from django.db import transaction
from django.core.exceptions import ValidationError, PermissionDenied
from django.utils import timezone

from apps.inventory.models import Asset
from apps.audit.utils import log_action
from .models import AssetDisposal


def validate_disposal_eligibility(asset):
    """
    Checks whether an asset is eligible for disposal request.
    Eligible: DAMAGED, UNSERVICEABLE condition, or FOR_REPLACEMENT maintenance outcome.
    Not eligible: BORROWED, MAINTENANCE, already DISPOSED, or with active conflicting lifecycle.
    Returns (is_eligible, reason_message).
    """
    if asset.status == Asset.Status.DISPOSED:
        return False, f"Asset '{asset.asset_code}' is already disposed."

    if asset.status == Asset.Status.BORROWED:
        return False, (
            f"Asset '{asset.asset_code}' is currently on loan. "
            "The equipment must be returned before disposal can be initiated."
        )

    if asset.status == Asset.Status.MAINTENANCE:
        return False, (
            f"Asset '{asset.asset_code}' is currently under maintenance/repair. "
            "The maintenance case must reach a terminal state before disposal."
        )

    # Check for active borrowings (RELEASED / OVERDUE)
    if asset.borrowings.filter(status__in=['RELEASED', 'OVERDUE']).exists():
        return False, (
            f"Asset '{asset.asset_code}' has an active equipment loan. "
            "The loan must be returned before disposal."
        )

    # Check for open transfers (PENDING / APPROVED)
    if asset.transfers.filter(status__in=['PENDING', 'APPROVED']).exists():
        return False, (
            f"Asset '{asset.asset_code}' has an open transfer request. "
            "The transfer must be resolved or cancelled before disposal."
        )

    # Check for active maintenance IN_REPAIR
    if asset.maintenance_records.filter(status='IN_REPAIR').exists():
        return False, (
            f"Asset '{asset.asset_code}' has an active maintenance case in repair. "
            "The repair must complete before disposal."
        )

    # Check if there's already an active disposal request
    if AssetDisposal.objects.filter(
        asset=asset,
        status__in=[AssetDisposal.Status.PENDING, AssetDisposal.Status.APPROVED]
    ).exists():
        return False, (
            f"Asset '{asset.asset_code}' already has an active disposal request."
        )

    return True, ""


def validate_completion_eligibility(asset):
    """
    Re-validates asset eligibility at completion time with stricter checks.
    Ensures no active assignments, borrowings, transfers, or repairs remain.
    """
    # Active assignment check
    if asset.assignments.filter(status='ACTIVE').exists():
        return False, (
            "This asset is still assigned to an employee. "
            "Complete the accountability return before disposal."
        )

    # Active borrowing check
    if asset.borrowings.filter(status__in=['RELEASED', 'OVERDUE']).exists():
        return False, (
            "This asset has an active equipment loan. "
            "The loan must be returned before disposal completion."
        )

    # Approved future reservations
    approved_reservations = asset.borrowings.filter(status='APPROVED')
    if approved_reservations.exists():
        return False, (
            "This asset has approved future borrowing reservations. "
            "Cancel all pending reservations before disposal completion."
        )

    # Open transfers
    if asset.transfers.filter(status__in=['PENDING', 'APPROVED']).exists():
        return False, (
            "This asset has an open transfer request. "
            "Resolve or cancel the transfer before disposal completion."
        )

    # Active repairs
    if asset.maintenance_records.filter(status='IN_REPAIR').exists():
        return False, (
            "This asset has an active maintenance case in repair. "
            "The repair must complete before disposal."
        )

    return True, ""


def request_disposal(
    asset,
    requested_by,
    reason,
    condition_at_disposal=None,
    maintenance_reference=None,
    remarks='',
    request=None
):
    """
    Initiates a disposal request for an eligible asset.
    Status starts as PENDING. Asset.status is NOT modified yet.
    """
    is_eligible, msg = validate_disposal_eligibility(asset)
    if not is_eligible:
        raise ValidationError(msg)

    if not reason or not reason.strip():
        raise ValidationError("A disposal reason/justification is required.")

    if condition_at_disposal is None:
        condition_at_disposal = asset.condition

    with transaction.atomic():
        disposal = AssetDisposal(
            asset=asset,
            requested_by=requested_by,
            requested_at=timezone.now(),
            reason=reason.strip(),
            condition_at_disposal=condition_at_disposal,
            maintenance_reference=maintenance_reference,
            recommended_by=requested_by,
            remarks=remarks.strip(),
            status=AssetDisposal.Status.PENDING,
        )
        disposal.save()

        log_action(
            user=requested_by,
            action='DISPOSAL_REQUESTED',
            instance=disposal,
            changes={
                'disposal_number': disposal.disposal_number,
                'asset_code': asset.asset_code,
                'item_name': asset.item_name,
                'reason': disposal.reason,
                'condition': disposal.get_condition_at_disposal_display(),
                'maintenance_ref': str(maintenance_reference.case_number) if maintenance_reference else '',
            },
            request=request
        )

    return disposal


def approve_disposal(
    disposal,
    reviewed_by,
    review_remarks='',
    request=None
):
    """
    Approves a pending disposal request.
    Validates PENDING status. Does NOT modify Asset.status yet.
    """
    with transaction.atomic():
        locked = AssetDisposal.objects.select_for_update().select_related('asset').get(pk=disposal.pk)
        locked_asset = Asset.objects.select_for_update().get(pk=locked.asset.pk)

        if locked.status != AssetDisposal.Status.PENDING:
            raise ValidationError(
                f"Cannot approve {locked.disposal_number}: current status is "
                f"'{locked.get_status_display()}'. Only PENDING requests can be approved."
            )

        # Re-validate that asset hasn't become ineligible
        if locked_asset.status == Asset.Status.DISPOSED:
            raise ValidationError(
                f"Asset '{locked_asset.asset_code}' has already been disposed."
            )

        locked.status = AssetDisposal.Status.APPROVED
        locked.reviewed_by = reviewed_by
        locked.reviewed_at = timezone.now()
        locked.review_remarks = review_remarks.strip()
        locked.save()

        log_action(
            user=reviewed_by,
            action='DISPOSAL_APPROVED',
            instance=locked,
            changes={
                'disposal_number': locked.disposal_number,
                'asset_code': locked_asset.asset_code,
                'status': locked.get_status_display(),
            },
            request=request
        )

    return locked


def reject_disposal(
    disposal,
    reviewed_by,
    review_remarks='',
    request=None
):
    """
    Rejects a pending disposal request.
    """
    if not review_remarks or not review_remarks.strip():
        raise ValidationError("A rejection reason must be provided.")

    with transaction.atomic():
        locked = AssetDisposal.objects.select_for_update().select_related('asset').get(pk=disposal.pk)

        if locked.status != AssetDisposal.Status.PENDING:
            raise ValidationError(
                f"Cannot reject {locked.disposal_number}: current status is "
                f"'{locked.get_status_display()}'. Only PENDING requests can be rejected."
            )

        locked.status = AssetDisposal.Status.REJECTED
        locked.reviewed_by = reviewed_by
        locked.reviewed_at = timezone.now()
        locked.review_remarks = review_remarks.strip()
        locked.save()

        log_action(
            user=reviewed_by,
            action='DISPOSAL_REJECTED',
            instance=locked,
            changes={
                'disposal_number': locked.disposal_number,
                'asset_code': locked.asset.asset_code,
                'review_remarks': locked.review_remarks,
            },
            request=request
        )

    return locked


def cancel_disposal(
    disposal,
    cancelled_by,
    cancellation_reason='',
    request=None
):
    """
    Cancels an active disposal request (PENDING or APPROVED).
    """
    with transaction.atomic():
        locked = AssetDisposal.objects.select_for_update().select_related('asset').get(pk=disposal.pk)

        if locked.status not in [AssetDisposal.Status.PENDING, AssetDisposal.Status.APPROVED]:
            raise ValidationError(
                f"Cannot cancel {locked.disposal_number}: current status is "
                f"'{locked.get_status_display()}'. Only PENDING or APPROVED requests can be cancelled."
            )

        locked.status = AssetDisposal.Status.CANCELLED
        locked.reviewed_by = cancelled_by
        locked.reviewed_at = timezone.now()
        if cancellation_reason.strip():
            locked.review_remarks = (
                f"{locked.review_remarks}\nCancellation: {cancellation_reason.strip()}".strip()
                if locked.review_remarks else
                f"Cancellation: {cancellation_reason.strip()}"
            )
        locked.save()

        log_action(
            user=cancelled_by,
            action='DISPOSAL_CANCELLED',
            instance=locked,
            changes={
                'disposal_number': locked.disposal_number,
                'asset_code': locked.asset.asset_code,
                'cancellation_reason': cancellation_reason.strip(),
            },
            request=request
        )

    return locked


def complete_disposal(
    disposal,
    processed_by,
    disposal_method,
    disposal_date=None,
    recipient_or_destination='',
    reference_number='',
    proceeds_amount=None,
    remarks='',
    request=None
):
    """
    Executes the physical disposal of the asset. This is the terminal lifecycle action.

    Steps (atomic):
    1. Lock AssetDisposal and Asset records.
    2. Verify APPROVED status.
    3. Re-check active assignment, borrowing, transfer, and repair eligibility.
    4. Record disposal execution details.
    5. Set Asset.status = DISPOSED.
    6. Preserve Asset.condition, asset_code, property_number.
    7. Write immutable audit log.
    """
    if not disposal_method:
        raise ValidationError("A disposal method must be selected.")

    if disposal_date is None:
        disposal_date = timezone.now().date()

    if proceeds_amount is not None and proceeds_amount < Decimal('0.00'):
        raise ValidationError("Proceeds amount cannot be negative.")

    with transaction.atomic():
        locked = AssetDisposal.objects.select_for_update().select_related('asset').get(pk=disposal.pk)
        locked_asset = Asset.objects.select_for_update().get(pk=locked.asset.pk)

        if locked.status != AssetDisposal.Status.APPROVED:
            raise ValidationError(
                f"Cannot complete {locked.disposal_number}: current status is "
                f"'{locked.get_status_display()}'. Only APPROVED disposals can be completed."
            )

        # Re-check all blocking lifecycle conditions at completion time
        is_eligible, msg = validate_completion_eligibility(locked_asset)
        if not is_eligible:
            raise ValidationError(msg)

        # Already disposed check
        if locked_asset.status == Asset.Status.DISPOSED:
            raise ValidationError(
                f"Asset '{locked_asset.asset_code}' has already been disposed."
            )

        # Record disposal execution details
        locked.disposal_method = disposal_method
        locked.disposal_date = disposal_date
        locked.processed_by = processed_by
        locked.recipient_or_destination = recipient_or_destination.strip()
        locked.reference_number = reference_number.strip()
        locked.proceeds_amount = proceeds_amount
        locked.completed_at = timezone.now()
        locked.status = AssetDisposal.Status.COMPLETED

        if remarks.strip():
            existing = locked.remarks
            locked.remarks = (
                f"{existing}\nCompletion: {remarks.strip()}".strip()
                if existing else
                f"Completion: {remarks.strip()}"
            )

        locked.save()

        # Transition asset to DISPOSED — preserve condition, code, property number
        locked_asset.status = Asset.Status.DISPOSED
        locked_asset.save(update_fields=['status', 'updated_at'])

        log_action(
            user=processed_by,
            action='ASSET_DISPOSED',
            instance=locked,
            changes={
                'disposal_number': locked.disposal_number,
                'asset_code': locked_asset.asset_code,
                'item_name': locked_asset.item_name,
                'disposal_method': locked.get_disposal_method_display(),
                'disposal_date': str(locked.disposal_date),
                'condition': locked.get_condition_at_disposal_display(),
                'reference_number': locked.reference_number,
                'recipient': locked.recipient_or_destination,
                'proceeds': str(locked.proceeds_amount) if locked.proceeds_amount else '0.00',
            },
            request=request
        )

    return locked
