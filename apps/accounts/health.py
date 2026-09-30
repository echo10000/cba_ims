from django.http import JsonResponse
from django.db import connection
from django.db.utils import OperationalError


def health_check(request):
    """
    Minimal health check endpoint.
    Returns HTTP 200 with {"status": "ok"} when the database is reachable.
    Returns HTTP 503 with {"status": "error"} when the database is unreachable.
    Does not expose server internals, credentials, or configuration.
    """
    try:
        connection.ensure_connection()
        db_ok = True
    except OperationalError:
        db_ok = False

    if db_ok:
        return JsonResponse({"status": "ok"}, status=200)
    else:
        return JsonResponse({"status": "error", "detail": "Database unavailable"}, status=503)
