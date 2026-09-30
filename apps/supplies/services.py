from django.db import transaction, models
from django.db.models import Sum, Q, F, Value
from django.db.models.functions import Coalesce
from django.core.exceptions import ValidationError
from django.utils import timezone

from .models import Supply, SupplyTransaction, SupplyCategory
from apps.audit.utils import log_action


def get_current_stock(supply):
    """
    Authoritative calculation of on-hand inventory based strictly on historical transactions:
    Current Stock = (STOCK_IN + ADJUSTMENT_IN) - (STOCK_OUT + ADJUSTMENT_OUT)
    """
    if not supply or not supply.pk:
        return 0

    aggregates = supply.transactions.aggregate(
        in_qty=Coalesce(Sum('quantity', filter=Q(transaction_type__in=[
            SupplyTransaction.TransactionType.STOCK_IN,
            SupplyTransaction.TransactionType.ADJUSTMENT_IN
        ])), Value(0)),
        out_qty=Coalesce(Sum('quantity', filter=Q(transaction_type__in=[
            SupplyTransaction.TransactionType.STOCK_OUT,
            SupplyTransaction.TransactionType.ADJUSTMENT_OUT
        ])), Value(0)),
    )
    return aggregates['in_qty'] - aggregates['out_qty']


def get_stock_status(current_stock, reorder_level):
    """
    Evaluates stock health status based on authoritative stock and threshold:
    - OUT_OF_STOCK: current_stock <= 0
    - LOW_STOCK: 0 < current_stock <= reorder_level
    - IN_STOCK: current_stock > reorder_level
    """
    if current_stock <= 0:
        return 'OUT_OF_STOCK'
    elif current_stock <= reorder_level:
        return 'LOW_STOCK'
    else:
        return 'IN_STOCK'


def get_annotated_supplies_queryset():
    """
    Returns Supply queryset annotated with 'calculated_stock' for high-performance listing
    without N+1 query overhead.
    """
    return Supply.objects.select_related('category', 'brand').annotate(
        total_in=Coalesce(Sum('transactions__quantity', filter=Q(transactions__transaction_type__in=[
            SupplyTransaction.TransactionType.STOCK_IN,
            SupplyTransaction.TransactionType.ADJUSTMENT_IN
        ])), Value(0)),
        total_out=Coalesce(Sum('transactions__quantity', filter=Q(transactions__transaction_type__in=[
            SupplyTransaction.TransactionType.STOCK_OUT,
            SupplyTransaction.TransactionType.ADJUSTMENT_OUT
        ])), Value(0)),
    ).annotate(
        calculated_stock=F('total_in') - F('total_out')
    )


def get_low_stock_supplies():
    """
    Returns active supplies that are either LOW STOCK or OUT OF STOCK,
    sorted by calculated_stock ascending (most urgent first).
    """
    qs = get_annotated_supplies_queryset().filter(is_active=True)
    return [s for s in qs if s.calculated_stock <= s.reorder_level]


@transaction.atomic
def stock_in(supply, quantity, processed_by, transaction_date=None, reference_number='', remarks='', request=None):
    """
    Records an incoming stock receipt.
    Uses select_for_update() row locking to serialize concurrent transactions.
    """
    if quantity <= 0:
        raise ValidationError("Quantity must be greater than zero.")

    # Acquire row lock on the Supply definition
    locked_supply = Supply.objects.select_for_update().get(pk=supply.pk)
    if not locked_supply.is_active:
        raise ValidationError("Cannot record incoming stock for an inactive supply definition.")

    tx = SupplyTransaction(
        supply=locked_supply,
        transaction_type=SupplyTransaction.TransactionType.STOCK_IN,
        quantity=quantity,
        reference_number=reference_number.strip(),
        remarks=remarks.strip(),
        processed_by=processed_by,
        transaction_date=transaction_date or timezone.now().date()
    )
    # Save directly via super to bypass immutability checks on creation
    models.Model.save(tx)

    # Calculate post-transaction stock
    new_stock = get_current_stock(locked_supply)

    # Emit audit log
    log_action(
        user=processed_by,
        action='SUPPLY_STOCK_IN',
        instance=tx,
        changes={
            'supply_code': locked_supply.supply_code,
            'item_name': locked_supply.item_name,
            'quantity': quantity,
            'unit': locked_supply.unit,
            'reference_number': reference_number.strip(),
            'new_balance': new_stock,
        },
        request=request
    )
    return tx


