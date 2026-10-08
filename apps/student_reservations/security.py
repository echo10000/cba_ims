from django.core.cache import cache
from django.core.exceptions import ValidationError
from .models import StudentReservation


def get_client_ip(request):
    """Safely extracts client IP address from HTTP request."""
    if not request:
        return '127.0.0.1'
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        return x_forwarded_for.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', '127.0.0.1')


def check_submission_rate_limit(request, student_id, max_per_window=5, window_seconds=600):
    """
    Applies basic rate limiting to public reservation submissions.
    - Limits requests by client IP (default max 5 requests per 10 minutes).
    - Prevents single student ID from flooding with > 3 concurrent pending requests.
    Raises ValidationError if rate limit exceeded.
    """
    # 1. IP rate limit check via cache
    ip = get_client_ip(request)
    cache_key = f"sr_rate_limit_ip_{ip}"
    current_count = cache.get(cache_key, 0)

    if current_count >= max_per_window:
        raise ValidationError(
            "Too many reservation attempts from your network. Please wait a few minutes before submitting again."
        )

    # 2. Prevent spamming multiple pending requests for same student ID
    if student_id:
        pending_count = StudentReservation.objects.filter(
            student_id=str(student_id).strip(),
            status=StudentReservation.Status.PENDING
        ).count()
        if pending_count >= 3:
            raise ValidationError(
                f"Student ID '{student_id}' already has {pending_count} pending reservations awaiting approval. "
                f"Please wait for Property Custodian review before submitting additional requests."
            )

    # Increment IP count
    cache.set(cache_key, current_count + 1, timeout=window_seconds)


def mask_contact_info(email, phone):
    """
    Masks student contact information for public responses to protect student privacy.
    Example: j****@example.com, 0917****567
    """
    masked_email = email
    if email and '@' in email:
        user_part, domain_part = email.split('@', 1)
        if len(user_part) <= 2:
            masked_email = f"{user_part[0]}***@{domain_part}"
        else:
            masked_email = f"{user_part[:2]}***{user_part[-1]}@{domain_part}"

    masked_phone = phone
    if phone:
        cleaned = str(phone).strip()
        if len(cleaned) > 4:
            masked_phone = f"{cleaned[:4]}****{cleaned[-3:]}"
        else:
            masked_phone = "****"

    return masked_email, masked_phone
