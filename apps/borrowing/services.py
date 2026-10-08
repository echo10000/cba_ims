from django.db import transaction
from django.core.exceptions import ValidationError
from django.utils import timezone
from datetime import timedelta

from apps.inventory.models import Asset
from apps.organizations.models import Employee
from apps.audit.utils import log_action
from .models import AssetBorrowing


def check_reservation_conflict(asset, requested_start, requested_return, exclude_borrowing_id=None):
    """
    Checks if an asset has overlapping approved reservations or active physical releases.
    Two periods [start_a, return_a] and [start_b, return_b] overlap iff:
    start_a < return_b AND return_a > start_b.
    Returns queryset of conflicting AssetBorrowing records.
    """
    qs = AssetBorrowing.objects.filter(
        asset=asset,
        status__in=[
            AssetBorrowing.Status.APPROVED,
            AssetBorrowing.Status.RELEASED,
            AssetBorrowing.Status.OVERDUE
        ],
        requested_start__lt=requested_return,
        requested_return__gt=requested_start
    )
    if exclude_borrowing_id:
        qs = qs.exclude(pk=exclude_borrowing_id)
    return qs


def check_student_reservation_conflict(asset, requested_start, requested_return):
    """
    Checks if an asset has overlapping approved/active student reservations or guard returns.
    Shared availability rule to prevent faculty borrowing bypassing student reservations.
    """
    from apps.student_reservations.models import StudentReservation
    from apps.student_reservations.services import auto_expire_uncollected_reservations
    auto_expire_uncollected_reservations()

    # Guard-returned equipment awaiting inspection blocks the asset
    guard_qs = StudentReservation.objects.filter(
        asset=asset,
        status=StudentReservation.Status.RETURNED_TO_GUARD
    )
    if guard_qs.exists():
        return guard_qs

    qs = StudentReservation.objects.filter(
        asset=asset,
        status__in=[
            StudentReservation.Status.APPROVED,
            StudentReservation.Status.RELEASED
        ],
        requested_pickup__lt=requested_return,
        requested_return__gt=requested_start
    )
    # Exclude expired uncollected approved reservations
    valid_ids = [
        res.pk for res in qs
        if not (res.status == StudentReservation.Status.APPROVED and res.is_pickup_expired)
    ]
    return StudentReservation.objects.filter(pk__in=valid_ids)


