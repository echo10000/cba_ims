from datetime import timedelta
from django.db import transaction
from django.core.exceptions import ValidationError, PermissionDenied
from django.utils import timezone
from django.db.models import Q

from apps.inventory.models import Asset, AssetCategory
from apps.borrowing.models import AssetBorrowing
from apps.audit.utils import log_action
from .models import StudentReservation


# ==============================================================================
# AUTHORIZATION HELPER
# ==============================================================================

def check_custodian_permission(user):
    """
    Enforces Administrator / Property Custodian authorization for office actions.
    Students, faculty, deans, and department chairs cannot perform custodian actions.
    """
    if not user or not user.is_authenticated:
        raise PermissionDenied("Authentication required to perform office actions.")
    is_admin = getattr(user, 'is_admin', False) or getattr(user, 'role', '') == 'ADMIN'
    if not is_admin:
        raise PermissionDenied(
            "Only Property Custodians / Administrators have authority to perform student reservation office actions."
        )
    return True


# ==============================================================================
# LAZY EXPIRATION (NO-SHOW) UTILITY
# ==============================================================================

def auto_expire_uncollected_reservations():
    """
    Lazily transitions expired uncollected APPROVED student reservations to NO_SHOW.
    Ensures that reservations passing their 15-minute (or extended) grace period without
    equipment release immediately free up inventory without requiring an external background daemon.
    """
    now = timezone.now()
    approved_qs = StudentReservation.objects.filter(
        status=StudentReservation.Status.APPROVED
    ).select_related('asset')

    expired_pks = []
    for res in approved_qs:
        if res.pickup_deadline and now > res.pickup_deadline:
            expired_pks.append(res.pk)

    if expired_pks:
        with transaction.atomic():
            StudentReservation.objects.filter(
                pk__in=expired_pks,
                status=StudentReservation.Status.APPROVED
            ).update(status=StudentReservation.Status.NO_SHOW)
    return len(expired_pks)


# ==============================================================================
# AVAILABILITY CHECKING SERVICE
# ==============================================================================

def get_reservable_categories():
    """
    Returns active AssetCategories marked as reservable for students.
    Excludes categories that are deactivated or non-reservable.
    """
    return AssetCategory.objects.filter(
        is_active=True,
        is_reservable=True
    )


def get_reservable_assets(category=None):
    """
    Returns physical assets that are active, reservable, and in reservable categories.
    Excludes non-reservable or disposed/lost assets from the student catalog.
    """
    qs = Asset.objects.filter(
        is_reservable=True,
        category__is_active=True,
        category__is_reservable=True
    ).exclude(
        status__in=[
            Asset.Status.DISPOSED,
            Asset.Status.LOST,
            Asset.Status.DAMAGED,
            Asset.Status.MAINTENANCE,
            Asset.Status.TRANSFERRED
        ]
    )
    if category:
        qs = qs.filter(category=category)
    return qs


