from django.db import models
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.urls import reverse
from django.utils import timezone
from decimal import Decimal
import uuid


def validate_asset_image(image):
    """Validate uploaded asset image: size, extension, and decodable content."""
    import os
    from PIL import Image as PILImage
    import io

    # 1. Size check: max 5MB
    max_size_mb = 5
    if image.size > max_size_mb * 1024 * 1024:
        raise ValidationError(f"Image file size must not exceed {max_size_mb} MB.")

    # 2. Extension check
    ALLOWED_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp'}
    ext = os.path.splitext(image.name)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ValidationError(
            f"Unsupported file extension '{ext}'. Allowed: JPEG, PNG, WebP."
        )

    # 3. Attempt to decode as image (prevents disguised files)
    try:
        image.seek(0)
        img = PILImage.open(io.BytesIO(image.read()))
        img.verify()
    except Exception:
        raise ValidationError("The uploaded file could not be decoded as a valid image.")
    finally:
        try:
            image.seek(0)
        except Exception:
            pass


class AssetCategory(models.Model):
    name = models.CharField(max_length=200, unique=True)
    code = models.CharField(max_length=10, unique=True, help_text='Short code for asset numbering, e.g. IT, FN, OE')
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    is_reservable = models.BooleanField(
        default=True,
        help_text='Designates whether equipment in this category can be reserved by students.'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = 'Asset Categories'
        ordering = ['name']

    def __str__(self):
        return self.name


class Brand(models.Model):
    name = models.CharField(max_length=200, unique=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class Asset(models.Model):
    class Condition(models.TextChoices):
        NEW = 'NEW', 'New'
        GOOD = 'GOOD', 'Good'
        FAIR = 'FAIR', 'Fair'
        POOR = 'POOR', 'Poor'
        UNSERVICEABLE = 'UNSERVICEABLE', 'Unserviceable'

    class Status(models.TextChoices):
        AVAILABLE = 'AVAILABLE', 'Available'
        ASSIGNED = 'ASSIGNED', 'Assigned'
        BORROWED = 'BORROWED', 'Borrowed'
        MAINTENANCE = 'MAINTENANCE', 'Under Maintenance'
        DAMAGED = 'DAMAGED', 'Damaged'
        LOST = 'LOST', 'Lost'
        TRANSFERRED = 'TRANSFERRED', 'Transferred'
        DISPOSED = 'DISPOSED', 'Disposed'

    uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    asset_code = models.CharField(max_length=50, unique=True, editable=False, db_index=True)
    property_number = models.CharField(
        max_length=100,
        blank=True,
        help_text='Government/institution property number (e.g. NORSU-CBA-2026-00482)'
    )
    item_name = models.CharField(max_length=300)
    category = models.ForeignKey(AssetCategory, on_delete=models.PROTECT, related_name='assets')
    brand = models.ForeignKey(Brand, on_delete=models.SET_NULL, null=True, blank=True, related_name='assets')
    model = models.CharField(max_length=200, blank=True)
    serial_number = models.CharField(max_length=200, blank=True, help_text='Leave blank if not applicable')
    description = models.TextField(blank=True)
    acquisition_date = models.DateField(null=True, blank=True)
    acquisition_cost = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal('0.00'))],
        help_text='Acquisition cost in PHP'
    )
    supplier = models.CharField(max_length=300, blank=True)
    department = models.ForeignKey('organizations.Department', on_delete=models.PROTECT, related_name='assets')
    current_location = models.ForeignKey(
        'organizations.Location',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assets'
    )
    condition = models.CharField(max_length=20, choices=Condition.choices, default=Condition.NEW)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.AVAILABLE)
    is_reservable = models.BooleanField(
        default=True,
        help_text='Designates whether this specific physical asset can be reserved by students.'
    )
    asset_image = models.ImageField(
        upload_to='assets/%Y/%m/',
        null=True,
        blank=True,
        validators=[validate_asset_image],
        help_text='Primary photograph or label image (Max 5MB)'
    )
    remarks = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_assets'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['property_number'],
                condition=models.Q(property_number__isnull=False) & ~models.Q(property_number=''),
                name='unique_non_empty_property_number'
            )
        ]
        indexes = [
            models.Index(fields=['status'], name='inventory_a_status_idx'),
            models.Index(fields=['department', 'status'], name='inventory_a_dept_stat_idx'),
        ]


    def __str__(self):
        return f'{self.asset_code} - {self.item_name}'

    def clean(self):
        super().clean()
        if self.property_number:
            self.property_number = self.property_number.strip()
            qs = Asset.objects.filter(property_number__iexact=self.property_number)
            if self.pk:
                qs = qs.exclude(pk=self.pk)
            if qs.exists():
                raise ValidationError({
                    'property_number': f"An asset with property number '{self.property_number}' already exists."
                })

    def save(self, *args, **kwargs):
        # Keep asset_code stable on updates; only generate if not set
        if not self.asset_code:
            self.asset_code = self._generate_asset_code()
        super().save(*args, **kwargs)

    def _generate_asset_code(self):
        category_code = (self.category.code if self.category else 'GEN').upper().strip()
        prefix = f'CBA-{category_code}'
        
        # Query existing codes matching prefix to find highest number
        existing_codes = Asset.objects.filter(
            asset_code__startswith=prefix
        ).values_list('asset_code', flat=True)

        max_num = 0
        for code in existing_codes:
            try:
                num = int(code.split('-')[-1])
                if num > max_num:
                    max_num = num
            except (ValueError, IndexError):
                continue

        next_num = max_num + 1
        new_code = f'{prefix}-{next_num:05d}'
        
        # Ensure no collision in database
        while Asset.objects.filter(asset_code=new_code).exists():
            next_num += 1
            new_code = f'{prefix}-{next_num:05d}'

        return new_code

    def get_absolute_url(self):
        return reverse('inventory:asset_detail', kwargs={'asset_code': self.asset_code})

    @property
    def latest_verification(self):
        """Returns the most recent physical verification record."""
        return self.verifications.first()

    @property
    def last_verified_at(self):
        """Returns the datetime of the most recent physical verification."""
        v = self.latest_verification
        return v.verified_at if v else None


