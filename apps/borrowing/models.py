from django.db import models
from django.conf import settings
from django.utils import timezone
from django.core.exceptions import ValidationError
from apps.inventory.models import Asset


class AssetBorrowing(models.Model):
    """
    Historical record of temporary physical equipment borrowing and reservations.
    Decoupled from long-term AssetAssignment and formal AssetTransfer.
    """

    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Pending Approval'
        APPROVED = 'APPROVED', 'Approved (Reserved)'
        RELEASED = 'RELEASED', 'Released (Borrowed)'
        RETURNED = 'RETURNED', 'Returned'
        REJECTED = 'REJECTED', 'Rejected'
        CANCELLED = 'CANCELLED', 'Cancelled'
        OVERDUE = 'OVERDUE', 'Overdue'

    # Core Relational Links
    asset = models.ForeignKey(
        Asset,
        on_delete=models.PROTECT,
        related_name='borrowings',
        help_text='The durable physical asset requested or borrowed.'
    )
    borrower = models.ForeignKey(
        'organizations.Employee',
        on_delete=models.PROTECT,
        related_name='borrowings',
        help_text='The employee/faculty member responsible for temporary custody.'
    )
    borrower_department = models.ForeignKey(
        'organizations.Department',
        on_delete=models.PROTECT,
        related_name='borrowings',
        help_text="The borrower's department at the time of request."
    )

    # Request Details
    requested_at = models.DateTimeField(default=timezone.now, db_index=True)
    purpose = models.CharField(max_length=500, help_text='Purpose of temporary equipment use.')
    requested_start = models.DateTimeField(db_index=True, help_text='Planned start time of reservation.')
    requested_return = models.DateTimeField(db_index=True, help_text='Expected return deadline.')

    # Approval / Review
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reviewed_borrowings'
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True, help_text='Required explanation if request is rejected.')

    # Physical Release
    released_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='released_borrowings'
    )
    released_at = models.DateTimeField(null=True, blank=True)
    condition_at_release = models.CharField(
        max_length=20,
        choices=Asset.Condition.choices,
        blank=True,
        help_text='Snapshot of physical condition when equipment left custody.'
    )

    # Physical Return & Inspection
    returned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='received_returned_borrowings'
    )
    returned_at = models.DateTimeField(null=True, blank=True)
    condition_at_return = models.CharField(
        max_length=20,
        choices=Asset.Condition.choices,
        blank=True,
        help_text='Inspected physical condition upon return.'
    )
    return_remarks = models.TextField(blank=True, help_text='Inspector notes or damage reports on return.')

    # Metadata & Tracking
    remarks = models.TextField(blank=True, help_text='Additional notes or instructions.')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-requested_at']
        verbose_name = 'Asset Borrowing'
        verbose_name_plural = 'Asset Borrowings'
        indexes = [
            models.Index(fields=['asset', 'status']),
            models.Index(fields=['borrower', 'status']),
            models.Index(fields=['status', 'requested_start', 'requested_return']),
        ]
        constraints = [
            # Ensure an asset cannot have multiple simultaneous active physical releases
            models.UniqueConstraint(
                fields=['asset'],
                condition=models.Q(status__in=['RELEASED', 'OVERDUE']),
                name='unique_active_released_borrowing'
            )
        ]

    def __str__(self):
        return f"{self.asset.asset_code} borrowed by {self.borrower.full_name} ({self.get_status_display()})"

    def clean(self):
        super().clean()
        if self.requested_start and self.requested_return:
            if self.requested_start >= self.requested_return:
                raise ValidationError({
                    'requested_return': 'Expected return date/time must be strictly after the start date/time.'
                })

    @property
    def is_overdue(self):
        """
        Dynamic check whether this released borrowing has passed its return deadline without return.
        """
        if self.status in [self.Status.RELEASED, self.Status.OVERDUE] and self.returned_at is None:
            return timezone.now() > self.requested_return
        return False

    @property
    def effective_status(self):
        """Returns OVERDUE if the dynamic deadline has passed, otherwise the database status."""
        if self.is_overdue:
            return self.Status.OVERDUE
        return self.status

    @property
    def effective_status_display(self):
        """User-facing status display accounting for real-time overdue evaluation."""
        if self.is_overdue:
            return 'Overdue'
        return self.get_status_display()