def check_asset_availability(asset, requested_pickup, requested_return, exclude_student_reservation_id=None, exclude_borrowing_id=None):
    """
    Core reusable availability verification for a specific Asset in [requested_pickup, requested_return].
    Returns (is_available: bool, conflict_reason: str).
    Accounts for:
    1. Operational eligibility (status, is_reservable flags)
    2. Permanent / ongoing faculty assignments (AssetAssignment)
    3. Open relocation transfers (AssetTransfer)
    4. Guard-returned assets awaiting CBA inspection (StudentReservation: RETURNED_TO_GUARD)
    5. Active physical releases and faculty borrowings (AssetBorrowing)
    6. Approved and active student reservations (StudentReservation)
       (Treats expired uncollected approved reservations as non-blocking)
    """
    auto_expire_uncollected_reservations()
    now = timezone.now()

    # 1. Date range validation
    if not requested_pickup or not requested_return:
        return False, "Both requested pickup and return datetimes are required."
    if requested_pickup >= requested_return:
        return False, "Return time must be strictly after pickup time."

    # 2. Operational eligibility & reservable flags
    if not getattr(asset, 'is_reservable', True):
        return False, f"Asset '{asset.asset_code}' is marked as non-reservable."
    if not getattr(asset.category, 'is_reservable', True):
        return False, f"Equipment category '{asset.category.name}' is non-reservable."
    if not getattr(asset.category, 'is_active', True):
        return False, f"Equipment category '{asset.category.name}' is deactivated."

    if asset.status in [
        Asset.Status.MAINTENANCE,
        Asset.Status.DAMAGED,
        Asset.Status.LOST,
        Asset.Status.DISPOSED,
        Asset.Status.TRANSFERRED
    ]:
        return False, f"Asset '{asset.asset_code}' is currently unavailable (Status: {asset.get_status_display()})."

    # 3. Permanent employee assignment protection
    if asset.assignments.filter(status='ACTIVE').exists():
        return False, f"Asset '{asset.asset_code}' is assigned under ongoing employee accountability."

    # 4. Open relocation transfer protection
    if asset.transfers.filter(status__in=['PENDING', 'APPROVED']).exists():
        return False, f"Asset '{asset.asset_code}' has an open relocation transfer pending."

    # 5. Guard return awaiting CBA inspection protection
    # "Ensure an asset returned to a guard is unavailable until inspected."
    guard_returns = StudentReservation.objects.filter(
        asset=asset,
        status=StudentReservation.Status.RETURNED_TO_GUARD
    )
    if exclude_student_reservation_id:
        guard_returns = guard_returns.exclude(pk=exclude_student_reservation_id)
    if guard_returns.exists():
        return False, f"Asset '{asset.asset_code}' was returned to a security guard and is awaiting CBA inspection."

    # 6. Physical release right now check
    # If the requested start is immediate or in the past, and equipment is currently released or overdue on loan:
    if requested_pickup <= now:
        active_loans = AssetBorrowing.objects.filter(
            asset=asset,
            status__in=[AssetBorrowing.Status.RELEASED, AssetBorrowing.Status.OVERDUE]
        )
        if exclude_borrowing_id:
            active_loans = active_loans.exclude(pk=exclude_borrowing_id)
        if active_loans.exists():
            return False, f"Asset '{asset.asset_code}' is currently physically released on loan."

        active_student_releases = StudentReservation.objects.filter(
            asset=asset,
            status=StudentReservation.Status.RELEASED
        )
        if exclude_student_reservation_id:
            active_student_releases = active_student_releases.exclude(pk=exclude_student_reservation_id)
        if active_student_releases.exists():
            return False, f"Asset '{asset.asset_code}' is currently physically released to another student."

    # 7. Conflicting faculty borrowings
    conflicting_borrowings = AssetBorrowing.objects.filter(
        asset=asset,
        status__in=[
            AssetBorrowing.Status.APPROVED,
            AssetBorrowing.Status.RELEASED,
            AssetBorrowing.Status.OVERDUE
        ],
        requested_start__lt=requested_return,
        requested_return__gt=requested_pickup
    )
    if exclude_borrowing_id:
        conflicting_borrowings = conflicting_borrowings.exclude(pk=exclude_borrowing_id)
    if conflicting_borrowings.exists():
        c = conflicting_borrowings.first()
        return False, (
            f"Asset '{asset.asset_code}' has an overlapping faculty borrowing by {c.borrower.full_name} "
            f"({c.requested_start:%Y-%m-%d %H:%M} to {c.requested_return:%Y-%m-%d %H:%M})."
        )

    # 8. Conflicting student reservations
    # Exclude expired uncollected reservations (past grace period)
    conflicting_student_res = StudentReservation.objects.filter(
        asset=asset,
        status__in=[
            StudentReservation.Status.APPROVED,
            StudentReservation.Status.RELEASED
        ],
        requested_pickup__lt=requested_return,
        requested_return__gt=requested_pickup
    )
    if exclude_student_reservation_id:
        conflicting_student_res = conflicting_student_res.exclude(pk=exclude_student_reservation_id)

    # Filter out any uncollected approved reservations whose grace period has expired
    for res in conflicting_student_res:
        if res.status == StudentReservation.Status.APPROVED and res.is_pickup_expired:
            continue
        return False, (
            f"Asset '{asset.asset_code}' has an overlapping approved student reservation for {res.student_name} "
            f"({res.requested_pickup:%Y-%m-%d %H:%M} to {res.requested_return:%Y-%m-%d %H:%M})."
        )

    return True, "Available"


