from decimal import Decimal
from django.db import transaction
from django.core.exceptions import ValidationError, PermissionDenied
from django.utils import timezone

from apps.inventory.models import Asset
from apps.audit.utils import log_action
from .models import AssetMaintenance


def validate_can_report(user, asset):
    """
    Validates whether the given user is authorized to file a maintenance report for the asset.
    - Admin & Custodians: full authorization for all college assets.
    - Dean & Dept Chairs: authorized for college / departmental assets.
    - Faculty / Staff: strictly restricted to equipment actively assigned to them
      OR equipment currently borrowed by them.
    """
    if getattr(user, 'is_admin', False) or getattr(user, 'role', '') in ['ADMIN', 'DEAN']:
        return True

    if getattr(user, 'role', '') == 'DEPT_CHAIR':
        chair_dept = getattr(getattr(user, 'employee_profile', None), 'department', None)
        if chair_dept and asset.department_id == chair_dept.pk:
            return True
        raise PermissionDenied("Department Chairs can only file maintenance reports for equipment in their department.")

    if getattr(user, 'role', '') == 'FACULTY':
        is_assigned = asset.assignments.filter(employee__user=user, status='ACTIVE').exists()
        is_borrowed = asset.borrowings.filter(borrower__user=user, status__in=['RELEASED', 'OVERDUE']).exists()
        if is_assigned or is_borrowed:
            return True
        raise PermissionDenied("You can only file equipment maintenance reports for assets currently assigned to your accountability or actively on loan to you.")

    raise PermissionDenied("You do not have permission to report maintenance for this asset.")


def resolve_post_maintenance_status(asset, final_condition):
    """
    Authoritatively determines the correct post-maintenance operational status for an asset.
    - If final_condition is UNSERVICEABLE: asset must remain non-operational -> DAMAGED.
    - Else (serviceable: NEW, GOOD, FAIR, POOR):
      - If the asset has an active personnel assignment (Phase 3 accountability): -> ASSIGNED.
      - Else: -> AVAILABLE.
    """
    if final_condition == Asset.Condition.UNSERVICEABLE:
        return Asset.Status.DAMAGED

    if asset.assignments.filter(status='ACTIVE').exists():
        return Asset.Status.ASSIGNED

    return Asset.Status.AVAILABLE


def report_issue(
    asset,
    reported_by,
    issue_title,
    issue_description,
    source=AssetMaintenance.ReportSource.MANUAL_REPORT,
    borrowing_ref=None,
    verification_ref=None,
    remarks='',
    request=None
):
    """
    Files an equipment defect or damage report.
    Validates reporter authorization and preserves the asset's current operational state.
    (Asset.status does NOT prematurely change to MAINTENANCE upon mere reporting).
    """
    validate_can_report(reported_by, asset)

    if asset.status == Asset.Status.DISPOSED:
        raise ValidationError(f"Cannot file maintenance report: Asset '{asset.asset_code}' has been permanently disposed.")

    if not issue_title or not issue_title.strip():
        raise ValidationError("An issue title is required.")
    if not issue_description or not issue_description.strip():
        raise ValidationError("An issue description is required.")

    # Prevent duplicate identical active reports if one is already reported/assessed for the same asset
    existing_open = AssetMaintenance.objects.filter(
        asset=asset,
        status__in=[AssetMaintenance.Status.REPORTED, AssetMaintenance.Status.ASSESSED, AssetMaintenance.Status.IN_REPAIR],
        issue_title__iexact=issue_title.strip()
    ).first()
    if existing_open:
        raise ValidationError(
            f"An active maintenance case ({existing_open.case_number}) with the same issue title is already open for this equipment."
        )

    with transaction.atomic():
        maintenance = AssetMaintenance(
            asset=asset,
            issue_title=issue_title.strip(),
            issue_description=issue_description.strip(),
            reported_by=reported_by,
            reported_at=timezone.now(),
            source=source,
            borrowing_reference=borrowing_ref,
            verification_reference=verification_ref,
            condition_before=asset.condition,
            remarks=remarks.strip(),
            status=AssetMaintenance.Status.REPORTED
        )
        maintenance.save()

        log_action(
            user=reported_by,
            action='MAINTENANCE_REPORTED',
            instance=maintenance,
            changes={
                'case_number': maintenance.case_number,
                'asset_code': asset.asset_code,
                'issue_title': maintenance.issue_title,
                'source': maintenance.get_source_display(),
                'status': maintenance.get_status_display(),
            },
            request=request
        )

    return maintenance


