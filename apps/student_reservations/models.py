import secrets
from datetime import timedelta
from django.db import models
from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.inventory.models import Asset, AssetCategory


class StudentReservation(models.Model):
    """
    Record of a student equipment reservation and borrowing lifecycle.
    Students do not have system user accounts; identity is verified physically
    using their original school ID, which is left in custody at the CBA office.
    """

    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Pending Approval'
        APPROVED = 'APPROVED', 'Approved (Reserved)'
        RELEASED = 'RELEASED', 'Released (Active Loan)'
        RETURNED = 'RETURNED', 'Returned'
        REJECTED = 'REJECTED', 'Rejected'
        CANCELLED = 'CANCELLED', 'Cancelled'
        NO_SHOW = 'NO_SHOW', 'No Show'
        RETURNED_TO_GUARD = 'RETURNED_TO_GUARD', 'Returned to Guard (Awaiting Inspection)'

    # 1. Student Information (Captured metadata; physical ID verified at pickup)
    student_id = models.CharField(
        max_length=50,
        db_index=True,
        help_text="Institutional Student ID number (e.g. 2023-10482)."
    )
    student_name = models.CharField(
        max_length=200,
        help_text="Full name of the student."
    )
    course_year_section = models.CharField(
        max_length=100,
        help_text="Academic course, year, and section (e.g. BSBA 3-A)."
    )
    email = models.EmailField(
        help_text="Student contact email address."
    )
    contact_number = models.CharField(
        max_length=50,
        help_text="Student contact mobile/telephone number."
    )

    # 2. Requested Equipment Information
    category = models.ForeignKey(
        AssetCategory,
        on_delete=models.PROTECT,
        related_name='student_reservations',
        help_text="Requested equipment category."
    )
    equipment_type = models.CharField(
        max_length=150,
        blank=True,
        help_text="Requested equipment subtype or specification (e.g. Projector, Speaker, Microphone)."
    )

    # 3. Allocated Physical Asset (Allocated by Property Custodian upon approval)
    asset = models.ForeignKey(
        Asset,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='student_reservations',
        help_text="Physical asset allocated by Custodian upon approval."
    )

    # 4. Schedule & Purpose
    requested_pickup = models.DateTimeField(
        db_index=True,
        help_text="Scheduled equipment pickup datetime."
    )
    requested_return = models.DateTimeField(
        db_index=True,
        help_text="Scheduled equipment return deadline."
    )
    purpose = models.CharField(
        max_length=500,
        help_text="Official purpose of equipment use (e.g. Class presentation, Student council event)."
    )
    room_venue = models.CharField(
        max_length=150,
        blank=True,
        help_text="Classroom, laboratory, or event venue where equipment will be used."
    )

    # 5. Status & Approval
    status = models.CharField(
        max_length=25,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reviewed_student_reservations'
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(
        blank=True,
        help_text="Required explanation if the reservation is rejected."
    )
    grace_period_minutes = models.PositiveIntegerField(
        default=15,
        help_text="Pickup grace period in minutes from requested_pickup (default 15, extendable by Custodian)."
    )

    # 6. Physical Equipment Release
    released_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='released_student_reservations'
    )
    released_at = models.DateTimeField(null=True, blank=True)
    condition_at_release = models.CharField(
        max_length=20,
        choices=Asset.Condition.choices,
        blank=True,
        help_text="Physical condition snapshot when equipment was handed over to the student."
    )

    # 7. Physical Equipment Return (Direct Office Handover)
    returned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='received_student_reservations'
    )
    returned_at = models.DateTimeField(null=True, blank=True)
    condition_at_return = models.CharField(
        max_length=20,
        choices=Asset.Condition.choices,
        blank=True,
        help_text="Physical condition snapshot upon return inspection."
    )
    return_remarks = models.TextField(
        blank=True,
        help_text="Inspection notes or damage details recorded on return."
    )

    # 8. Security Guard Handover & Inspection Workflow
    guard_returned_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Documented handover datetime to security guard after office hours."
    )
    guard_handover_details = models.CharField(
        max_length=255,
        blank=True,
        help_text="Documented details of guard handover (e.g. Guard Name, Security Logbook Entry #)."
    )
    guard_recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='guard_recorded_student_reservations',
        help_text="CBA office staff who entered the guard return into the system."
    )
    guard_recorded_at = models.DateTimeField(null=True, blank=True)
    cba_inspected_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='inspected_student_reservations',
        help_text="CBA Custodian/staff who performed inspection on guard-returned equipment."
    )
    cba_inspected_at = models.DateTimeField(null=True, blank=True)

    # 9. Physical School ID Custody & Collection
    id_deposit_verified = models.BooleanField(
        default=False,
        help_text="Indicates whether physical school ID was verified and deposited at CBA office."
    )
    id_deposited_at = models.DateTimeField(null=True, blank=True)
    id_collected_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp when the student physically retrieved their deposited school ID."
    )
    id_returned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='id_returned_student_reservations',
        help_text="Staff member who returned the deposited school ID to the student."
    )
    id_collection_remarks = models.CharField(
        max_length=255,
        blank=True,
        help_text="Remarks regarding school ID return."
    )

    # 10. Unguessable Public Lookup Token & Tracking
    lookup_token = models.CharField(
        max_length=64,
        unique=True,
        db_index=True,
        editable=False,
        help_text="Secure, unguessable public lookup token for students to check reservation status."
    )

    # 11. Timestamps & Remarks
    remarks = models.TextField(blank=True, help_text="Additional operational remarks.")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Student Reservation'
        verbose_name_plural = 'Student Reservations'
        indexes = [
            models.Index(fields=['status', 'requested_pickup', 'requested_return']),
            models.Index(fields=['asset', 'status']),
            models.Index(fields=['lookup_token']),
            models.Index(fields=['student_id', 'status']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['asset'],
                condition=models.Q(status__in=['RELEASED', 'RETURNED_TO_GUARD']),
                name='unique_active_released_student_reservation'
            )
        ]

    def __str__(self):
        category_name = self.category.name if self.category_id else 'General'
        return f"Reservation #{self.pk or 'New'} - {self.student_name} ({category_name}) [{self.get_status_display()}]"

    def clean(self):
        super().clean()
        if self.requested_pickup and self.requested_return:
            if self.requested_pickup >= self.requested_return:
                raise ValidationError({
                    'requested_return': 'Requested return time must be strictly after the pickup time.'
                })
        if self.asset and self.category_id and self.asset.category_id != self.category_id:
            raise ValidationError({
                'asset': f"Allocated asset '{self.asset.asset_code}' does not belong to category '{self.category.name}'."
            })

    def save(self, *args, **kwargs):
        if not self.lookup_token:
            self.lookup_token = secrets.token_urlsafe(32)
        super().save(*args, **kwargs)

    # Computed / Business Logic Properties
    @property
    def pickup_deadline(self):
        """Calculates the deadline for pickup based on grace period."""
        if not self.requested_pickup:
            return None
        return self.requested_pickup + timedelta(minutes=self.grace_period_minutes)

    @property
    def is_pickup_expired(self):
        """Returns True if the approved reservation has passed its pickup grace deadline without release."""
        if self.status == self.Status.APPROVED and self.pickup_deadline:
            return timezone.now() > self.pickup_deadline
        return False

    @property
    def actual_handover_time(self):
        """
        Returns the physical handover timestamp when equipment left student possession:
        guard_returned_at for after-hours guard handover, or returned_at for direct office handover.
        """
        return self.guard_returned_at or self.returned_at

    @property
    def is_overdue(self):
        """
        Calculates overdue status based on expected return deadline and physical handover time.
        - If still physically RELEASED: overdue if now > requested_return.
        - If RETURNED or RETURNED_TO_GUARD: overdue if physical handover occurred after requested_return.
        """
        if not self.requested_return:
            return False
        if self.status == self.Status.RELEASED:
            return timezone.now() > self.requested_return
        if self.status in [self.Status.RETURNED, self.Status.RETURNED_TO_GUARD]:
            handover = self.actual_handover_time
            if handover:
                return handover > self.requested_return
        return False

    @property
    def overdue_duration(self):
        """
        Returns timedelta of how late the equipment was kept beyond the expected return deadline.
        Returns timedelta(0) if not overdue.
        """
        if not self.requested_return:
            return timedelta(0)
        if self.status == self.Status.RELEASED:
            diff = timezone.now() - self.requested_return
            return diff if diff.total_seconds() > 0 else timedelta(0)
        if self.status in [self.Status.RETURNED, self.Status.RETURNED_TO_GUARD]:
            handover = self.actual_handover_time
            if handover and handover > self.requested_return:
                return handover - self.requested_return
        return timedelta(0)

    @property
    def is_id_in_custody(self):
        """Returns True if the student's ID has been deposited and not yet collected."""
        return self.id_deposit_verified and self.id_collected_at is None