def get_available_assets_for_category(category, requested_pickup, requested_return, equipment_type=None, exclude_student_reservation_id=None):
    """
    Returns list of eligible Asset objects in the specified category that are fully available
    for the requested [requested_pickup, requested_return] interval.
    Enables Property Custodians to allocate specific units (e.g. one of 3 projectors).
    """
    auto_expire_uncollected_reservations()
    eligible_assets = get_reservable_assets(category=category)
    if equipment_type:
        # Match equipment_type in item_name or model or category name
        eligible_assets = eligible_assets.filter(
            Q(item_name__icontains=equipment_type) |
            Q(model__icontains=equipment_type) |
            Q(category__name__icontains=equipment_type)
        )

    available = []
    for asset in eligible_assets:
        is_avail, _ = check_asset_availability(
            asset=asset,
            requested_pickup=requested_pickup,
            requested_return=requested_return,
            exclude_student_reservation_id=exclude_student_reservation_id
        )
        if is_avail:
            available.append(asset)
    return available


# ==============================================================================
# SERVICE-LAYER BACKEND OPERATIONS
# ==============================================================================

def submit_reservation(
    student_id,
    student_name,
    course_year_section,
    email,
    contact_number,
    category,
    requested_pickup,
    requested_return,
    purpose,
    room_venue='',
    equipment_type='',
    remarks='',
    created_by=None,
    request=None
):
    """
    Submits a new student equipment reservation request.
    Publicly accessible; students do not need accounts.
    Captures student metadata, generates unguessable lookup token.
    Pending requests do not block equipment until Custodian approves.
    """
    auto_expire_uncollected_reservations()

    if request:
        from .security import check_submission_rate_limit
        check_submission_rate_limit(request, student_id)

    # 1. Input hygiene & validation
    student_id = str(student_id).strip()
    student_name = str(student_name).strip()
    course_year_section = str(course_year_section).strip()
    email = str(email).strip().lower()
    contact_number = str(contact_number).strip()
    purpose = str(purpose).strip()
    room_venue = str(room_venue).strip()
    equipment_type = str(equipment_type).strip()

    if not student_id:
        raise ValidationError({'student_id': "Student ID number is required."})
    if not student_name:
        raise ValidationError({'student_name': "Student full name is required."})
    if not course_year_section:
        raise ValidationError({'course_year_section': "Course, year, and section are required."})
    if not email:
        raise ValidationError({'email': "Valid email address is required."})
    if not contact_number:
        raise ValidationError({'contact_number': "Contact number is required."})
    if not purpose:
        raise ValidationError({'purpose': "Official purpose is required."})
    if not requested_pickup or not requested_return:
        raise ValidationError("Both requested pickup and return datetimes are required.")
    if requested_pickup >= requested_return:
        raise ValidationError({'requested_return': "Requested return time must be strictly after pickup time."})

    now = timezone.now()
    if requested_pickup < now - timedelta(minutes=10):
        raise ValidationError({'requested_pickup': "Requested pickup time cannot be in the past."})

    # Validate category reservability
    if not getattr(category, 'is_active', True) or not getattr(category, 'is_reservable', True):
        raise ValidationError({'category': f"Category '{category.name}' is not currently available for reservations."})

    # Basic verification: Ensure at least one asset exists for this category
    total_assets = get_reservable_assets(category=category)
    if equipment_type:
        total_assets = total_assets.filter(
            Q(item_name__icontains=equipment_type) |
            Q(model__icontains=equipment_type)
        )
    if not total_assets.exists():
        raise ValidationError({'category': f"No reservable equipment currently registered under category '{category.name}'."})

    with transaction.atomic():
        reservation = StudentReservation(
            student_id=student_id,
            student_name=student_name,
            course_year_section=course_year_section,
            email=email,
            contact_number=contact_number,
            category=category,
            equipment_type=equipment_type,
            requested_pickup=requested_pickup,
            requested_return=requested_return,
            purpose=purpose,
            room_venue=room_venue,
            status=StudentReservation.Status.PENDING,
            remarks=remarks.strip(),
        )
        reservation.full_clean()
        reservation.save()

        log_action(
            user=created_by,
            action='STUDENT_RESERVATION_SUBMITTED',
            instance=reservation,
            changes={
                'student_id': student_id,
                'student_name': student_name,
                'category': category.name,
                'equipment_type': equipment_type,
                'requested_pickup': requested_pickup.isoformat(),
                'requested_return': requested_return.isoformat(),
                'lookup_token': reservation.lookup_token,
            },
            request=request
        )

    return reservation