def request_borrowing(
    asset,
    borrower,
    purpose,
    requested_start,
    requested_return,
    remarks='',
    created_by=None,
    request=None
):
    """
    Submits a temporary equipment borrowing request.
    Validates date range, asset availability, and reservation conflicts.
    Does NOT alter canonical asset status (remains AVAILABLE).
    """
    # 1. Date/time validation
    if not requested_start or not requested_return:
        raise ValidationError("Both requested start and expected return times are required.")
    if requested_start >= requested_return:
        raise ValidationError("Expected return time must be strictly after the start time.")

    # 2. Asset eligibility validation
    if asset.status != Asset.Status.AVAILABLE:
        raise ValidationError(
            f"Asset '{asset.asset_code}' cannot be borrowed because its status is "
            f"'{asset.get_status_display()}'. Only AVAILABLE equipment may be requested."
        )

    # 3. Long-term assignment and transfer protection
    if asset.assignments.filter(status='ACTIVE').exists():
        raise ValidationError(
            f"Asset '{asset.asset_code}' is currently assigned under ongoing employee accountability and cannot be borrowed."
        )
    if asset.transfers.filter(status__in=['PENDING', 'APPROVED']).exists():
        raise ValidationError(
            f"Asset '{asset.asset_code}' has an active relocation transfer pending and cannot be reserved."
        )

    # 4. Check for active physical releases
    if AssetBorrowing.objects.filter(
        asset=asset,
        status__in=[AssetBorrowing.Status.RELEASED, AssetBorrowing.Status.OVERDUE]
    ).exists():
        raise ValidationError(
            f"Asset '{asset.asset_code}' is currently physically released on loan and cannot be reserved."
        )

    # 5. Overlapping reservation conflict check
    conflicts = check_reservation_conflict(asset, requested_start, requested_return)
    if conflicts.exists():
        c = conflicts.first()
        raise ValidationError(
            f"Reservation conflict: Asset '{asset.asset_code}' is already reserved/borrowed by "
            f"{c.borrower.full_name} from {c.requested_start:%Y-%m-%d %H:%M} to {c.requested_return:%Y-%m-%d %H:%M}."
        )

    # 5b. Overlapping student reservation check
    student_conflicts = check_student_reservation_conflict(asset, requested_start, requested_return)
    if student_conflicts.exists():
        sc = student_conflicts.first()
        if sc.status == 'RETURNED_TO_GUARD':
            raise ValidationError(
                f"Asset '{asset.asset_code}' was returned to a security guard and is awaiting CBA inspection."
            )
        raise ValidationError(
            f"Reservation conflict: Asset '{asset.asset_code}' is already reserved for a student "
            f"({sc.student_name} from {sc.requested_pickup:%Y-%m-%d %H:%M} to {sc.requested_return:%Y-%m-%d %H:%M})."
        )

    # 6. Borrower validation
    if not borrower.is_active:
        raise ValidationError(f"Cannot request borrowing for inactive employee '{borrower.full_name}'.")

    borrower_department = borrower.department
    if not borrower_department:
        raise ValidationError(f"Employee '{borrower.full_name}' does not have an assigned department.")

    with transaction.atomic():
        borrowing = AssetBorrowing.objects.create(
            asset=asset,
            borrower=borrower,
            borrower_department=borrower_department,
            purpose=purpose.strip(),
            requested_start=requested_start,
            requested_return=requested_return,
            status=AssetBorrowing.Status.PENDING,
            remarks=remarks.strip(),
        )

        user_for_log = created_by or getattr(borrower, 'user', None)
        log_action(
            user=user_for_log,
            action='BORROW_REQUEST_CREATED',
            instance=borrowing,
            changes={
                'asset_code': asset.asset_code,
                'borrower': borrower.full_name,
                'department': borrower_department.name,
                'requested_start': requested_start.isoformat(),
                'requested_return': requested_return.isoformat(),
                'purpose': purpose.strip(),
            },
            request=request
        )

    return borrowing


