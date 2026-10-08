"""
URL configuration for CBA IMS project.
"""

from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.views.generic import RedirectView
from django.views.defaults import page_not_found, server_error, permission_denied, bad_request
from apps.inventory import views as inventory_views
from apps.accounts.health import health_check

handler400 = bad_request
handler403 = permission_denied
handler404 = page_not_found
handler500 = server_error

urlpatterns = [
    path('health/', health_check, name='health_check'),
    path('admin/', admin.site.urls),

    # Root URL redirects to dashboard
    path('', RedirectView.as_view(url='/dashboard/', permanent=False), name='home'),

    # Phase 6: Canonical QR Sticker Asset Lookup Gateway
    path('q/assets/<str:asset_code>/', inventory_views.QRAssetLookupView.as_view(), name='qr_asset_lookup'),

    # Dashboard (handled by accounts app)
    path('dashboard/', include('apps.accounts.dashboard_urls')),

    # Authentication
    path('accounts/', include('apps.accounts.urls')),

    # Domain apps
    path('organizations/', include('apps.organizations.urls')),
    path('inventory/', include('apps.inventory.urls')),
    path('supplies/', include('apps.supplies.urls')),
    path('assignments/', include('apps.assignments.urls')),
    path('borrowing/', include('apps.borrowing.urls')),
    path('transfers/', include('apps.transfers.urls')),
    path('maintenance/', include('apps.maintenance.urls')),
    path('disposals/', include('apps.disposals.urls')),
    path('reports/', include('apps.reports.urls')),
    path('audit/', include('apps.audit.urls')),
    path('student-reservations/', include('apps.student_reservations.urls')),
]

from django.contrib.staticfiles.urls import staticfiles_urlpatterns

# Serve media and static files in development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += staticfiles_urlpatterns()