def assess_issue(
    maintenance,
    assessed_by,
    severity,
    diagnosis,
    recommended_action='',
    remarks='',
    request=None
):
    """
    Records diagnostic inspection findings and operational severity for a maintenance case.
    Transitions status from REPORTED to ASSESSED.
    """
    if not diagnosis or not diagnosis.strip():
        raise ValidationError("A technical diagnosis or finding must be provided.")
    if not severity:
        raise ValidationError("An operational severity rating must be selected.")

    with transaction.atomic():
        locked_m = AssetMaintenance.objects.select_for_update().select_related('asset').get(pk=maintenance.pk)

        if locked_m.status not in [AssetMaintenance.Status.REPORTED, AssetMaintenance.Status.ASSESSED]:
            raise ValidationError(
                f"Cannot assess case {locked_m.case_number}: current status is '{locked_m.get_status_display()}'. Only REPORTED or ASSESSED cases may be assessed."
            )

        locked_m.assessed_by = assessed_by
        locked_m.assessed_at = timezone.now()
        locked_m.severity = severity
        locked_m.diagnosis = diagnosis.strip()
        locked_m.recommended_action = recommended_action.strip()
        if not locked_m.condition_before:
            locked_m.condition_before = locked_m.asset.condition

        if remarks.strip():
            existing = locked_m.remarks
            locked_m.remarks = f"{existing}\nAssessment: {remarks.strip()}".strip() if existing else f"Assessment: {remarks.strip()}"

        locked_m.status = AssetMaintenance.Status.ASSESSED
        locked_m.save()

        log_action(
            user=assessed_by,
            action='MAINTENANCE_ASSESSED',
            instance=locked_m,
            changes={
                'case_number': locked_m.case_number,
                'asset_code': locked_m.asset.asset_code,
                'severity': locked_m.get_severity_display(),
                'diagnosis': locked_m.diagnosis,
                'status': locked_m.get_status_display(),
            },
            request=request
        )

    return locked_m


def start_repair(
    maintenance,
    user,
    service_provider,
    technician='',
    repair_started_at=None,
    remarks='',
    request=None
):
    """
    Transitions a maintenance case to IN_REPAIR and marks the Asset as UNDER_MAINTENANCE.
    Enforces that:
    1. Case must be ASSESSED.
    2. Asset must not be physically out on active temporary loan (BORROWED).
    3. Asset must not already be in an active repair under another case.
    Preserves ongoing faculty accountability (AssetAssignment).
    """
    if not service_provider or not service_provider.strip():
        raise ValidationError("A service provider or maintenance facility must be specified.")

    with transaction.atomic():
        locked_m = AssetMaintenance.objects.select_for_update().select_related('asset').get(pk=maintenance.pk)
        locked_asset = Asset.objects.select_for_update().get(pk=locked_m.asset.pk)

        if locked_m.status != AssetMaintenance.Status.ASSESSED:
            raise ValidationError(
                f"Cannot start repair for {locked_m.case_number}: status is '{locked_m.get_status_display()}'. Equipment must be ASSESSED before starting repair."
            )

        if locked_asset.status == Asset.Status.DISPOSED:
            raise ValidationError(
                f"Cannot start repair: Asset '{locked_asset.asset_code}' is permanently disposed."
            )

        # Invariant: Borrowed equipment must be returned before active repair begins
        if locked_asset.status == Asset.Status.BORROWED or locked_asset.borrowings.filter(status__in=['RELEASED', 'OVERDUE']).exists():
            raise ValidationError(
                f"Cannot start repair: Asset '{locked_asset.asset_code}' is currently borrowed on loan. The equipment must be returned first."
            )

        # Invariant: Only one active repair per physical asset
        if AssetMaintenance.objects.filter(
            asset=locked_asset,
            status=AssetMaintenance.Status.IN_REPAIR
        ).exclude(pk=locked_m.pk).exists():
            raise ValidationError(
                f"Asset '{locked_asset.asset_code}' already has another maintenance case actively in repair."
            )

        locked_m.service_provider = service_provider.strip()
        locked_m.technician = technician.strip()
        locked_m.repair_started_at = repair_started_at or timezone.now()
        locked_m.status = AssetMaintenance.Status.IN_REPAIR
        if not locked_m.condition_before:
            locked_m.condition_before = locked_asset.condition

        if remarks.strip():
            existing = locked_m.remarks
            locked_m.remarks = f"{existing}\nRepair Dispatch: {remarks.strip()}".strip() if existing else f"Repair Dispatch: {remarks.strip()}"

        locked_m.save()

        # Update Asset operational status to MAINTENANCE
        locked_asset.status = Asset.Status.MAINTENANCE
        locked_asset.save(update_fields=['status'])

        log_action(
            user=user,
            action='MAINTENANCE_REPAIR_STARTED',
            instance=locked_m,
            changes={
                'case_number': locked_m.case_number,
                'asset_code': locked_asset.asset_code,
                'service_provider': locked_m.service_provider,
                'technician': locked_m.technician,
                'asset_status': locked_asset.get_status_display(),
            },
            request=request
        )

    return locked_m