def approve_reservation(reservation, asset, reviewed_by, grace_period_minutes=15, remarks='', request=None):
    """
    Authorizes a pending student reservation and allocates a specific physical Asset.
    Acquires database row locks on reservation and asset records to guarantee no double-booking
    even under simultaneous concurrent approvals by multiple staff members.
    Requires Custodian authorization.
    """
    check_custodian_permission(reviewed_by)
    auto_expire_uncollected_reservations()

    with transaction.atomic():
        # Row-lock reservation and asset to prevent race conditions
        locked_reservation = StudentReservation.objects.select_for_update().select_related('category').get(pk=reservation.pk)
        locked_asset = Asset.objects.select_for_update().select_related('category').get(pk=asset.pk)

        if locked_reservation.status != StudentReservation.Status.PENDING:
            raise ValidationError(
                f"Cannot approve reservation #{locked_reservation.pk}: status is "
                f"'{locked_reservation.get_status_display()}'. Only PENDING requests may be approved."
            )

        if locked_asset.category_id != locked_reservation.category_id:
            raise ValidationError(
                f"Asset '{locked_asset.asset_code}' ({locked_asset.category.name}) does not match "
                f"requested category '{locked_reservation.category.name}'."
            )

        # Check availability of the selected asset for the requested interval
        is_avail, reason = check_asset_availability(
            asset=locked_asset,
            requested_pickup=locked_reservation.requested_pickup,
            requested_return=locked_reservation.requested_return,
            exclude_student_reservation_id=locked_reservation.pk
        )
        if not is_avail:
            raise ValidationError(f"Cannot allocate asset '{locked_asset.asset_code}': {reason}")

        locked_reservation.asset = locked_asset
        locked_reservation.status = StudentReservation.Status.APPROVED
        locked_reservation.reviewed_by = reviewed_by
        locked_reservation.reviewed_at = timezone.now()
        locked_reservation.grace_period_minutes = grace_period_minutes
        if remarks.strip():
            existing = locked_reservation.remarks
            locked_reservation.remarks = f"{existing}\nApproval: {remarks.strip()}".strip() if existing else f"Approval: {remarks.strip()}"
        locked_reservation.save()

        log_action(
            user=reviewed_by,
            action='STUDENT_RESERVATION_APPROVED',
            instance=locked_reservation,
            changes={
                'asset_code': locked_asset.asset_code,
                'student_name': locked_reservation.student_name,
                'approved_at': locked_reservation.reviewed_at.isoformat(),
                'grace_period_minutes': grace_period_minutes,
            },
            request=request
        )

    return locked_reservation


def reject_reservation(reservation, reviewed_by, rejection_reason, request=None):
    """
    Rejects a pending student reservation with documented reason.
    Requires Custodian authorization.
    """
    check_custodian_permission(reviewed_by)

    if not rejection_reason or not rejection_reason.strip():
        raise ValidationError("A rejection explanation reason is required.")

    with transaction.atomic():
        locked_res = StudentReservation.objects.select_for_update().get(pk=reservation.pk)

        if locked_res.status != StudentReservation.Status.PENDING:
            raise ValidationError(
                f"Cannot reject reservation #{locked_res.pk}: status is "
                f"'{locked_res.get_status_display()}'. Only PENDING requests may be rejected."
            )

        locked_res.status = StudentReservation.Status.REJECTED
        locked_res.reviewed_by = reviewed_by
        locked_res.reviewed_at = timezone.now()
        locked_res.rejection_reason = rejection_reason.strip()
        locked_res.save()

        log_action(
            user=reviewed_by,
            action='STUDENT_RESERVATION_REJECTED',
            instance=locked_res,
            changes={
                'student_name': locked_res.student_name,
                'rejection_reason': rejection_reason.strip(),
            },
            request=request
        )

    return locked_res


