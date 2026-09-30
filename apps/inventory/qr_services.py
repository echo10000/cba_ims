import io
import base64
import qrcode
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from .models import Asset, AssetVerification
from apps.audit.utils import log_action


def get_asset_qr_url(asset, request=None):
    """
    Returns canonical QR payload URL pointing to the asset lookup route.
    Example: https://institution.edu/q/assets/CBA-IT-00001/
    Or relative: /q/assets/CBA-IT-00001/
    """
    path = reverse('qr_asset_lookup', kwargs={'asset_code': asset.asset_code})
    if request:
        return request.build_absolute_uri(path)
    return path


def generate_qr_image_bytes(data, box_size=8, border=2):
    """
    Generates a deterministic PNG QR code image as bytes.
    Uses medium error correction (approx 15% damage recovery).
    """
    qr = qrcode.QRCode(
        version=None,  # Automatic version based on data size
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=box_size,
        border=border,
    )
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")

    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return buffer.getvalue()


def generate_asset_qr_image(asset, request=None, box_size=8, border=2):
    """Generates PNG bytes for the given asset's canonical lookup URL."""
    payload = get_asset_qr_url(asset, request=request)
    return generate_qr_image_bytes(payload, box_size=box_size, border=border)


def generate_asset_qr_data_uri(asset, request=None, box_size=8, border=2):
    """
    Generates a base64 data URI for inline embedding in HTML templates
    (e.g., printable labels and asset detail cards) without disk storage or extra HTTP requests.
    """
    img_bytes = generate_asset_qr_image(asset, request=request, box_size=box_size, border=border)
    b64_str = base64.b64encode(img_bytes).decode('ascii')
    return f"data:image/png;base64,{b64_str}"


@transaction.atomic
def verify_asset(asset, verified_by, observed_department, observed_location, observed_condition, remarks='', request=None):
    """
    Records a physical inventory verification snapshot for a durable asset.
    Compares expected state against physically observed state and computes result.
    Does NOT modify canonical asset state automatically (transfer/condition updates are deliberate workflows).
    """
    # 1. Snapshot expected state from the database
    expected_dept = asset.department
    expected_loc = asset.current_location
    expected_cond = asset.condition

    # 2. Compute verification result
    result = AssetVerification.calculate_result(
        expected_dept=expected_dept,
        expected_loc=expected_loc,
        expected_cond=expected_cond,
        observed_dept=observed_department,
        observed_loc=observed_location,
        observed_cond=observed_condition,
    )

    # 3. Create historical verification record
    verification = AssetVerification.objects.create(
        asset=asset,
        verified_by=verified_by,
        verified_at=timezone.now(),
        expected_department=expected_dept,
        expected_location=expected_loc,
        expected_condition=expected_cond,
        observed_department=observed_department,
        observed_location=observed_location,
        observed_condition=observed_condition,
        result=result,
        remarks=remarks.strip(),
    )

    # 4. Write immutable audit log
    log_action(
        user=verified_by,
        action='ASSET_VERIFIED',
        instance=verification,
        changes={
            'asset_code': asset.asset_code,
            'item_name': asset.item_name,
            'result': result,
            'expected_department': expected_dept.name if expected_dept else None,
            'expected_location': expected_loc.name if expected_loc else None,
            'expected_condition': expected_cond,
            'observed_department': observed_department.name if observed_department else None,
            'observed_location': observed_location.name if observed_location else None,
            'observed_condition': observed_condition,
            'remarks': remarks.strip(),
        },
        request=request
    )

    return verification