def approve_borrowing(borrowing, reviewed_by, remarks='', request=None):
    """
    Authorizes a pending borrowing request (reserves the asset).
    Row-locks borrowing and asset records, re-verifies conflict absence.
    Asset status remains AVAILABLE until physical release.
    """
    with transaction.atomic():
        locked_borrowing = AssetBorrowing.objects.select_for_update().select_related('asset', 'borrower').get(pk=borrowing.pk)
        locked_asset = Asset.objects.select_for_update().get(pk=locked_borrowing.asset.pk)

        if locked_borrowing.status != AssetBorrowing.Status.PENDING:
            raise ValidationError(
                f"Cannot approve request #{locked_borrowing.pk}: current status is '{locked_borrowing.get_status_display()}'. Only PENDING requests may be approved."
            )

        if locked_asset.status != Asset.Status.AVAILABLE:
            raise ValidationError(
                f"Cannot approve request: Asset '{locked_asset.asset_code}' is currently '{locked_asset.get_status_display()}'."
            )

        if locked_asset.assignments.filter(status='ACTIVE').exists():
            raise ValidationError(
                f"Cannot approve request: Asset '{locked_asset.asset_code}' has an active accountability assignment."
            )

        if locked_asset.transfers.filter(status__in=['PENDING', 'APPROVED']).exists():
            raise ValidationError(
                f"Cannot approve request: Asset '{locked_asset.asset_code}' has an open relocation transfer."
            )

        conflicts = check_reservation_conflict(
            locked_asset,
            locked_borrowing.requested_start,
            locked_borrowing.requested_return,
            exclude_borrowing_id=locked_borrowing.pk
        )
        if conflicts.exists():
            c = conflicts.first()
            raise ValidationError(
                f"Cannot approve: Asset '{locked_asset.asset_code}' conflicts with an existing reservation by "
                f"{c.borrower.full_name} ({c.requested_start:%Y-%m-%d %H:%M} to {c.requested_return:%Y-%m-%d %H:%M})."
            )

        student_conflicts = check_student_reservation_conflict(
            locked_asset,
            locked_borrowing.requested_start,
            locked_borrowing.requested_return
        )
        if student_conflicts.exists():
            sc = student_conflicts.first()
            if sc.status == 'RETURNED_TO_GUARD':
                raise ValidationError(
                    f"Cannot approve: Asset '{locked_asset.asset_code}' was returned to a security guard and is awaiting CBA inspection."
                )
            raise ValidationError(
                f"Cannot approve: Asset '{locked_asset.asset_code}' conflicts with an existing student reservation by "
                f"{sc.student_name} ({sc.requested_pickup:%Y-%m-%d %H:%M} to {sc.requested_return:%Y-%m-%d %H:%M})."
            )

        locked_borrowing.status = AssetBorrowing.Status.APPROVED
        locked_borrowing.reviewed_by = reviewed_by
        locked_borrowing.reviewed_at = timezone.now()
        if remarks.strip():
            existing_remarks = locked_borrowing.remarks
            locked_borrowing.remarks = f"{existing_remarks}\nApproval note: {remarks.strip()}".strip() if existing_remarks else f"Approval note: {remarks.strip()}"
        locked_borrowing.save()

        log_action(
            user=reviewed_by,
            action='BORROW_REQUEST_APPROVED',
            instance=locked_borrowing,
            changes={
                'asset_code': locked_asset.asset_code,
                'borrower': locked_borrowing.borrower.full_name,
                'approved_at': locked_borrowing.reviewed_at.isoformat(),
            },
            request=request
        )

    return locked_borrowing


def reject_borrowing(borrowing, reviewed_by, rejection_reason, request=None):
    """
    Rejects a pending borrowing request with an explanatory reason.
    Row-locks borrowing record and preserves historical trail.
    """
    if not rejection_reason or not rejection_reason.strip():
        raise ValidationError("A rejection reason must be provided.")

    with transaction.atomic():
        locked_borrowing = AssetBorrowing.objects.select_for_update().select_related('asset').get(pk=borrowing.pk)

        if locked_borrowing.status != AssetBorrowing.Status.PENDING:
            raise ValidationError(
                f"Cannot reject request #{locked_borrowing.pk}: current status is '{locked_borrowing.get_status_display()}'. Only PENDING requests may be rejected."
            )

        locked_borrowing.status = AssetBorrowing.Status.REJECTED
        locked_borrowing.reviewed_by = reviewed_by
        locked_borrowing.reviewed_at = timezone.now()
        locked_borrowing.rejection_reason = rejection_reason.strip()
        locked_borrowing.save()

        log_action(
            user=reviewed_by,
            action='BORROW_REQUEST_REJECTED',
            instance=locked_borrowing,
            changes={
                'asset_code': locked_borrowing.asset.asset_code,
                'rejection_reason': rejection_reason.strip(),
            },
            request=request
        )

    return locked_borrowing


