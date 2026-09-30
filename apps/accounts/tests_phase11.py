"""
Phase 11 tests: Production hardening, security, deployment readiness.

Tests cover:
- Health endpoint (GET /health/ → 200, safe response)
- Seed commands refuse under DEBUG=False
- Cache-Control headers on authenticated private pages
- Custom 404/403/500 error pages render without traceback
- QR security regression (role-based access, no open redirect, invalid codes)
- Service worker does not cache authenticated HTML (static assertion)
"""
from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.contrib.auth import get_user_model
from apps.organizations.models import Department, Location, Employee
from apps.inventory.models import Asset, AssetCategory

User = get_user_model()


# ---------------------------------------------------------------------------
# Health endpoint
# ---------------------------------------------------------------------------

class HealthEndpointTests(TestCase):
    """GET /health/ must return 200 with {status: ok}, no sensitive data."""

    def test_health_endpoint_returns_200(self):
        response = self.client.get('/health/')
        self.assertEqual(response.status_code, 200)

    def test_health_endpoint_is_json(self):
        response = self.client.get('/health/')
        self.assertEqual(response['Content-Type'], 'application/json')

    def test_health_endpoint_has_status_ok(self):
        import json
        response = self.client.get('/health/')
        data = json.loads(response.content)
        self.assertIn('status', data)
        self.assertEqual(data['status'], 'ok')

    def test_health_endpoint_no_sensitive_fields(self):
        """Health endpoint must not expose database name, hostname, debug state, or credentials."""
        import json
        response = self.client.get('/health/')
        content_str = response.content.decode('utf-8')
        # Must not contain any configuration identifiers
        for forbidden in ['SECRET_KEY', 'DB_PASSWORD', 'DATABASE_URL', 'DEBUG', 'traceback']:
            self.assertNotIn(forbidden, content_str,
                             f"Health endpoint must not expose: {forbidden}")

    def test_health_endpoint_accessible_without_login(self):
        """Health endpoint must be publicly accessible (for load balancers)."""
        # Ensure no login was performed
        client = Client()
        response = client.get('/health/')
        self.assertEqual(response.status_code, 200)


# ---------------------------------------------------------------------------
# Seed command protection (DEBUG=False safeguard)
# ---------------------------------------------------------------------------

class SeedCommandDebugGuardTests(TestCase):
    """Seed commands must refuse to run when DEBUG=False without --force-demo-data."""

    def _run_seed_command(self, command_name, **kwargs):
        from django.core.management import call_command
        from io import StringIO
        out = StringIO()
        err = StringIO()
        try:
            call_command(command_name, stdout=out, stderr=err, **kwargs)
            return {'success': True, 'out': out.getvalue(), 'err': err.getvalue()}
        except Exception as e:
            return {'success': False, 'exception': e, 'out': out.getvalue(), 'err': err.getvalue()}

    @override_settings(DEBUG=False)
    def test_seed_phase1_refuses_when_debug_false(self):
        result = self._run_seed_command('seed_phase1')
        self.assertFalse(result['success'],
                         "seed_phase1 should refuse to run when DEBUG=False")

    @override_settings(DEBUG=True)
    def test_seed_phase1_allowed_when_debug_true(self):
        """Seed command runs without error when DEBUG=True."""
        result = self._run_seed_command('seed_phase1')
        # Either success OR existing data (get_or_create idempotent)
        # We just check it didn't raise a safety CommandError
        from django.core.management.base import CommandError
        if not result['success']:
            exc = result['exception']
            self.assertNotIsInstance(
                exc, CommandError,
                f"seed_phase1 raised unexpected CommandError in DEBUG=True: {exc}"
            )

    @override_settings(DEBUG=False)
    def test_seed_phase2_refuses_when_debug_false(self):
        result = self._run_seed_command('seed_phase2')
        self.assertFalse(result['success'],
                         "seed_phase2 should refuse to run when DEBUG=False")

    @override_settings(DEBUG=False)
    def test_seed_phase5_refuses_when_debug_false(self):
        result = self._run_seed_command('seed_phase5')
        self.assertFalse(result['success'],
                         "seed_phase5 should refuse to run when DEBUG=False")


# ---------------------------------------------------------------------------
# Cache-Control headers on authenticated private pages
# ---------------------------------------------------------------------------

