from decimal import Decimal
from django.db import models
from django.conf import settings
from django.core.validators import MinValueValidator
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.inventory.models import Asset


class AssetDisposal(models.Model):
    """
    Formal end-of-service lifecycle record for a durable physical asset.
    Tracks the disposal request, review/approval, and physical disposal execution.
    Never hard-deletes the asset — sets Asset.status to DISPOSED and preserves
    all historical records (assignments, transfers, borrowing, maintenance, verifications).
    """

    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Pending'
        APPROVED = 'APPROVED', 'Approved'
        COMPLETED = 'COMPLETED', 'Completed'
        REJECTED = 'REJECTED', 'Rejected'
        CANCELLED = 'CANCELLED', 'Cancelled'

    class DisposalMethod(models.TextChoices):
        SCRAP = 'SCRAP', 'Scrap / Recycling'
        DONATION = 'DONATION', 'Donation'
        TRANSFER_OUT = 'TRANSFER_OUT', 'Transfer to External Entity'
        AUCTION = 'AUCTION', 'Auction / Sale'
        DESTRUCTION = 'DESTRUCTION', 'Destruction / Write-off'
        OTHER = 'OTHER', 'Other'

    # === Identification ===
    disposal_number = models.CharField(
        max_length=50,
        unique=True,
        editable=False,
        db_index=True,
        help_text='Auto-generated unique disposal identifier (e.g. DSP-2026-00001)'
    )
    asset = models.ForeignKey(
        Asset,
        on_delete=models.PROTECT,
        related_name='disposal_records',
        help_text='The durable asset being disposed'
    )

    # === Request Phase ===
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='requested_disposals',
        help_text='Administrator who initiated the disposal request'
    )
    requested_at = models.DateTimeField(
        default=timezone.now,
        db_index=True
    )
    reason = models.TextField(
        help_text='Justification for disposal (e.g. irreparable, obsolete, condemned)'
    )

    # === Assessment / Recommendation ===
    recommended_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='recommended_disposals',
        help_text='User who recommended disposal (may differ from requester)'
    )
    maintenance_reference = models.ForeignKey(
        'maintenance.AssetMaintenance',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='disposal_records',
        help_text='Optional maintenance case that recommended this asset for replacement'
    )
    condition_at_disposal = models.CharField(
        max_length=20,
        choices=Asset.Condition.choices,
        help_text='Physical condition of the asset at time of disposal request'
    )

    # === Approval Phase ===
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
        related_name='reviewed_disposals',
        help_text='Administrator who approved or rejected the request'
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_remarks = models.TextField(
        blank=True,
        help_text='Approval or rejection notes'
    )

    # === Disposal Execution Phase ===
    disposal_method = models.CharField(
        max_length=20,
        choices=DisposalMethod.choices,
        blank=True,
        help_text='Method of physical disposal execution'
    )
    disposal_date = models.DateField(
        null=True,
        blank=True,
        help_text='Date when physical disposal was executed'
    )
    processed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='processed_disposals',
        help_text='Administrator who physically executed the disposal'
    )
    recipient_or_destination = models.CharField(
        max_length=300,
        blank=True,
        help_text='Recipient, buyer, or destination of the disposed asset'
    )
    reference_number = models.CharField(
        max_length=200,
        blank=True,
        help_text='Internal document or reference number associated with disposal'
    )
    proceeds_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal('0.00'))],
        help_text='Informational proceeds from sale/auction in PHP (not official accounting)'
    )
    remarks = models.TextField(blank=True)

    # === Timestamps ===
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text='Timestamp when disposal was marked COMPLETED'
    )

    class Meta:
        ordering = ['-requested_at', '-id']
        verbose_name = 'Asset Disposal'
        verbose_name_plural = 'Asset Disposals'
        indexes = [
            models.Index(fields=['status', 'asset']),
            models.Index(fields=['requested_at']),
            models.Index(fields=['disposal_date']),
        ]

    def __str__(self):
        return f"{self.disposal_number} - {self.asset.asset_code} ({self.get_status_display()})"

    @classmethod
    def generate_disposal_number(cls, year=None):
        """
        Generates a collision-safe sequential disposal identifier.
        Format: DSP-{YEAR}-{NUMBER:05d} (e.g. DSP-2026-00001).
        """
        if year is None:
            year = timezone.now().year
        prefix = f"DSP-{year}-"
        last_rec = cls.objects.filter(disposal_number__startswith=prefix).order_by('-disposal_number').first()
        if last_rec:
            try:
                last_num = int(last_rec.disposal_number.split('-')[-1])
                seq = last_num + 1
            except (ValueError, IndexError):
                seq = 1
        else:
            seq = 1

        new_code = f"{prefix}{seq:05d}"
        while cls.objects.filter(disposal_number=new_code).exists():
            seq += 1
            new_code = f"{prefix}{seq:05d}"
        return new_code

    def clean(self):
        super().clean()
        if self.proceeds_amount is not None and self.proceeds_amount < Decimal('0.00'):
            raise ValidationError({'proceeds_amount': 'Proceeds amount cannot be negative.'})

    def save(self, *args, **kwargs):
        self.clean()
        if not self.disposal_number:
            year = self.requested_at.year if self.requested_at else timezone.now().year
            self.disposal_number = self.generate_disposal_number(year=year)
        super().save(*args, **kwargs)

    @property
    def is_pending(self):
        return self.status == self.Status.PENDING

    @property
    def is_approved(self):
        return self.status == self.Status.APPROVED

    @property
    def is_completed(self):
        return self.status == self.Status.COMPLETED

    @property
    def is_terminal(self):
        """Returns True if disposal is in a final state."""
        return self.status in [self.Status.COMPLETED, self.Status.REJECTED, self.Status.CANCELLED]