def cancel_borrowing(borrowing, cancelled_by, reason='', request=None):
    """
    Cancels a pending or approved borrowing reservation.
    Faculty can cancel only their own PENDING requests.
    Admins can administratively cancel PENDING or APPROVED reservations.
    Released equipment cannot be cancelled; it must be returned.
    """
    with transaction.atomic():
        locked_borrowing = AssetBorrowing.objects.select_for_update().select_related('asset', 'borrower').get(pk=borrowing.pk)

        if locked_borrowing.status in [AssetBorrowing.Status.RELEASED, AssetBorrowing.Status.OVERDUE]:
            raise ValidationError(
                "A physically released equipment loan cannot be cancelled. The equipment must be formally returned."
            )

        if locked_borrowing.status not in [AssetBorrowing.Status.PENDING, AssetBorrowing.Status.APPROVED]:
            raise ValidationError(
                f"Cannot cancel borrowing #{locked_borrowing.pk}: current status is already '{locked_borrowing.get_status_display()}'."
            )

        # Faculty security check: only own pending requests
        is_admin = getattr(cancelled_by, 'is_admin', False) or getattr(cancelled_by, 'role', '') == 'ADMIN'
        if not is_admin:
            if locked_borrowing.borrower.user != cancelled_by:
                raise ValidationError("You do not have permission to cancel another employee's borrowing request.")
            if locked_borrowing.status != AssetBorrowing.Status.PENDING:
                raise ValidationError("Approved reservations cannot be self-cancelled. Please contact the Property Custodian.")

        locked_borrowing.status = AssetBorrowing.Status.CANCELLED
        if reason.strip():
            existing_remarks = locked_borrowing.remarks
            locked_borrowing.remarks = f"{existing_remarks}\nCancellation: {reason.strip()}".strip() if existing_remarks else f"Cancellation: {reason.strip()}"
        locked_borrowing.save()

        log_action(
            user=cancelled_by,
            action='BORROW_REQUEST_CANCELLED',
            instance=locked_borrowing,
            changes={
                'asset_code': locked_borrowing.asset.asset_code,
                'cancelled_by': cancelled_by.username,
                'reason': reason.strip(),
            },
            request=request
        )

    return locked_borrowing


def release_asset(borrowing, released_by, condition_at_release=None, remarks='', request=None):
    """
    Physically releases the equipment to the borrower.
    Transitions borrowing from APPROVED to RELEASED.
    Transitions asset status from AVAILABLE to BORROWED.
    Snapshots release condition.
    """
    with transaction.atomic():
        locked_borrowing = AssetBorrowing.objects.select_for_update().select_related('asset', 'borrower').get(pk=borrowing.pk)
        locked_asset = Asset.objects.select_for_update().get(pk=locked_borrowing.asset.pk)

        if locked_borrowing.status != AssetBorrowing.Status.APPROVED:
            raise ValidationError(
                f"Cannot release equipment: borrowing #{locked_borrowing.pk} status is "
                f"'{locked_borrowing.get_status_display()}'. Equipment must be in APPROVED status before release."
            )

        if locked_asset.status != Asset.Status.AVAILABLE:
            raise ValidationError(
                f"Cannot release: Asset '{locked_asset.asset_code}' is currently '{locked_asset.get_status_display()}'. Only AVAILABLE assets may be released."
            )

        # Ensure no active released loan exists on this asset
        if AssetBorrowing.objects.filter(
            asset=locked_asset,
            status__in=[AssetBorrowing.Status.RELEASED, AssetBorrowing.Status.OVERDUE]
        ).exclude(pk=locked_borrowing.pk).exists():
            raise ValidationError(
                f"Asset '{locked_asset.asset_code}' is already recorded as physically released on another active borrowing."
            )

        from apps.student_reservations.models import StudentReservation
        if StudentReservation.objects.filter(
            asset=locked_asset,
            status__in=[StudentReservation.Status.RELEASED, StudentReservation.Status.RETURNED_TO_GUARD]
        ).exists():
            raise ValidationError(
                f"Asset '{locked_asset.asset_code}' is currently physically released on a student reservation."
            )

        cond = condition_at_release or locked_asset.condition
        locked_borrowing.status = AssetBorrowing.Status.RELEASED
        locked_borrowing.released_by = released_by
        locked_borrowing.released_at = timezone.now()
        locked_borrowing.condition_at_release = cond
        if remarks.strip():
            existing_remarks = locked_borrowing.remarks
            locked_borrowing.remarks = f"{existing_remarks}\nRelease note: {remarks.strip()}".strip() if existing_remarks else remarks.strip()
        locked_borrowing.save()

        locked_asset.status = Asset.Status.BORROWED
        locked_asset.save()

        log_action(
            user=released_by,
            action='ASSET_BORROW_RELEASED',
            instance=locked_borrowing,
            changes={
                'asset_code': locked_asset.asset_code,
                'borrower': locked_borrowing.borrower.full_name,
                'released_at': locked_borrowing.released_at.isoformat(),
                'condition_at_release': cond,
            },
            request=request
        )

    return locked_borrowing