class AssetVerification(models.Model):
    """
    Historical physical inventory verification record.
    Captures snapshots of expected vs observed location and condition.
    Does NOT alter canonical asset state automatically.
    """
    class VerificationResult(models.TextChoices):
        VERIFIED = 'VERIFIED', 'Verified'
        LOCATION_MISMATCH = 'LOCATION_MISMATCH', 'Location Mismatch'
        CONDITION_MISMATCH = 'CONDITION_MISMATCH', 'Condition Mismatch'
        LOCATION_AND_CONDITION_MISMATCH = 'LOCATION_AND_CONDITION_MISMATCH', 'Location and Condition Mismatch'

    asset = models.ForeignKey(
        Asset,
        on_delete=models.PROTECT,
        related_name='verifications'
    )
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='conducted_verifications'
    )
    verified_at = models.DateTimeField(default=timezone.now, db_index=True)

    # Snapshot of system expected state at verification time
    expected_department = models.ForeignKey(
        'organizations.Department',
        on_delete=models.PROTECT,
        related_name='expected_verifications'
    )
    expected_location = models.ForeignKey(
        'organizations.Location',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='expected_verifications'
    )
    expected_condition = models.CharField(
        max_length=20,
        choices=Asset.Condition.choices
    )

    # Physical state observed by verifier
    observed_department = models.ForeignKey(
        'organizations.Department',
        on_delete=models.PROTECT,
        related_name='observed_verifications'
    )
    observed_location = models.ForeignKey(
        'organizations.Location',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='observed_verifications'
    )
    observed_condition = models.CharField(
        max_length=20,
        choices=Asset.Condition.choices
    )

    result = models.CharField(
        max_length=40,
        choices=VerificationResult.choices,
        db_index=True
    )
    remarks = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-verified_at', '-created_at']
        verbose_name = 'Asset Verification'
        verbose_name_plural = 'Asset Verifications'
        indexes = [
            models.Index(fields=['asset', '-verified_at']),
            models.Index(fields=['result']),
        ]

    def __str__(self):
        return f"{self.asset.asset_code} - {self.get_result_display()} ({self.verified_at:%Y-%m-%d})"

    @staticmethod
    def calculate_result(expected_dept, expected_loc, expected_cond, observed_dept, observed_loc, observed_cond):
        """Calculates verification outcome based on expected vs observed values."""
        loc_match = (expected_dept == observed_dept) and (expected_loc == observed_loc)
        cond_match = (expected_cond == observed_cond)
        if loc_match and cond_match:
            return AssetVerification.VerificationResult.VERIFIED
        elif not loc_match and cond_match:
            return AssetVerification.VerificationResult.LOCATION_MISMATCH
        elif loc_match and not cond_match:
            return AssetVerification.VerificationResult.CONDITION_MISMATCH
        else:
            return AssetVerification.VerificationResult.LOCATION_AND_CONDITION_MISMATCH

