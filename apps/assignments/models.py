from django.db import models
from django.conf import settings
from django.utils import timezone
from apps.inventory.models import Asset


class AssetAssignment(models.Model):
    class Status(models.TextChoices):
        ACTIVE = 'ACTIVE', 'Active'
        RETURNED = 'RETURNED', 'Returned'

    asset = models.ForeignKey(
        'inventory.Asset',
        on_delete=models.PROTECT,
        related_name='assignments',
        help_text='Physical asset being assigned'
    )
    employee = models.ForeignKey(
        'organizations.Employee',
        on_delete=models.PROTECT,
        related_name='assignments',
        help_text='Accountable faculty member or staff'
    )
    assigned_date = models.DateField(
        default=timezone.now,
        help_text='Date accountability took effect'
    )
    expected_return_date = models.DateField(
        null=True,
        blank=True,
        help_text='Anticipated return date if temporary'
    )
    returned_date = models.DateField(
        null=True,
        blank=True,
        help_text='Actual date asset was returned and released'
    )
    purpose = models.CharField(
        max_length=300,
        blank=True,
        help_text='Official purpose (e.g. Instruction, Research, Administrative)'
    )
    condition_at_assignment = models.CharField(
        max_length=20,
        choices=Asset.Condition.choices,
        help_text='Condition snapshot at time of turnover'
    )
    condition_at_return = models.CharField(
        max_length=20,
        choices=Asset.Condition.choices,
        null=True,
        blank=True,
        help_text='Condition snapshot upon return'
    )
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='administered_assignments',
        help_text='Custodian/Admin who processed assignment'
    )
    returned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='received_returns',
        help_text='Custodian/Admin who received return'
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.ACTIVE,
        db_index=True
    )
    remarks = models.TextField(
        blank=True,
        help_text='Operational notes or accession remarks'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-assigned_date', '-created_at']
        constraints = [
            # Ensure an asset never has more than one active assignment simultaneously
            models.UniqueConstraint(
                fields=['asset'],
                condition=models.Q(status='ACTIVE'),
                name='unique_active_assignment_per_asset'
            )
        ]

    def __str__(self):
        return f"{self.asset.asset_code} -> {self.employee.full_name} ({self.status})"

    @property
    def is_active(self):
        return self.status == self.Status.ACTIVE