def cancel_reservation(reservation, cancelled_by=None, lookup_token=None, reason='', request=None):
    """
    Cancels a PENDING or APPROVED student reservation.
    Allowed by:
    1. Student providing their private lookup_token (self-cancellation prior to release).
    2. Property Custodian / Administrator.
    Released equipment CANNOT be cancelled; it must be returned.
    """
    with transaction.atomic():
        locked_res = StudentReservation.objects.select_for_update().get(pk=reservation.pk)

        if locked_res.status in [
            StudentReservation.Status.RELEASED,
            StudentReservation.Status.RETURNED,
            StudentReservation.Status.RETURNED_TO_GUARD
        ]:
            raise ValidationError(
                f"Cannot cancel reservation in '{locked_res.get_status_display()}' status. "
                f"Equipment must be physically returned."
            )

        if locked_res.status not in [StudentReservation.Status.PENDING, StudentReservation.Status.APPROVED]:
            raise ValidationError(
                f"Cannot cancel reservation: status is already '{locked_res.get_status_display()}'."
            )

        # Verification of identity/token
        is_custodian = cancelled_by and (getattr(cancelled_by, 'is_admin', False) or getattr(cancelled_by, 'role', '') == 'ADMIN')
        if not is_custodian:
            if not lookup_token or lookup_token != locked_res.lookup_token:
                raise PermissionDenied("Valid lookup token or Property Custodian authorization required to cancel reservation.")

        locked_res.status = StudentReservation.Status.CANCELLED
        if reason.strip():
            existing = locked_res.remarks
            locked_res.remarks = f"{existing}\nCancellation: {reason.strip()}".strip() if existing else f"Cancellation: {reason.strip()}"
        locked_res.save()

        log_action(
            user=cancelled_by,
            action='STUDENT_RESERVATION_CANCELLED',
            instance=locked_res,
            changes={
                'cancelled_by': cancelled_by.username if cancelled_by else 'Student (Token)',
                'reason': reason.strip(),
            },
            request=request
        )

    return locked_res


def extend_grace_period(reservation, additional_minutes=15, extended_by=None, reason='', request=None):
    """
    Extends the 15-minute pickup grace period for an APPROVED reservation.
    Requires Property Custodian authorization.
    """
    check_custodian_permission(extended_by)

    if additional_minutes <= 0:
        raise ValidationError("Additional minutes must be greater than zero.")

    with transaction.atomic():
        locked_res = StudentReservation.objects.select_for_update().get(pk=reservation.pk)

        if locked_res.status != StudentReservation.Status.APPROVED:
            raise ValidationError(
                f"Cannot extend grace period: reservation status is '{locked_res.get_status_display()}'. "
                f"Grace periods can only be extended for APPROVED reservations."
            )

        locked_res.grace_period_minutes += additional_minutes
        if reason.strip():
            existing = locked_res.remarks
            locked_res.remarks = f"{existing}\nGrace extended +{additional_minutes}m: {reason.strip()}".strip() if existing else f"Grace extended +{additional_minutes}m: {reason.strip()}"
        locked_res.save()

        log_action(
            user=extended_by,
            action='STUDENT_RESERVATION_GRACE_EXTENDED',
            instance=locked_res,
            changes={
                'new_grace_minutes': locked_res.grace_period_minutes,
                'additional_minutes': additional_minutes,
                'extended_deadline': locked_res.pickup_deadline.isoformat() if locked_res.pickup_deadline else None,
            },
            request=request
        )

    return locked_res


def record_no_show(reservation, recorded_by=None, reason='', request=None):
    """
    Records a NO_SHOW for an approved reservation when the student failed to claim equipment
    within the pickup grace period. Frees up the allocated asset.
    Requires Custodian authorization (or can be triggered when grace period expires).
    """
    if recorded_by:
        check_custodian_permission(recorded_by)

    with transaction.atomic():
        locked_res = StudentReservation.objects.select_for_update().get(pk=reservation.pk)

        if locked_res.status != StudentReservation.Status.APPROVED:
            raise ValidationError(
                f"Cannot record no-show: reservation status is '{locked_res.get_status_display()}'. "
                f"Only APPROVED reservations can be marked as No-Show."
            )

        now = timezone.now()
        # If recorded by staff, they can record it at or after pickup time
        if not locked_res.is_pickup_expired and recorded_by is None:
            raise ValidationError(
                f"Pickup deadline has not yet passed. Deadline is {locked_res.pickup_deadline:%Y-%m-%d %H:%M}."
            )

        locked_res.status = StudentReservation.Status.NO_SHOW
        if reason.strip():
            existing = locked_res.remarks
            locked_res.remarks = f"{existing}\nNo-Show: {reason.strip()}".strip() if existing else f"No-Show: {reason.strip()}"
        locked_res.save()

        log_action(
            user=recorded_by,
            action='STUDENT_RESERVATION_NO_SHOW',
            instance=locked_res,
            changes={
                'recorded_by': recorded_by.username if recorded_by else 'System (Automatic)',
                'reason': reason.strip(),
            },
            request=request
        )

    return locked_res


