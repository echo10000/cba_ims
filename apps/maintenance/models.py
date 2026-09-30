from decimal import Decimal
from django.db import models
from django.conf import settings
from django.core.validators import MinValueValidator
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.inventory.models import Asset


class AssetMaintenance(models.Model):
    """
    Historical maintenance, repair, and damage tracking record for durable college assets.
    Tracks issue reporting, diagnostic assessment, physical repair, and return to service.
    """

    class Status(models.TextChoices):
        REPORTED = 'REPORTED', 'Reported'
        ASSESSED = 'ASSESSED', 'Assessed'
        IN_REPAIR = 'IN_REPAIR', 'In Repair'
        COMPLETED = 'COMPLETED', 'Completed'
        FOR_REPLACEMENT = 'FOR_REPLACEMENT', 'For Replacement'
        CANCELLED = 'CANCELLED', 'Cancelled'

    class ReportSource(models.TextChoices):
        MANUAL_REPORT = 'MANUAL_REPORT', 'Manual Report'
        BORROW_RETURN = 'BORROW_RETURN', 'Borrow Return Inspection'
        ASSIGNMENT_RETURN = 'ASSIGNMENT_RETURN', 'Assignment Return Inspection'
        PHYSICAL_VERIFICATION = 'PHYSICAL_VERIFICATION', 'Physical Inventory Verification'
        ADMIN_INSPECTION = 'ADMIN_INSPECTION', 'Custodian / Admin Inspection'

    class Severity(models.TextChoices):
        LOW = 'LOW', 'Low - Minor Cosmetic / Non-Essential'
        MEDIUM = 'MEDIUM', 'Medium - Impaired Functionality'
        HIGH = 'HIGH', 'High - Inoperable / Unusable'
        CRITICAL = 'CRITICAL', 'Critical - Safety Hazard / Urgent Core Facility'

    # Case Identification
    case_number = models.CharField(
        max_length=50,
        unique=True,
        editable=False,
        db_index=True,
        help_text='Auto-generated unique maintenance identifier (e.g. MNT-2026-00001)'
    )
    asset = models.ForeignKey(
        Asset,
        on_delete=models.PROTECT,
        related_name='maintenance_records',
        help_text='The physical asset undergoing maintenance'
    )

    # Status & Prioritization
    status = models.CharField(
        max_length=25,
        choices=Status.choices,
        default=Status.REPORTED,
        db_index=True
    )
    severity = models.CharField(
        max_length=20,
        choices=Severity.choices,
        blank=True,
        null=True,
        db_index=True,
        help_text='Operational severity set during inspection/assessment'
    )
    source = models.CharField(
        max_length=30,
        choices=ReportSource.choices,
        default=ReportSource.MANUAL_REPORT,
        help_text='Operational channel that originated this maintenance incident'
    )

    # Optional cross-module triggering references
    borrowing_reference = models.ForeignKey(
        'borrowing.AssetBorrowing',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='maintenance_cases',
        help_text='Optional borrowing transaction that surfaced the damage'
    )
    verification_reference = models.ForeignKey(
        'inventory.AssetVerification',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='maintenance_cases',
        help_text='Optional physical verification audit that flagged a condition mismatch'
    )

    # Condition Snapshots
    condition_before = models.CharField(
        max_length=20,
        choices=Asset.Condition.choices,
        blank=True,
        help_text='Asset physical condition snapshotted at time of incident/assessment'
    )
    final_condition = models.CharField(
        max_length=20,
        choices=Asset.Condition.choices,
        blank=True,
        help_text='Physical condition evaluated upon completion of repair or assessment'
    )

    # 1. Reporting Phase
    issue_title = models.CharField(
        max_length=200,
        help_text='Short descriptive title of the defect or failure'
    )
    issue_description = models.TextField(
        help_text='Detailed explanation of observed symptoms, damage, or malfunction'
    )
    reported_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='reported_maintenances',
        help_text='User who filed the defect report'
    )
    reported_at = models.DateTimeField(
        default=timezone.now,
        db_index=True
    )

    # 2. Assessment Phase
    assessed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assessed_maintenances'
    )
    assessed_at = models.DateTimeField(null=True, blank=True)
    diagnosis = models.TextField(
        blank=True,
        help_text='Technical finding, root cause, or diagnostic evaluation'
    )
    recommended_action = models.TextField(
        blank=True,
        help_text='Proposed corrective action (e.g. in-house servicing, authorized center, part replacement)'
    )

    # 3. Repair Execution Phase
    service_provider = models.CharField(
        max_length=200,
        blank=True,
        help_text='Entity executing repair (e.g., In-house IT, Epson Service Center, Local vendor)'
    )
    technician = models.CharField(
        max_length=200,
        blank=True,
        help_text='Name or contact of servicing technician'
    )
    repair_started_at = models.DateTimeField(null=True, blank=True)
    repair_completed_at = models.DateTimeField(null=True, blank=True)
    repair_cost = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal('0.00'))],
        help_text='Operational repair expense incurred in PHP'
    )
    action_taken = models.TextField(
        blank=True,
        help_text='Specific mechanical or electrical repairs performed'
    )
    parts_replaced = models.TextField(
        blank=True,
        help_text='Itemized spare parts, modules, or consumables replaced'
    )

    # 4. Return to Service / Resolution Phase
    returned_to_service_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='service_returned_maintenances'
    )
    returned_to_service_at = models.DateTimeField(null=True, blank=True)

    # Cancellation Phase
    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='cancelled_maintenances'
    )
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancellation_reason = models.TextField(blank=True)

    # General Remarks & Timestamps
    remarks = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-reported_at', '-id']
        verbose_name = 'Asset Maintenance'
        verbose_name_plural = 'Asset Maintenances'
        indexes = [
            models.Index(fields=['status', 'asset']),
            models.Index(fields=['reported_at']),
        ]

    def __str__(self):
        return f"{self.case_number} - {self.asset.asset_code} ({self.get_status_display()})"

    @classmethod
    def generate_case_number(cls, year=None):
        """
        Generates a collision-safe sequential case identifier.
        Format: MNT-{YEAR}-{NUMBER:05d} (e.g. MNT-2026-00001).
        """
        if year is None:
            year = timezone.now().year
        prefix = f"MNT-{year}-"
        last_rec = cls.objects.filter(case_number__startswith=prefix).order_by('-case_number').first()
        if last_rec:
            try:
                last_num = int(last_rec.case_number.split('-')[-1])
                seq = last_num + 1
            except (ValueError, IndexError):
                seq = 1
        else:
            seq = 1

        new_code = f"{prefix}{seq:05d}"
        while cls.objects.filter(case_number=new_code).exists():
            seq += 1
            new_code = f"{prefix}{seq:05d}"
        return new_code

    def clean(self):
        super().clean()
        if self.repair_cost is not None and self.repair_cost < Decimal('0.00'):
            raise ValidationError({'repair_cost': 'Repair cost cannot be negative.'})
        if self.status == self.Status.COMPLETED and not self.final_condition:
            raise ValidationError({'final_condition': 'Final condition is required when completing a maintenance case.'})

    def save(self, *args, **kwargs):
        self.clean()
        if not self.case_number:
            year = self.reported_at.year if self.reported_at else timezone.now().year
            self.case_number = self.generate_case_number(year=year)
        super().save(*args, **kwargs)

    @property
    def is_active(self):
        """Returns True if the maintenance case is ongoing (not finished or cancelled)."""
        return self.status in [self.Status.REPORTED, self.Status.ASSESSED, self.Status.IN_REPAIR]

    @property
    def is_in_repair(self):
        return self.status == self.Status.IN_REPAIR

    @property
    def is_completed(self):
        return self.status == self.Status.COMPLETED