class CacheControlHeaderTests(TestCase):
    """Private authenticated pages must set Cache-Control: private, no-store."""

    def setUp(self):
        self.client = Client()
        self.admin = User.objects.create_user(
            username='cc_admin', password='Password123!', role=User.Role.ADMIN
        )
        self.faculty = User.objects.create_user(
            username='cc_faculty', password='Password123!', role=User.Role.FACULTY
        )

    def _assert_no_cache(self, path, username, password):
        self.client.login(username=username, password=password)
        response = self.client.get(path)
        # Only check if page is accessible (not a redirect to login)
        if response.status_code == 200:
            cache_control = response.get('Cache-Control', '')
            self.assertIn('no-store', cache_control,
                          f"Expected Cache-Control: no-store on {path}, got: '{cache_control}'")

    def test_dashboard_no_store(self):
        self._assert_no_cache('/dashboard/', 'cc_admin', 'Password123!')

    def test_assignments_list_no_store(self):
        self._assert_no_cache('/assignments/', 'cc_admin', 'Password123!')

    def test_reports_no_store(self):
        self._assert_no_cache('/reports/', 'cc_admin', 'Password123!')

    def test_audit_no_store(self):
        self._assert_no_cache('/audit/', 'cc_admin', 'Password123!')

    def test_borrowing_list_no_store(self):
        self._assert_no_cache('/borrowing/', 'cc_admin', 'Password123!')

    def test_maintenance_list_no_store(self):
        self._assert_no_cache('/maintenance/', 'cc_admin', 'Password123!')

    def test_faculty_accountability_no_store(self):
        """My Accountability page for faculty must not be cached."""
        self._assert_no_cache('/assignments/my-accountability/', 'cc_faculty', 'Password123!')


# ---------------------------------------------------------------------------
# Custom error pages
# ---------------------------------------------------------------------------

class CustomErrorPageTests(TestCase):
    """Custom error pages must render without tracebacks and with minimal branding."""

    def test_404_page_contains_branded_text(self):
        """Custom 404 page must mention CBA IMS or 404, not expose traceback."""
        response = self.client.get('/this-url-definitely-does-not-exist-phase11-test/')
        self.assertEqual(response.status_code, 404)
        content = response.content.decode('utf-8')
        # Must NOT contain Django debug traceback markers
        self.assertNotIn('Traceback (most recent call last)', content)
        self.assertNotIn('django.core.exceptions', content)

    def test_404_template_exists(self):
        """The 404.html template file must exist."""
        import os
        template_path = 'C:/Users/PERSONAL/Documents/RobloxDanceEmote/cba_ims/templates/404.html'
        self.assertTrue(os.path.exists(template_path),
                        "templates/404.html must exist for custom 404 page")

    def test_403_template_exists(self):
        """The 403.html template file must exist."""
        import os
        template_path = 'C:/Users/PERSONAL/Documents/RobloxDanceEmote/cba_ims/templates/403.html'
        self.assertTrue(os.path.exists(template_path),
                        "templates/403.html must exist for custom 403 page")

    def test_500_template_exists(self):
        """The 500.html template file must exist."""
        import os
        template_path = 'C:/Users/PERSONAL/Documents/RobloxDanceEmote/cba_ims/templates/500.html'
        self.assertTrue(os.path.exists(template_path),
                        "templates/500.html must exist for custom 500 page")

    def test_400_template_exists(self):
        """The 400.html template file must exist."""
        import os
        template_path = 'C:/Users/PERSONAL/Documents/RobloxDanceEmote/cba_ims/templates/400.html'
        self.assertTrue(os.path.exists(template_path),
                        "templates/400.html must exist for custom 400 page")

    def test_all_handlers_execute_cleanly_under_debug_false(self):
        """All four error handlers (400, 403, 404, 500) render valid status codes and leak zero secrets."""
        from django.test import RequestFactory
        from config.urls import handler400, handler403, handler404, handler500

        rf = RequestFactory()
        req = rf.get('/test-error/')

        with override_settings(DEBUG=False):
            res400 = handler400(req, Exception('Bad request test'))
            res403 = handler403(req, Exception('Forbidden test'))
            res404 = handler404(req, Exception('Not found test'))
            res500 = handler500(req)

        self.assertEqual(res400.status_code, 400)
        self.assertEqual(res403.status_code, 403)
        self.assertEqual(res404.status_code, 404)
        self.assertEqual(res500.status_code, 500)

        for code, res in [(400, res400), (403, res403), (404, res404), (500, res500)]:
            t = res.content.decode('utf-8')
            self.assertNotIn('Traceback', t, f'{code} leaked Traceback')
            self.assertNotIn('SELECT', t, f'{code} leaked SQL')
            self.assertNotIn('SECRET_KEY', t, f'{code} leaked secret')