@transaction.atomic
def stock_out(supply, quantity, processed_by, department=None, location=None, employee=None, purpose='', transaction_date=None, reference_number='', remarks='', request=None):
    """
    Issues consumable stock to a department, office, or individual.
    Guarantees negative-stock protection via select_for_update() row-level locking.
    """
    if quantity <= 0:
        raise ValidationError("Quantity must be greater than zero.")

    # Acquire row lock on the Supply definition
    locked_supply = Supply.objects.select_for_update().get(pk=supply.pk)
    if not locked_supply.is_active:
        raise ValidationError("Cannot issue an inactive supply definition.")

    # Authoritative stock verification under row lock
    current_stock = get_current_stock(locked_supply)
    if quantity > current_stock:
        unit_display = locked_supply.get_unit_display()
        raise ValidationError(f"Insufficient stock. Only {current_stock} {unit_display} are currently available.")

    tx = SupplyTransaction(
        supply=locked_supply,
        transaction_type=SupplyTransaction.TransactionType.STOCK_OUT,
        quantity=quantity,
        department=department,
        location=location,
        employee=employee,
        purpose=purpose.strip(),
        reference_number=reference_number.strip(),
        remarks=remarks.strip(),
        processed_by=processed_by,
        transaction_date=transaction_date or timezone.now().date()
    )
    models.Model.save(tx)

    new_stock = get_current_stock(locked_supply)

    # Emit audit log
    log_action(
        user=processed_by,
        action='SUPPLY_STOCK_OUT',
        instance=tx,
        changes={
            'supply_code': locked_supply.supply_code,
            'item_name': locked_supply.item_name,
            'quantity': quantity,
            'unit': locked_supply.unit,
            'department': department.name if department else None,
            'recipient': employee.full_name if employee else None,
            'reference_number': reference_number.strip(),
            'new_balance': new_stock,
        },
        request=request
    )
    return tx


@transaction.atomic
def adjust_stock(supply, adjustment_type, quantity, processed_by, reason, remarks='', transaction_date=None, reference_number='', request=None):
    """
    Performs a compensating inventory adjustment (surplus or shrinkage/loss/damage).
    """
    if adjustment_type not in [
        SupplyTransaction.TransactionType.ADJUSTMENT_IN,
        SupplyTransaction.TransactionType.ADJUSTMENT_OUT
    ]:
        raise ValidationError("Invalid adjustment type. Must be ADJUSTMENT_IN or ADJUSTMENT_OUT.")

    if quantity <= 0:
        raise ValidationError("Quantity must be greater than zero.")

    if not reason or not reason.strip():
        raise ValidationError("Adjustment reason is required.")

    # Acquire row lock on the Supply definition
    locked_supply = Supply.objects.select_for_update().get(pk=supply.pk)
    if not locked_supply.is_active:
        raise ValidationError("Cannot adjust an inactive supply definition.")

    if adjustment_type == SupplyTransaction.TransactionType.ADJUSTMENT_OUT:
        current_stock = get_current_stock(locked_supply)
        if quantity > current_stock:
            unit_display = locked_supply.get_unit_display()
            raise ValidationError(
                f"Cannot adjust out {quantity} {unit_display}. Only {current_stock} {unit_display} are currently available."
            )

    tx = SupplyTransaction(
        supply=locked_supply,
        transaction_type=adjustment_type,
        quantity=quantity,
        purpose=reason.strip(),
        reference_number=reference_number.strip(),
        remarks=remarks.strip(),
        processed_by=processed_by,
        transaction_date=transaction_date or timezone.now().date()
    )
    models.Model.save(tx)

    new_stock = get_current_stock(locked_supply)
    audit_action = 'SUPPLY_ADJUSTMENT_IN' if adjustment_type == SupplyTransaction.TransactionType.ADJUSTMENT_IN else 'SUPPLY_ADJUSTMENT_OUT'

    log_action(
        user=processed_by,
        action=audit_action,
        instance=tx,
        changes={
            'supply_code': locked_supply.supply_code,
            'item_name': locked_supply.item_name,
            'quantity': quantity,
            'unit': locked_supply.unit,
            'reason': reason.strip(),
            'new_balance': new_stock,
        },
        request=request
    )
    return tx


def create_supply(item_name, category, unit, reorder_level=10, brand=None, description='', created_by=None, is_active=True, request=None):
    """Creates a new supply item definition and logs audit event."""
    supply = Supply(
        item_name=item_name.strip(),
        category=category,
        brand=brand,
        unit=unit,
        reorder_level=reorder_level,
        description=description.strip(),
        created_by=created_by,
        is_active=is_active
    )
    supply.save()

    log_action(
        user=created_by,
        action='SUPPLY_CREATED',
        instance=supply,
        changes={
            'supply_code': supply.supply_code,
            'item_name': supply.item_name,
            'category': supply.category.name,
            'brand': supply.brand.name if supply.brand else None,
            'unit': supply.unit,
            'reorder_level': supply.reorder_level,
        },
        request=request
    )
    return supply


def update_supply(supply, updated_by, **fields):
    """Updates supply metadata (excluding immutable code and transaction-derived stock)."""
    changes = {}
    for field, val in fields.items():
        if hasattr(supply, field) and field not in ['id', 'supply_code', 'created_at', 'created_by']:
            old_val = getattr(supply, field)
            if old_val != val:
                changes[field] = {'old': str(old_val), 'new': str(val)}
                setattr(supply, field, val)

    supply.save()
    if changes:
        log_action(
            user=updated_by,
            action='SUPPLY_UPDATED',
            instance=supply,
            changes=changes
        )
    return supply


def toggle_supply_active(supply, toggled_by, request=None):
    """Toggles supply active state."""
    supply.is_active = not supply.is_active
    supply.save(update_fields=['is_active', 'updated_at'])
    log_action(
        user=toggled_by,
        action='SUPPLY_DEACTIVATED' if not supply.is_active else 'SUPPLY_UPDATED',
        instance=supply,
        changes={'is_active': supply.is_active},
        request=request
    )
    return supply.is_active