def release_equipment(reservation, released_by, condition_at_release=None, remarks='', request=None):
    """
    Physically releases the equipment to the student and records physical school ID deposit.
    Business rules:
    - Student identity is physically checked using their original school ID at pickup.
    - Students leave their physical school ID at the CBA office while borrowing equipment.
    - Transitions reservation status: APPROVED -> RELEASED.
    - Transitions asset status: AVAILABLE -> BORROWED.
    - Requires Custodian authorization.
    """
    check_custodian_permission(released_by)
    auto_expire_uncollected_reservations()

    with transaction.atomic():
        locked_res = StudentReservation.objects.select_for_update().select_related('asset').get(pk=reservation.pk)

        if locked_res.status != StudentReservation.Status.APPROVED:
            raise ValidationError(
                f"Cannot release equipment: reservation status is '{locked_res.get_status_display()}'. "
                f"Equipment must be in APPROVED status before release."
            )

        if not locked_res.asset:
            raise ValidationError("Cannot release: No physical asset has been allocated to this reservation.")

        locked_asset = Asset.objects.select_for_update().get(pk=locked_res.asset.pk)

        # Check pickup grace deadline
        if locked_res.is_pickup_expired:
            raise ValidationError(
                f"Pickup grace period expired at {locked_res.pickup_deadline:%Y-%m-%d %H:%M}. "
                f"Please extend the grace period before releasing."
            )

        if locked_asset.status != Asset.Status.AVAILABLE:
            raise ValidationError(
                f"Cannot release: Asset '{locked_asset.asset_code}' is currently '{locked_asset.get_status_display()}'. "
                f"Only AVAILABLE assets can be physically released."
            )

        # Ensure no other active release exists on this asset
        if StudentReservation.objects.filter(
            asset=locked_asset,
            status__in=[StudentReservation.Status.RELEASED, StudentReservation.Status.RETURNED_TO_GUARD]
        ).exclude(pk=locked_res.pk).exists():
            raise ValidationError(
                f"Asset '{locked_asset.asset_code}' is already recorded as physically released on another reservation."
            )

        if AssetBorrowing.objects.filter(
            asset=locked_asset,
            status__in=[AssetBorrowing.Status.RELEASED, AssetBorrowing.Status.OVERDUE]
        ).exists():
            raise ValidationError(
                f"Asset '{locked_asset.asset_code}' is currently released on a faculty borrowing."
            )

        now = timezone.now()
        cond = condition_at_release or locked_asset.condition

        locked_res.status = StudentReservation.Status.RELEASED
        locked_res.released_by = released_by
        locked_res.released_at = now
        locked_res.condition_at_release = cond
        # School ID custody is recorded upon physical handover
        locked_res.id_deposit_verified = True
        locked_res.id_deposited_at = now

        if remarks.strip():
            existing = locked_res.remarks
            locked_res.remarks = f"{existing}\nRelease note: {remarks.strip()}".strip() if existing else remarks.strip()
        locked_res.save()

        locked_asset.status = Asset.Status.BORROWED
        locked_asset.save()

        log_action(
            user=released_by,
            action='STUDENT_RESERVATION_RELEASED',
            instance=locked_res,
            changes={
                'asset_code': locked_asset.asset_code,
                'student_name': locked_res.student_name,
                'released_at': now.isoformat(),
                'condition_at_release': cond,
                'id_deposited': True,
            },
            request=request
        )

    return locked_res