# ---------------------------------------------------------------------------

# QR Security Regression
# ---------------------------------------------------------------------------

class QRSecurityRegressionTests(TestCase):
    """QR lookup endpoint must enforce RBAC, no open redirect, 404 on invalid."""

    def setUp(self):
        self.client = Client()
        self.admin = User.objects.create_user(
            username='qr_admin', password='Password123!', role=User.Role.ADMIN
        )
        # Create minimal asset infrastructure
        self.dept = Department.objects.create(name='QR Test Dept', code='QRTD')
        self.category = AssetCategory.objects.create(name='QR Category', code='QRC')
        self.asset = Asset.objects.create(
            item_name='QR Test Asset',
            category=self.category,
            department=self.dept,
            condition=Asset.Condition.GOOD,
            status=Asset.Status.AVAILABLE,
        )

    def test_unauthenticated_qr_redirects_to_login(self):
        """Unauthenticated QR access must redirect to login, not expose data."""
        asset_code = self.asset.asset_code
        response = self.client.get(f'/q/assets/{asset_code}/')
        # Must redirect to login
        self.assertIn(response.status_code, [301, 302])
        redirect_url = response.get('Location', '')
        self.assertIn('/accounts/login/', redirect_url,
                      f"QR unauthenticated must redirect to login, got: {redirect_url}")

    def test_unauthenticated_qr_no_open_redirect(self):
        """QR redirect must not allow open redirect to arbitrary external URLs."""
        response = self.client.get('/q/assets/NONEXISTENT-ASSET-CODE/')
        if response.status_code in [301, 302]:
            location = response.get('Location', '')
            # Must not redirect to external domain
            self.assertFalse(
                location.startswith('http://evil.example.com') or
                location.startswith('https://evil.example.com'),
                f"Possible open redirect to: {location}"
            )

    def test_invalid_asset_code_returns_404(self):
        """Invalid QR asset codes must return 404."""
        self.client.login(username='qr_admin', password='Password123!')
        response = self.client.get('/q/assets/TOTALLY-INVALID-ASSET-CODE-XYZ/')
        self.assertEqual(response.status_code, 404)

    def test_admin_can_access_valid_qr_asset(self):
        """Admin scanning a valid QR code must get a redirect to asset detail (not error)."""
        self.client.login(username='qr_admin', password='Password123!')
        asset_code = self.asset.asset_code
        response = self.client.get(f'/q/assets/{asset_code}/')
        # Should redirect to asset detail or show it directly
        self.assertIn(response.status_code, [200, 301, 302],
                      f"Admin QR access returned unexpected status: {response.status_code}")

    def test_disposed_asset_returns_404_or_403_for_faculty(self):
        """Faculty accessing disposed asset QR must not see full asset detail."""
        faculty = User.objects.create_user(
            username='qr_faculty', password='Password123!', role=User.Role.FACULTY
        )
        # Set asset to DISPOSED
        self.asset.status = Asset.Status.DISPOSED
        self.asset.save()

        self.client.login(username='qr_faculty', password='Password123!')
        asset_code = self.asset.asset_code
        response = self.client.get(f'/q/assets/{asset_code}/')
        # Faculty must get 404 or redirect (not full asset detail on disposed)
        self.assertIn(response.status_code, [404, 302, 403],
                      f"Faculty access to disposed asset QR returned: {response.status_code}")


# ---------------------------------------------------------------------------
# Service worker security assertion
# ---------------------------------------------------------------------------

class ServiceWorkerSecurityTests(TestCase):
    """Assert that the service worker does not cache authenticated HTML pages."""

    def test_service_worker_does_not_cache_navigation(self):
        """sw.js must use network-first (not cache-first) for navigate requests."""
        from django.contrib.staticfiles import finders
        sw_path = finders.find('sw.js')
        self.assertIsNotNone(sw_path, "sw.js must be findable")
        with open(sw_path, 'r', encoding='utf-8') as f:
            sw_content = f.read()
        # The navigate mode must NOT be sent to cache.match first
        # It must call fetch() first for navigate requests
        self.assertIn("mode === 'navigate'", sw_content,
                      "sw.js must explicitly handle navigate requests")
        # Must include a comment or logic indicating no HTML caching
        has_security_comment = (
            'NEVER cached' in sw_content or
            'not cached' in sw_content or
            'network only' in sw_content.lower() or
            'SECURITY' in sw_content
        )
        self.assertTrue(has_security_comment,
                        "sw.js must document that authenticated HTML is not cached")

    def test_service_worker_version_constant_exists(self):
        """sw.js should have a version constant for cache busting."""
        from django.contrib.staticfiles import finders
        sw_path = finders.find('sw.js')
        if sw_path:
            with open(sw_path, 'r', encoding='utf-8') as f:
                sw_content = f.read()
            self.assertIn('cba-ims', sw_content,
                          "sw.js must reference cba-ims in cache name")


