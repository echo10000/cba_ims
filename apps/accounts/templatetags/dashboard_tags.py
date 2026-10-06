import re
from django import template

register = template.Library()

ACTION_LABELS = {
    'MAINTENANCE_REPAIR_STARTED': 'Maintenance repair started',
    'MAINTENANCE_ASSESSED': 'Maintenance assessment completed',
    'MAINTENANCE_REPORTED': 'Maintenance defect reported',
    'MAINTENANCE_COMPLETED': 'Maintenance repair completed',
    'MAINTENANCE_FOR_REPLACEMENT': 'Equipment marked for replacement',
    'ASSET_VERIFIED': 'Physical verification recorded',
    'SUPPLY_STOCK_IN': 'Consumable stock received',
    'SUPPLY_STOCK_OUT': 'Consumable stock issued',
    'SUPPLY_ADJUSTMENT_OUT': 'Stock inventory adjusted',
    'TRANSFER_REQUESTED': 'Asset transfer requested',
    'TRANSFER_APPROVED': 'Asset transfer approved',
    'TRANSFER_REJECTED': 'Asset transfer rejected',
    'TRANSFER_COMPLETED': 'Asset transfer completed',
    'TRANSFER_CANCELLED': 'Asset transfer cancelled',
    'ASSET_ASSIGNED': 'Asset assigned to custodian',
    'ASSET_RETURNED': 'Asset returned to custody',
    'ASSET_CREATED': 'New asset registered',
    'ASSET_UPDATED': 'Asset record updated',
    'ASSET_DELETED': 'Asset record removed',
    'BORROWING_REQUESTED': 'Equipment loan requested',
    'BORROWING_APPROVED': 'Equipment loan approved',
    'BORROWING_RETURNED': 'Equipment loan returned',
    'DISPOSAL_REQUESTED': 'Disposal review requested',
    'DISPOSAL_APPROVED': 'Disposal approved',
    'SEEDED': 'Initial database setup',
}

@register.filter(name='humanize_action')
def humanize_action(action):
    """Convert raw uppercase or underscored audit action strings into natural sentence case."""
    if not action:
        return 'System update'
    upper = str(action).upper().strip()
    if upper in ACTION_LABELS:
        return ACTION_LABELS[upper]
    # General fallback: replace underscores with spaces and capitalize sentence
    cleaned = upper.replace('_', ' ').strip().lower()
    return cleaned.capitalize() if cleaned else 'System update'

@register.filter(name='clean_entity_label')
def clean_entity_label(object_repr, model_name=''):
    """Format object repr into human readable asset/entity reference (e.g. 'Asset CBA-IT-00007')."""
    if not object_repr:
        return 'System Record'
    text = str(object_repr)
    # Check for CBA asset tags (e.g., CBA-IT-00007, CBA-COMP-00001, CBA-FUR-00001)
    match = re.search(r'(CBA-[A-Za-z0-9-]+)', text)
    if match:
        return f"Asset {match.group(1)}"
    # Remove trailing status like (In Repair), (Reported)
    clean = re.sub(r'\s*\([^)]*\)$', '', text).strip()
    return clean if clean else text

@register.filter(name='action_badge_theme')
def action_badge_theme(action):
    """Return a semantic color theme class for the action badge."""
    upper = str(action).upper()
    if any(k in upper for k in ['COMPLETED', 'VERIFIED', 'APPROVED', 'CREATED', 'RETURNED', 'STOCK_IN']):
        return 'badge-theme-success'
    if any(k in upper for k in ['REPAIR', 'ASSESSED', 'REPORTED', 'REQUESTED', 'STOCK_OUT', 'ADJUSTMENT']):
        return 'badge-theme-warning'
    if any(k in upper for k in ['DELETED', 'REJECTED', 'CANCELLED', 'REPLACEMENT', 'DISPOSAL']):
        return 'badge-theme-danger'
    return 'badge-theme-info'