def return_borrowed_asset(borrowing, returned_to, condition_at_return, return_remarks='', request=None):
    """
    Processes the physical return and inspection of borrowed equipment.
    Transitions borrowing from RELEASED/OVERDUE to RETURNED.
    Updates asset condition.
    Safely transitions asset status:
    - Normal (NEW, GOOD, FAIR, POOR) -> AVAILABLE
    - UNSERVICEABLE -> DAMAGED
    """
    if not condition_at_return or condition_at_return not in Asset.Condition.values:
        raise ValidationError("A valid condition inspection rating must be recorded upon return.")

    with transaction.atomic():
        locked_borrowing = AssetBorrowing.objects.select_for_update().select_related('asset', 'borrower').get(pk=borrowing.pk)
        locked_asset = Asset.objects.select_for_update().get(pk=locked_borrowing.asset.pk)

        if locked_borrowing.status not in [AssetBorrowing.Status.RELEASED, AssetBorrowing.Status.OVERDUE]:
            raise ValidationError(
                f"Cannot process return for borrowing #{locked_borrowing.pk}: current status is "
                f"'{locked_borrowing.get_status_display()}'. Only currently RELEASED or OVERDUE loans can be returned."
            )

        now = timezone.now()
        locked_borrowing.status = AssetBorrowing.Status.RETURNED
        locked_borrowing.returned_to = returned_to
        locked_borrowing.returned_at = now
        locked_borrowing.condition_at_return = condition_at_return
        locked_borrowing.return_remarks = return_remarks.strip()
        locked_borrowing.save()

        # Update physical asset condition
        locked_asset.condition = condition_at_return

        # Determine safe operational asset status
        if condition_at_return == Asset.Condition.UNSERVICEABLE:
            locked_asset.status = Asset.Status.DAMAGED
        else:
            locked_asset.status = Asset.Status.AVAILABLE
        locked_asset.save()

        log_action(
            user=returned_to,
            action='ASSET_BORROW_RETURNED',
            instance=locked_borrowing,
            changes={
                'asset_code': locked_asset.asset_code,
                'returned_at': now.isoformat(),
                'condition_at_return': condition_at_return,
                'resulting_asset_status': locked_asset.status,
                'return_remarks': return_remarks.strip(),
            },
            request=request
        )

    return locked_borrowing


def refresh_overdue_status(borrowing=None):
    """
    Safely synchronizes persisted OVERDUE status for released loans that passed their return deadline.
    Returns the count of records updated.
    """
    now = timezone.now()
    if borrowing:
        if (
            borrowing.status == AssetBorrowing.Status.RELEASED
            and borrowing.returned_at is None
            and now > borrowing.requested_return
        ):
            borrowing.status = AssetBorrowing.Status.OVERDUE
            borrowing.save(update_fields=['status'])
            return 1
        return 0

    qs = AssetBorrowing.objects.filter(
        status=AssetBorrowing.Status.RELEASED,
        returned_at__isnull=True,
        requested_return__lt=now
    )
    count = qs.update(status=AssetBorrowing.Status.OVERDUE)
    return count