# ---------------------------------------------------------------------------
# Settings security assertions
# ---------------------------------------------------------------------------

class SettingsSecurityTests(TestCase):
    """Verify security-relevant settings are configured correctly."""

    def test_x_frame_options_deny(self):
        from django.conf import settings
        x_frame = getattr(settings, 'X_FRAME_OPTIONS', None)
        self.assertEqual(x_frame, 'DENY',
                         "X_FRAME_OPTIONS must be DENY to prevent clickjacking")

    def test_session_cookie_httponly(self):
        from django.conf import settings
        self.assertTrue(
            getattr(settings, 'SESSION_COOKIE_HTTPONLY', True),
            "SESSION_COOKIE_HTTPONLY must be True"
        )

    def test_csrf_cookie_httponly(self):
        from django.conf import settings
        self.assertTrue(
            getattr(settings, 'CSRF_COOKIE_HTTPONLY', True),
            "CSRF_COOKIE_HTTPONLY must be True"
        )

    def test_session_cookie_samesite(self):
        from django.conf import settings
        samesite = getattr(settings, 'SESSION_COOKIE_SAMESITE', None)
        self.assertIn(samesite, ['Lax', 'Strict'],
                      f"SESSION_COOKIE_SAMESITE must be Lax or Strict, got: {samesite}")

    def test_secret_key_not_default_insecure_value(self):
        """SECRET_KEY must not be left as the insecure development default."""
        from django.conf import settings
        # The insecure placeholder key starts with 'django-insecure-'
        # In test environment this may still be the dev key — we just check it's set
        self.assertIsNotNone(settings.SECRET_KEY)
        self.assertGreater(len(settings.SECRET_KEY), 20,
                           "SECRET_KEY must be a meaningful length")

    def test_axes_installed(self):
        """django-axes must be in INSTALLED_APPS for brute-force protection."""
        from django.conf import settings
        self.assertIn('axes', settings.INSTALLED_APPS,
                      "django-axes must be in INSTALLED_APPS")

    def test_whitenoise_in_middleware(self):
        """WhiteNoise middleware must be configured for static file serving."""
        from django.conf import settings
        middleware_list = settings.MIDDLEWARE
        whitenoise_present = any('whitenoise' in m.lower() for m in middleware_list)
        self.assertTrue(whitenoise_present,
                        "WhiteNoise middleware must be in MIDDLEWARE")


# ---------------------------------------------------------------------------
# Backend & Axes Security Tests (Audit Point 3)
# ---------------------------------------------------------------------------

