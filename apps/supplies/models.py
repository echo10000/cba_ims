from django.db import models
from django.conf import settings
from django.core.validators import MinValueValidator
from django.urls import reverse
from django.utils import timezone


def generate_supply_code(category_code):
    """
    Generates a unique, collision-safe supply code.
    Format: CBA-SUP-{CAT}-{NUMBER:05d}, e.g. CBA-SUP-PAPER-00001
    """
    clean_cat = (category_code or 'GEN').upper().strip()
    prefix = f"CBA-SUP-{clean_cat}-"
    
    last_supply = Supply.objects.filter(supply_code__startswith=prefix).order_by('-supply_code').first()
    if last_supply:
        try:
            last_num = int(last_supply.supply_code.split('-')[-1])
            new_num = last_num + 1
        except (ValueError, IndexError):
            new_num = 1
    else:
        new_num = 1

    code = f"{prefix}{new_num:05d}"
    while Supply.objects.filter(supply_code=code).exists():
        new_num += 1
        code = f"{prefix}{new_num:05d}"
    return code


class SupplyCategory(models.Model):
    """
    Categorization specific to consumable materials (paper, ink, office supplies).
    Completely separate from durable AssetCategory.
    """
    name = models.CharField(max_length=100, unique=True)
    code = models.CharField(
        max_length=20,
        unique=True,
        help_text='Unique uppercase category code, e.g. PAPER, WRITE, PRINT, OFFICE, CLEAN'
    )
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Supply Category'
        verbose_name_plural = 'Supply Categories'
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.code})"

    def clean(self):
        super().clean()
        if self.code:
            self.code = self.code.upper().strip()

    def save(self, *args, **kwargs):
        if self.code:
            self.code = self.code.upper().strip()
        super().save(*args, **kwargs)


class Supply(models.Model):
    """
    Consumable supply definition.
    Stock balance is strictly derived from historical SupplyTransaction records.
    """
    class Unit(models.TextChoices):
        PIECE = 'PIECE', 'Piece'
        BOX = 'BOX', 'Box'
        PACK = 'PACK', 'Pack'
        REAM = 'REAM', 'Ream'
        BOTTLE = 'BOTTLE', 'Bottle'
        CARTRIDGE = 'CARTRIDGE', 'Cartridge'
        ROLL = 'ROLL', 'Roll'
        SET = 'SET', 'Set'
        LITER = 'LITER', 'Liter'
        KILOGRAM = 'KILOGRAM', 'Kilogram'

    supply_code = models.CharField(
        max_length=50,
        unique=True,
        editable=False,
        db_index=True,
        help_text='Auto-generated unique code, e.g. CBA-SUP-PAPER-00001'
    )
    item_name = models.CharField(max_length=200, db_index=True)
    category = models.ForeignKey(
        SupplyCategory,
        on_delete=models.PROTECT,
        related_name='supplies'
    )
    brand = models.ForeignKey(
        'inventory.Brand',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='supplies'
    )
    description = models.TextField(blank=True)
    unit = models.CharField(max_length=20, choices=Unit.choices, default=Unit.PIECE)
    reorder_level = models.PositiveIntegerField(
        default=10,
        validators=[MinValueValidator(0)],
        help_text='Threshold quantity that triggers low-stock warning (must be >= 0)'
    )
    is_active = models.BooleanField(default=True, db_index=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='created_supplies'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Supply'
        verbose_name_plural = 'Supplies'
        ordering = ['item_name']

    def __str__(self):
        return f"{self.supply_code} - {self.item_name}"

    def save(self, *args, **kwargs):
        if not self.supply_code:
            cat_code = self.category.code if self.category else 'GEN'
            self.supply_code = generate_supply_code(cat_code)
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse('supplies:supply_detail', kwargs={'supply_code': self.supply_code})

    @property
    def current_stock(self):
        """Authoritative transaction-derived stock balance."""
        from . import services
        return services.get_current_stock(self)

    @property
    def stock_status(self):
        """IN_STOCK, LOW_STOCK, or OUT_OF_STOCK."""
        from . import services
        return services.get_stock_status(self.current_stock, self.reorder_level)

    @property
    def is_low_stock(self):
        return self.current_stock <= self.reorder_level


class SupplyTransaction(models.Model):
    """
    Immutable transaction record representing stock additions, issuances, or adjustments.
    Historical transactions cannot be edited or deleted once posted.
    """
    class TransactionType(models.TextChoices):
        STOCK_IN = 'STOCK_IN', 'Stock In'
        STOCK_OUT = 'STOCK_OUT', 'Stock Out'
        ADJUSTMENT_IN = 'ADJUSTMENT_IN', 'Adjustment In (Count Surplus)'
        ADJUSTMENT_OUT = 'ADJUSTMENT_OUT', 'Adjustment Out (Damage / Loss / Correction)'

    supply = models.ForeignKey(
        Supply,
        on_delete=models.PROTECT,
        related_name='transactions'
    )
    transaction_type = models.CharField(
        max_length=20,
        choices=TransactionType.choices,
        db_index=True
    )
    quantity = models.PositiveIntegerField(
        validators=[MinValueValidator(1)],
        help_text='Transaction quantity (must be strictly greater than 0)'
    )
    department = models.ForeignKey(
        'organizations.Department',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='supply_transactions',
        db_index=True,
        help_text='Recipient department for stock issuance'
    )
    location = models.ForeignKey(
        'organizations.Location',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='supply_transactions',
        help_text='Destination office/room for stock issuance'
    )
    employee = models.ForeignKey(
        'organizations.Employee',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='supply_issuances',
        db_index=True,
        help_text='Receiving staff/faculty member'
    )
    reference_number = models.CharField(
        max_length=100,
        blank=True,
        help_text='Delivery receipt, issuance slip, or audit correction reference'
    )
    purpose = models.TextField(blank=True, help_text='Intended use or allocation justification')
    remarks = models.TextField(blank=True, help_text='Additional notes or adjustment rationale')
    processed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='processed_supply_transactions'
    )
    transaction_date = models.DateField(default=timezone.now, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Supply Transaction'
        verbose_name_plural = 'Supply Transactions'
        ordering = ['-transaction_date', '-created_at']
        indexes = [
            models.Index(fields=['supply', 'transaction_type', 'transaction_date']),
        ]

    def __str__(self):
        return f"{self.get_transaction_type_display()} - {self.supply.supply_code} ({self.quantity} {self.supply.get_unit_display()})"

    def delete(self, *args, **kwargs):
        """Prevent deletion of historical stock transactions."""
        raise PermissionError("Historical stock transactions cannot be deleted. Use a compensating adjustment instead.")

    def save(self, *args, **kwargs):
        """Prevent modification of already posted stock transactions."""
        if self.pk:
            raise PermissionError("Historical stock transactions cannot be modified. Use a compensating adjustment instead.")
        super().save(*args, **kwargs)

    @property
    def signed_quantity(self):
        """Returns signed quantity (+/-) based on transaction type."""
        if self.transaction_type in [self.TransactionType.STOCK_IN, self.TransactionType.ADJUSTMENT_IN]:
            return self.quantity
        return -self.quantity

    @property
    def is_incoming(self):
        return self.transaction_type in [self.TransactionType.STOCK_IN, self.TransactionType.ADJUSTMENT_IN]

    @property
    def is_outgoing(self):
        return self.transaction_type in [self.TransactionType.STOCK_OUT, self.TransactionType.ADJUSTMENT_OUT]