def return_equipment_to_office(
    reservation,
    returned_to,
    condition_at_return,
    return_remarks='',
    id_collected_now=True,
    id_returned_by=None,
    request=None
):
    """
    Records direct return of equipment to the CBA office during office hours.
    Performs physical return inspection and updates asset status:
    - Normal (NEW, GOOD, FAIR, POOR) -> AVAILABLE
    - UNSERVICEABLE -> DAMAGED
    Optionally hands back deposited school ID at the same time.
    Requires Custodian authorization.
    """
    check_custodian_permission(returned_to)

    if not condition_at_return or condition_at_return not in Asset.Condition.values:
        raise ValidationError("A valid physical condition inspection rating is required upon return.")

    with transaction.atomic():
        locked_res = StudentReservation.objects.select_for_update().select_related('asset').get(pk=reservation.pk)

        if locked_res.status != StudentReservation.Status.RELEASED:
            raise ValidationError(
                f"Cannot process office return for reservation #{locked_res.pk}: status is "
                f"'{locked_res.get_status_display()}'. Only currently RELEASED loans can be returned."
            )

        locked_asset = Asset.objects.select_for_update().get(pk=locked_res.asset.pk)
        now = timezone.now()

        locked_res.status = StudentReservation.Status.RETURNED
        locked_res.returned_to = returned_to
        locked_res.returned_at = now
        locked_res.condition_at_return = condition_at_return
        locked_res.return_remarks = return_remarks.strip()

        # Handle ID retrieval if collected at return
        if id_collected_now and locked_res.id_deposit_verified and locked_res.id_collected_at is None:
            locked_res.id_collected_at = now
            locked_res.id_returned_by = id_returned_by or returned_to

        locked_res.save()

        # Update physical asset
        locked_asset.condition = condition_at_return
        if condition_at_return == Asset.Condition.UNSERVICEABLE:
            locked_asset.status = Asset.Status.DAMAGED
        else:
            locked_asset.status = Asset.Status.AVAILABLE
        locked_asset.save()

        log_action(
            user=returned_to,
            action='STUDENT_RESERVATION_RETURNED',
            instance=locked_res,
            changes={
                'asset_code': locked_asset.asset_code,
                'returned_at': now.isoformat(),
                'condition_at_return': condition_at_return,
                'resulting_asset_status': locked_asset.status,
                'id_collected': bool(locked_res.id_collected_at),
                'is_overdue': locked_res.is_overdue,
            },
            request=request
        )

    return locked_res


def record_guard_return(
    reservation,
    recorded_by,
    guard_returned_at,
    guard_handover_details='',
    remarks='',
    request=None
):
    """
    Records an after-hours return made to an authorized security guard.
    Business rules:
    - Students return equipment directly to CBA or to an authorized security guard after office hours.
    - Guard returns can be recorded by the CBA office the next working day using the actual documented handover time.
    - Guard-returned equipment remains unavailable until CBA inspects it.
    - Students collect their deposited school IDs at the CBA office (guard does NOT have the ID).
    Requires Custodian authorization.
    """
    check_custodian_permission(recorded_by)

    if not guard_returned_at:
        raise ValidationError("Documented guard handover datetime is required.")

    now = timezone.now()
    if guard_returned_at > now:
        raise ValidationError("Handover time to security guard cannot be in the future.")

    with transaction.atomic():
        locked_res = StudentReservation.objects.select_for_update().select_related('asset').get(pk=reservation.pk)

        if locked_res.status != StudentReservation.Status.RELEASED:
            raise ValidationError(
                f"Cannot record guard return for reservation #{locked_res.pk}: status is "
                f"'{locked_res.get_status_display()}'. Only currently RELEASED loans can be recorded as returned to guard."
            )

        if locked_res.released_at and guard_returned_at < locked_res.released_at:
            raise ValidationError(
                f"Guard handover time ({guard_returned_at:%Y-%m-%d %H:%M}) cannot be earlier than release time "
                f"({locked_res.released_at:%Y-%m-%d %H:%M})."
            )

        locked_res.status = StudentReservation.Status.RETURNED_TO_GUARD
        locked_res.guard_returned_at = guard_returned_at
        locked_res.guard_handover_details = guard_handover_details.strip()
        locked_res.guard_recorded_by = recorded_by
        locked_res.guard_recorded_at = now
        if remarks.strip():
            existing = locked_res.remarks
            locked_res.remarks = f"{existing}\nGuard return: {remarks.strip()}".strip() if existing else f"Guard return: {remarks.strip()}"
        locked_res.save()

        # Notice: Asset status remains BORROWED (unavailable) until CBA inspects it!
        # Physical school ID remains deposited at the CBA office.

        log_action(
            user=recorded_by,
            action='STUDENT_RESERVATION_GUARD_RETURN',
            instance=locked_res,
            changes={
                'asset_code': locked_res.asset.asset_code if locked_res.asset else '',
                'guard_returned_at': guard_returned_at.isoformat(),
                'guard_handover_details': guard_handover_details.strip(),
                'recorded_at': now.isoformat(),
                'is_overdue': locked_res.is_overdue,
            },
            request=request
        )

    return locked_res


