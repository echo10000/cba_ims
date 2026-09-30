from django.db import models
from django.conf import settings
from django.utils import timezone
from django.core.exceptions import ValidationError


class AssetTransfer(models.Model):
    """
    Historical model tracking physical movement and departmental reallocation of assets.
    Preserves immutable origin snapshots and lifecycle audit details.
    """
    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Pending Approval'
        APPROVED = 'APPROVED', 'Approved'
        COMPLETED = 'COMPLETED', 'Completed'
        REJECTED = 'REJECTED', 'Rejected'
        CANCELLED = 'CANCELLED', 'Cancelled'

    asset = models.ForeignKey(
        'inventory.Asset',
        on_delete=models.PROTECT,
        related_name='transfers',
        help_text='Physical asset being transferred'
    )

    # Origin Snapshot (immutable once created)
    from_department = models.ForeignKey(
        'organizations.Department',
        on_delete=models.PROTECT,
        related_name='transfers_from',
        help_text='Source department at time of transfer request'
    )
    from_location = models.ForeignKey(
        'organizations.Location',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='transfers_from',
        help_text='Source physical location at time of transfer request'
    )

    # Destination Target
    to_department = models.ForeignKey(
        'organizations.Department',
        on_delete=models.PROTECT,
        related_name='transfers_to',
        help_text='Target destination department'
    )
    to_location = models.ForeignKey(
        'organizations.Location',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='transfers_to',
        help_text='Target physical destination location'
    )

    # Transfer Context
    transfer_date = models.DateField(
        default=timezone.now,
        help_text='Scheduled or effective physical transfer date'
    )
    reason = models.CharField(
        max_length=300,
        help_text='Official justification (e.g. Redistribution, Room Reallocation, Faculty Transfer)'
    )
    remarks = models.TextField(
        blank=True,
        help_text='Handling notes, condition on dispatch, carrier, or custody context'
    )

    # Workflow & Actors
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='requested_transfers',
        help_text='User who initiated the transfer request'
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='approved_transfers',
        help_text='Administrator/Officer who authorized the transfer'
    )
    processed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='processed_transfers',
        help_text='Custodian/Admin who physically executed and confirmed receipt'
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True
    )

    # Lifecycle Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            # Ensure an asset never has multiple concurrent open (PENDING/APPROVED) transfer requests
            models.UniqueConstraint(
                fields=['asset'],
                condition=models.Q(status__in=['PENDING', 'APPROVED']),
                name='unique_open_transfer_per_asset'
            )
        ]

    def __str__(self):
        from_str = f"{self.from_department.code}/{self.from_location.name if self.from_location else 'No Loc'}"
        to_str = f"{self.to_department.code}/{self.to_location.name if self.to_location else 'No Loc'}"
        return f"{self.asset.asset_code}: {from_str} -> {to_str} ({self.status})"

    def clean(self):
        super().clean()
        # Destination must differ from source
        if self.from_department_id and self.to_department_id:
            if self.from_department_id == self.to_department_id and self.from_location_id == self.to_location_id:
                raise ValidationError({
                    'to_location': "Destination must differ from current origin department or location."
                })

        # Validate that destination location belongs to destination department if location has a department assigned
        if self.to_location and self.to_location.department_id and self.to_department_id:
            if self.to_location.department_id != self.to_department_id:
                raise ValidationError({
                    'to_location': f"Location '{self.to_location.name}' belongs to {self.to_location.department.name}, not {self.to_department.name}."
                })

    @property
    def is_open(self):
        return self.status in [self.Status.PENDING, self.Status.APPROVED]

    @property
    def is_completed(self):
        return self.status == self.Status.COMPLETED