def complete_repair(
    maintenance,
    user,
    final_condition,
    action_taken='',
    parts_replaced='',
    repair_cost=None,
    repair_completed_at=None,
    remarks='',
    request=None
):
    """
    Completes repair activity and restores asset to service.
    Transitions maintenance status to COMPLETED.
    Updates asset.condition to final_condition.
    Authoritatively restores asset operational status:
    - If unserviceable: -> DAMAGED
    - If serviceable and actively assigned to personnel: -> ASSIGNED (preserves accountability!)
    - If serviceable and unassigned: -> AVAILABLE
    """
    if not final_condition:
        raise ValidationError("A final evaluated physical condition is required.")

    if repair_cost is not None and repair_cost < Decimal('0.00'):
        raise ValidationError("Repair cost cannot be negative.")

    with transaction.atomic():
        locked_m = AssetMaintenance.objects.select_for_update().select_related('asset').get(pk=maintenance.pk)
        locked_asset = Asset.objects.select_for_update().get(pk=locked_m.asset.pk)

        if locked_m.status != AssetMaintenance.Status.IN_REPAIR:
            raise ValidationError(
                f"Cannot complete case {locked_m.case_number}: status is '{locked_m.get_status_display()}'. Only cases IN_REPAIR can be completed."
            )

        locked_m.final_condition = final_condition
        locked_m.action_taken = action_taken.strip()
        locked_m.parts_replaced = parts_replaced.strip()
        locked_m.repair_cost = repair_cost
        locked_m.repair_completed_at = repair_completed_at or timezone.now()
        locked_m.returned_to_service_by = user
        locked_m.returned_to_service_at = timezone.now()
        locked_m.status = AssetMaintenance.Status.COMPLETED

        if remarks.strip():
            existing = locked_m.remarks
            locked_m.remarks = f"{existing}\nCompletion note: {remarks.strip()}".strip() if existing else f"Completion note: {remarks.strip()}"

        locked_m.save()

        # Update physical condition
        locked_asset.condition = final_condition

        # Derive and set authoritative operational status
        new_asset_status = resolve_post_maintenance_status(locked_asset, final_condition)
        locked_asset.status = new_asset_status
        locked_asset.save(update_fields=['condition', 'status'])

        log_action(
            user=user,
            action='MAINTENANCE_COMPLETED',
            instance=locked_m,
            changes={
                'case_number': locked_m.case_number,
                'asset_code': locked_asset.asset_code,
                'final_condition': locked_m.get_final_condition_display(),
                'repair_cost': str(locked_m.repair_cost) if locked_m.repair_cost is not None else '0.00',
                'restored_asset_status': locked_asset.get_status_display(),
            },
            request=request
        )

    return locked_m