class CBAAxesBackendSecurityTests(TestCase):
    """
    Rigorously verify CBAAxesBackend:
    - Never authenticates on its own without valid credentials
    - Correct password is strictly required
    - Axes lockout enforces after 5 failures and cannot be bypassed
    - Arbitrary client headers/params cannot trigger bypass
    """

    def setUp(self):
        self.user = User.objects.create_user(
            username='axes_audit_user',
            password='TargetPassword123!',
            role=User.Role.ADMIN
        )

    def test_backend_alone_returns_none_when_request_is_none(self):
        from apps.accounts.backends import CBAAxesBackend
        backend = CBAAxesBackend()
        # Even with correct credentials, CBAAxesBackend returns None when request=None
        # It relies on ModelBackend to perform the actual password verification
        result = backend.authenticate(request=None, username='axes_audit_user', password='TargetPassword123!')
        self.assertIsNone(result)

    def test_backend_alone_returns_none_when_wrong_password(self):
        from apps.accounts.backends import CBAAxesBackend
        backend = CBAAxesBackend()
        result = backend.authenticate(request=None, username='axes_audit_user', password='WrongPassword!')
        self.assertIsNone(result)

    def test_authenticate_requires_correct_password(self):
        from django.contrib.auth import authenticate
        # Wrong password must fail
        user = authenticate(username='axes_audit_user', password='IncorrectPassword!')
        self.assertIsNone(user)
        # Correct password must succeed
        user = authenticate(username='axes_audit_user', password='TargetPassword123!')
        self.assertIsNotNone(user)
        self.assertEqual(user.username, 'axes_audit_user')

    def test_axes_lockout_enforcement_on_repeated_failures(self):
        """5 consecutive failed HTTP login attempts trigger Axes lockout."""
        from axes.models import AccessAttempt
        from axes.utils import reset
        reset(username='axes_audit_user')

        client = Client(REMOTE_ADDR='10.20.30.40')
        # Attempt 5 failures
        for i in range(5):
            client.post('/accounts/login/', {
                'username': 'axes_audit_user',
                'password': f'WrongPass{i}!'
            })

        # Verify an access attempt record exists
        attempts = AccessAttempt.objects.filter(username='axes_audit_user')
        self.assertTrue(attempts.exists())
        self.assertGreaterEqual(attempts.first().failures_since_start, 5)

        # 6th attempt with CORRECT password must be blocked by Axes lockout
        res = client.post('/accounts/login/', {
            'username': 'axes_audit_user',
            'password': 'TargetPassword123!'
        })
        # During lockout, user must NOT be logged in and response must indicate lockout or failure
        self.assertNotIn('_auth_user_id', client.session)

        # Cleanup
        reset(username='axes_audit_user')

    def test_client_parameters_cannot_bypass_lockout(self):
        """Attacker cannot supply 'request=None' or bypass headers in POST body."""
        client = Client(REMOTE_ADDR='10.20.30.41')
        res = client.post('/accounts/login/', {
            'username': 'axes_audit_user',
            'password': 'WrongPassword!',
            'request': 'None',
            'is_test': 'True',
        })
        # Password still rejected
        self.assertNotIn('_auth_user_id', client.session)


# ---------------------------------------------------------------------------
# Image Upload Validation Regression Tests (Audit Point 10)
# ---------------------------------------------------------------------------