def complete_inspection(
    reservation,
    inspected_by,
    condition_at_return,
    inspection_remarks='',
    id_collected_now=False,
    id_returned_by=None,
    request=None
):
    """
    Completes formal CBA office inspection for equipment returned to a security guard.
    Transitions reservation status: RETURNED_TO_GUARD -> RETURNED.
    Updates asset condition and operational status:
    - Normal (NEW, GOOD, FAIR, POOR) -> AVAILABLE (released back to reservable pool!)
    - UNSERVICEABLE -> DAMAGED
    Optionally records school ID collection if the student is present.
    Requires Custodian authorization.
    """
    check_custodian_permission(inspected_by)

    if not condition_at_return or condition_at_return not in Asset.Condition.values:
        raise ValidationError("A valid physical condition inspection rating is required.")

    with transaction.atomic():
        locked_res = StudentReservation.objects.select_for_update().select_related('asset').get(pk=reservation.pk)

        if locked_res.status != StudentReservation.Status.RETURNED_TO_GUARD:
            raise ValidationError(
                f"Cannot complete inspection: reservation status is '{locked_res.get_status_display()}'. "
                f"Only equipment in RETURNED_TO_GUARD status can undergo guard return inspection."
            )

        locked_asset = Asset.objects.select_for_update().get(pk=locked_res.asset.pk)
        now = timezone.now()

        locked_res.status = StudentReservation.Status.RETURNED
        locked_res.cba_inspected_by = inspected_by
        locked_res.cba_inspected_at = now
        locked_res.returned_to = inspected_by
        locked_res.returned_at = now
        locked_res.condition_at_return = condition_at_return
        locked_res.return_remarks = inspection_remarks.strip()

        if id_collected_now and locked_res.id_deposit_verified and locked_res.id_collected_at is None:
            locked_res.id_collected_at = now
            locked_res.id_returned_by = id_returned_by or inspected_by

        locked_res.save()

        # Release asset back into circulation
        locked_asset.condition = condition_at_return
        if condition_at_return == Asset.Condition.UNSERVICEABLE:
            locked_asset.status = Asset.Status.DAMAGED
        else:
            locked_asset.status = Asset.Status.AVAILABLE
        locked_asset.save()

        log_action(
            user=inspected_by,
            action='STUDENT_RESERVATION_INSPECTED',
            instance=locked_res,
            changes={
                'asset_code': locked_asset.asset_code,
                'inspected_at': now.isoformat(),
                'condition_at_return': condition_at_return,
                'resulting_asset_status': locked_asset.status,
                'id_collected': bool(locked_res.id_collected_at),
            },
            request=request
        )

    return locked_res


def record_id_collection(reservation, returned_by, remarks='', request=None):
    """
    Records physical retrieval of the deposited school ID by the student at the CBA office.
    Business rules:
    - Students collect their deposited school IDs at the CBA office.
    Requires Custodian authorization.
    """
    check_custodian_permission(returned_by)

    with transaction.atomic():
        locked_res = StudentReservation.objects.select_for_update().get(pk=reservation.pk)

        if not locked_res.id_deposit_verified:
            raise ValidationError("No school ID deposit has been recorded for this reservation.")

        if locked_res.id_collected_at is not None:
            raise ValidationError(
                f"School ID was already collected on {locked_res.id_collected_at:%Y-%m-%d %H:%M}."
            )

        now = timezone.now()
        locked_res.id_collected_at = now
        locked_res.id_returned_by = returned_by
        locked_res.id_collection_remarks = remarks.strip()
        locked_res.save()

        log_action(
            user=returned_by,
            action='STUDENT_ID_COLLECTED',
            instance=locked_res,
            changes={
                'student_name': locked_res.student_name,
                'student_id': locked_res.student_id,
                'id_collected_at': now.isoformat(),
                'returned_by': returned_by.username,
            },
            request=request
        )

    return locked_res


def get_reservation_by_token(lookup_token):
    """
    Retrieves reservation using secure public lookup token.
    Raises ValidationError if token is missing or not found.
    Protects student privacy by requiring token rather than student ID.
    """
    if not lookup_token or not str(lookup_token).strip():
        raise ValidationError("Reservation lookup token is required.")

    auto_expire_uncollected_reservations()

    try:
        return StudentReservation.objects.select_related('category', 'asset').get(lookup_token=str(lookup_token).strip())
    except StudentReservation.DoesNotExist:
        raise ValidationError("Reservation not found. Please verify your lookup token.")