def mark_for_replacement(
    maintenance,
    user,
    remarks='',
    request=None
):
    """
    Concludes that continued repair is uneconomical or unviable.
    Transitions maintenance status to FOR_REPLACEMENT.
    Asset is kept in a safe non-operational state (DAMAGED) with UNSERVICEABLE condition.
    (Asset is NOT disposed; formal disposal is managed in Phase 9).
    """
    with transaction.atomic():
        locked_m = AssetMaintenance.objects.select_for_update().select_related('asset').get(pk=maintenance.pk)
        locked_asset = Asset.objects.select_for_update().get(pk=locked_m.asset.pk)

        if locked_m.status not in [
            AssetMaintenance.Status.REPORTED,
            AssetMaintenance.Status.ASSESSED,
            AssetMaintenance.Status.IN_REPAIR
        ]:
            raise ValidationError(
                f"Cannot mark {locked_m.case_number} for replacement: status is already '{locked_m.get_status_display()}'."
            )

        locked_m.status = AssetMaintenance.Status.FOR_REPLACEMENT
        locked_m.final_condition = Asset.Condition.UNSERVICEABLE
        locked_m.repair_completed_at = timezone.now()

        if remarks.strip():
            existing = locked_m.remarks
            locked_m.remarks = f"{existing}\nReplacement Recommendation: {remarks.strip()}".strip() if existing else f"Replacement Recommendation: {remarks.strip()}"

        locked_m.save()

        locked_asset.condition = Asset.Condition.UNSERVICEABLE
        locked_asset.status = Asset.Status.DAMAGED
        locked_asset.save(update_fields=['condition', 'status'])

        log_action(
            user=user,
            action='MAINTENANCE_FOR_REPLACEMENT',
            instance=locked_m,
            changes={
                'case_number': locked_m.case_number,
                'asset_code': locked_asset.asset_code,
                'final_condition': 'Unserviceable',
                'asset_status': 'Damaged',
            },
            request=request
        )

    return locked_m


def cancel_maintenance(
    maintenance,
    user,
    cancellation_reason,
    request=None
):
    """
    Cancels an open maintenance case (e.g. false alarm, duplicate, resolved without servicing).
    If the asset was previously in MAINTENANCE status, restores its correct operational status.
    """
    if not cancellation_reason or not cancellation_reason.strip():
        raise ValidationError("A cancellation reason must be provided.")

    with transaction.atomic():
        locked_m = AssetMaintenance.objects.select_for_update().select_related('asset').get(pk=maintenance.pk)
        locked_asset = Asset.objects.select_for_update().get(pk=locked_m.asset.pk)

        if locked_m.status in [
            AssetMaintenance.Status.COMPLETED,
            AssetMaintenance.Status.FOR_REPLACEMENT,
            AssetMaintenance.Status.CANCELLED
        ]:
            raise ValidationError(
                f"Cannot cancel {locked_m.case_number}: case is already '{locked_m.get_status_display()}'."
            )

        locked_m.status = AssetMaintenance.Status.CANCELLED
        locked_m.cancelled_by = user
        locked_m.cancelled_at = timezone.now()
        locked_m.cancellation_reason = cancellation_reason.strip()
        locked_m.save()

        # If asset was marked UNDER_MAINTENANCE because of this case, restore it
        if locked_asset.status == Asset.Status.MAINTENANCE:
            restored_status = resolve_post_maintenance_status(locked_asset, locked_asset.condition)
            locked_asset.status = restored_status
            locked_asset.save(update_fields=['status'])

        log_action(
            user=user,
            action='MAINTENANCE_CANCELLED',
            instance=locked_m,
            changes={
                'case_number': locked_m.case_number,
                'asset_code': locked_asset.asset_code,
                'cancellation_reason': locked_m.cancellation_reason,
                'asset_status': locked_asset.get_status_display(),
            },
            request=request
        )

    return locked_m