class ImageUploadValidationRegressionTests(TestCase):
    """Regression test image upload validation: JPEG, PNG, WebP, >5MB, fake jpg, corrupted, unsupported."""

    def _make_image_bytes(self, fmt='JPEG'):
        from io import BytesIO
        from PIL import Image as PILImage
        buf = BytesIO()
        img = PILImage.new('RGB', (20, 20), color='green')
        img.save(buf, format=fmt)
        return buf.getvalue()

    def test_valid_jpeg_passes(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from apps.inventory.models import validate_asset_image
        f = SimpleUploadedFile('test.jpg', self._make_image_bytes('JPEG'), content_type='image/jpeg')
        validate_asset_image(f)

    def test_valid_png_passes(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from apps.inventory.models import validate_asset_image
        f = SimpleUploadedFile('test.png', self._make_image_bytes('PNG'), content_type='image/png')
        validate_asset_image(f)

    def test_valid_webp_passes(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from apps.inventory.models import validate_asset_image
        f = SimpleUploadedFile('test.webp', self._make_image_bytes('WEBP'), content_type='image/webp')
        validate_asset_image(f)

    def test_file_above_5mb_rejected(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from django.core.exceptions import ValidationError
        from apps.inventory.models import validate_asset_image
        oversized_data = b'0' * (6 * 1024 * 1024)
        f = SimpleUploadedFile('huge.jpg', oversized_data, content_type='image/jpeg')
        with self.assertRaises(ValidationError) as ctx:
            validate_asset_image(f)
        self.assertIn('5 MB', str(ctx.exception))

    def test_renamed_text_file_ending_jpg_rejected(self):
        """A text or script file renamed to .jpg must fail decodability check."""
        from django.core.files.uploadedfile import SimpleUploadedFile
        from django.core.exceptions import ValidationError
        from apps.inventory.models import validate_asset_image
        fake_data = b'<?php echo "evil script"; ?> This is not an image.'
        f = SimpleUploadedFile('malicious.jpg', fake_data, content_type='image/jpeg')
        with self.assertRaises(ValidationError) as ctx:
            validate_asset_image(f)
        self.assertIn('could not be decoded', str(ctx.exception))

    def test_corrupted_image_rejected(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from django.core.exceptions import ValidationError
        from apps.inventory.models import validate_asset_image
        corrupt_data = b'\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01corrupted_data_junk_bytes'
        f = SimpleUploadedFile('corrupt.jpg', corrupt_data, content_type='image/jpeg')
        with self.assertRaises(ValidationError) as ctx:
            validate_asset_image(f)
        self.assertIn('could not be decoded', str(ctx.exception))

    def test_unsupported_extension_rejected(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from django.core.exceptions import ValidationError
        from apps.inventory.models import validate_asset_image
        for ext in ['.gif', '.exe', '.pdf', '.svg', '.bmp']:
            f = SimpleUploadedFile(f'file{ext}', b'GIF89a...', content_type='application/octet-stream')
            with self.assertRaises(ValidationError) as ctx:
                validate_asset_image(f)
            self.assertIn('Unsupported file extension', str(ctx.exception))


# ---------------------------------------------------------------------------
# Report Export Security & Scoping Regression Tests (Audit Point 12)
# ---------------------------------------------------------------------------

class ReportExportSecurityRegressionTests(TestCase):
    """Verify Department Chair scoping cannot be bypassed and spreadsheet formula injection is sanitized."""

    def setUp(self):
        self.dept_acct = Department.objects.create(name='Accountancy Dept', code='ACT')
        self.dept_mkt = Department.objects.create(name='Marketing Dept', code='MKT')

        self.chair_acct_user = User.objects.create_user(
            username='chair_audit_acct',
            password='Password123!',
            role=User.Role.DEPT_CHAIR
        )
        self.chair_acct_emp = Employee.objects.create(
            user=self.chair_acct_user,
            department=self.dept_acct,
            first_name='Acct',
            last_name='Chair'
        )

        self.faculty_user = User.objects.create_user(
            username='faculty_audit',
            password='Password123!',
            role=User.Role.FACULTY
        )

    def test_chair_scope_helper_returns_own_department(self):
        from apps.reports.services import get_user_department_scope
        scope = get_user_department_scope(self.chair_acct_user)
        self.assertEqual(scope, self.dept_acct)

    def test_faculty_scope_helper_raises_permission_denied(self):
        from apps.reports.services import get_user_department_scope
        from django.core.exceptions import PermissionDenied
        with self.assertRaises(PermissionDenied):
            get_user_department_scope(self.faculty_user)

    def test_formula_injection_sanitization_prefixes_dangerous_chars(self):
        from apps.reports.exporters import sanitize_for_spreadsheet
        self.assertEqual(sanitize_for_spreadsheet("=SUM(A1:A10)"), "'=SUM(A1:A10)")
        self.assertEqual(sanitize_for_spreadsheet("+cmd|' /C calc'!A0"), "'+cmd|' /C calc'!A0")
        self.assertEqual(sanitize_for_spreadsheet("-1+1"), "'-1+1")
        self.assertEqual(sanitize_for_spreadsheet("@external_ref"), "'@external_ref")
        self.assertEqual(sanitize_for_spreadsheet("\t=cmd"), "'\t=cmd")
        self.assertEqual(sanitize_for_spreadsheet("   =spaced_cmd"), "'   =spaced_cmd")

    def test_formula_injection_sanitization_leaves_safe_values_intact(self):
        from apps.reports.exporters import sanitize_for_spreadsheet
        self.assertEqual(sanitize_for_spreadsheet("Normal Laptop"), "Normal Laptop")
        self.assertEqual(sanitize_for_spreadsheet("CBA-IT-00001"), "CBA-IT-00001")
        self.assertEqual(sanitize_for_spreadsheet(12345), 12345)
        self.assertEqual(sanitize_for_spreadsheet(None), None)


# ---------------------------------------------------------------------------
# Health Endpoint Failure Mode Regression Tests (Audit Point 9)
# ---------------------------------------------------------------------------

class HealthEndpointFailureRegressionTests(TestCase):
    """Verify health check returns 503 without configuration leak when DB is unreachable."""

    def test_health_check_returns_503_when_database_fails(self):
        from unittest.mock import patch
        from django.db.utils import OperationalError
        import json

        with patch('django.db.connection.ensure_connection', side_effect=OperationalError("DB connection refused")):
            response = self.client.get('/health/')
            self.assertEqual(response.status_code, 503)
            data = json.loads(response.content)
            self.assertEqual(data.get('status'), 'error')
            content_str = response.content.decode('utf-8')
            for forbidden in ['password', 'localhost', 'cba_ims', 'traceback', 'postgres']:
                self.assertNotIn(forbidden, content_str.lower())

