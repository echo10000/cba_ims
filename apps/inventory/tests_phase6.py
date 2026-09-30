from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal

from apps.accounts.models import User
from apps.organizations.models import Department, Location, Employee
from apps.inventory.models import AssetCategory, Brand, Asset, AssetVerification
from apps.assignments.models import AssetAssignment
from apps.audit.models import AuditLog
from apps.inventory import qr_services


class Phase6BaseTestCase(TestCase):
    def setUp(self):
        self.client = Client()

        # Departments & Locations
        self.dept_it = Department.objects.create(name='Information Technology', code='IT')
        self.dept_ba = Department.objects.create(name='Business Administration', code='BA')
        self.loc_lab = Location.objects.create(name='Computer Lab 1', building='IT Building', room_number='101', department=self.dept_it)
        self.loc_dean = Location.objects.create(name="Dean's Office", building='Admin Building', room_number='201', department=self.dept_ba)

        # Category & Brand
        self.cat_comp = AssetCategory.objects.create(name='Computers', code='COMP')
        self.brand_dell = Brand.objects.create(name='Dell')

        # Users
        self.admin = User.objects.create_user(
            username='admin_user', email='admin@cba.edu', password='password123',
            role=User.Role.ADMIN, is_staff=True
        )
        self.dean = User.objects.create_user(
            username='dean_user', email='dean@cba.edu', password='password123',
            role=User.Role.DEAN
        )
        self.chair_it_user = User.objects.create_user(
            username='chair_it', email='chair_it@cba.edu', password='password123',
            role=User.Role.DEPT_CHAIR
        )
        self.chair_ba_user = User.objects.create_user(
            username='chair_ba', email='chair_ba@cba.edu', password='password123',
            role=User.Role.DEPT_CHAIR
        )
        self.faculty_user = User.objects.create_user(
            username='faculty_user', email='faculty@cba.edu', password='password123',
            role=User.Role.FACULTY
        )
        self.other_faculty_user = User.objects.create_user(
            username='other_faculty', email='other_fac@cba.edu', password='password123',
            role=User.Role.FACULTY
        )

        # Employee profiles
        self.emp_chair_it = Employee.objects.create(
            user=self.chair_it_user, employee_id='EMP-CH-01', first_name='IT', last_name='Chair',
            department=self.dept_it, email='chair_it@cba.edu'
        )
        self.emp_chair_ba = Employee.objects.create(
            user=self.chair_ba_user, employee_id='EMP-CH-02', first_name='BA', last_name='Chair',
            department=self.dept_ba, email='chair_ba@cba.edu'
        )
        self.emp_faculty = Employee.objects.create(
            user=self.faculty_user, employee_id='EMP-FAC-01', first_name='Faculty', last_name='One',
            department=self.dept_it, email='faculty@cba.edu'
        )
        self.emp_other_faculty = Employee.objects.create(
            user=self.other_faculty_user, employee_id='EMP-FAC-02', first_name='Faculty', last_name='Two',
            department=self.dept_ba, email='other_fac@cba.edu'
        )

        # Assets
        self.asset_it = Asset.objects.create(
            item_name='ThinkPad L14',
            category=self.cat_comp,
            brand=self.brand_dell,
            department=self.dept_it,
            current_location=self.loc_lab,
            condition=Asset.Condition.GOOD,
            status=Asset.Status.AVAILABLE,
            property_number='NORSU-COMP-001',
            created_by=self.admin,
        )
        self.asset_ba = Asset.objects.create(
            item_name='Projector Epson',
            category=self.cat_comp,
            brand=self.brand_dell,
            department=self.dept_ba,
            current_location=self.loc_dean,
            condition=Asset.Condition.GOOD,
            status=Asset.Status.AVAILABLE,
            property_number='NORSU-PROJ-001',
            created_by=self.admin,
        )

        # Assigned Asset to faculty_user
        self.asset_assigned = Asset.objects.create(
            item_name='Faculty Assigned Desktop',
            category=self.cat_comp,
            brand=self.brand_dell,
            department=self.dept_it,
            current_location=self.loc_lab,
            condition=Asset.Condition.GOOD,
            status=Asset.Status.ASSIGNED,
            property_number='NORSU-COMP-002',
            created_by=self.admin,
        )
        self.assignment = AssetAssignment.objects.create(
            asset=self.asset_assigned,
            employee=self.emp_faculty,
            assigned_by=self.admin,
            status='ACTIVE',
            condition_at_assignment=Asset.Condition.GOOD,
            purpose='Instructional research'
        )


class AssetVerificationModelTests(Phase6BaseTestCase):
    def test_calculate_result_exact_match(self):
        result = AssetVerification.calculate_result(
            expected_dept=self.dept_it,
            expected_loc=self.loc_lab,
            expected_cond=Asset.Condition.GOOD,
            observed_dept=self.dept_it,
            observed_loc=self.loc_lab,
            observed_cond=Asset.Condition.GOOD,
        )
        self.assertEqual(result, AssetVerification.VerificationResult.VERIFIED)

    def test_calculate_result_location_mismatch(self):
        result = AssetVerification.calculate_result(
            expected_dept=self.dept_it,
            expected_loc=self.loc_lab,
            expected_cond=Asset.Condition.GOOD,
            observed_dept=self.dept_ba,
            observed_loc=self.loc_dean,
            observed_cond=Asset.Condition.GOOD,
        )
        self.assertEqual(result, AssetVerification.VerificationResult.LOCATION_MISMATCH)

    def test_calculate_result_condition_mismatch(self):
        result = AssetVerification.calculate_result(
            expected_dept=self.dept_it,
            expected_loc=self.loc_lab,
            expected_cond=Asset.Condition.GOOD,
            observed_dept=self.dept_it,
            observed_loc=self.loc_lab,
            observed_cond=Asset.Condition.POOR,
        )
        self.assertEqual(result, AssetVerification.VerificationResult.CONDITION_MISMATCH)

    def test_calculate_result_both_mismatch(self):
        result = AssetVerification.calculate_result(
            expected_dept=self.dept_it,
            expected_loc=self.loc_lab,
            expected_cond=Asset.Condition.GOOD,
            observed_dept=self.dept_ba,
            observed_loc=self.loc_dean,
            observed_cond=Asset.Condition.DAMAGED if hasattr(Asset.Condition, 'DAMAGED') else Asset.Condition.POOR,
        )
        self.assertEqual(result, AssetVerification.VerificationResult.LOCATION_AND_CONDITION_MISMATCH)

    def test_asset_latest_verification_properties(self):
        self.assertIsNone(self.asset_it.latest_verification)
        self.assertIsNone(self.asset_it.last_verified_at)

        v1 = AssetVerification.objects.create(
            asset=self.asset_it,
            verified_by=self.admin,
            verified_at=timezone.now() - timedelta(days=2),
            expected_department=self.dept_it,
            expected_location=self.loc_lab,
            expected_condition=self.asset_it.condition,
            observed_department=self.dept_it,
            observed_location=self.loc_lab,
            observed_condition=self.asset_it.condition,
            result=AssetVerification.VerificationResult.VERIFIED,
            remarks='First check'
        )

        v2 = AssetVerification.objects.create(
            asset=self.asset_it,
            verified_by=self.admin,
            verified_at=timezone.now() - timedelta(days=1),
            expected_department=self.dept_it,
            expected_location=self.loc_lab,
            expected_condition=self.asset_it.condition,
            observed_department=self.dept_ba,
            observed_location=self.loc_dean,
            observed_condition=self.asset_it.condition,
            result=AssetVerification.VerificationResult.LOCATION_MISMATCH,
            remarks='Second check'
        )

        self.asset_it.refresh_from_db()
        self.assertEqual(self.asset_it.latest_verification, v2)
        self.assertEqual(self.asset_it.last_verified_at, v2.verified_at)


class QRCodeServiceTests(Phase6BaseTestCase):
    def test_get_asset_qr_url(self):
        url = qr_services.get_asset_qr_url(self.asset_it)
        self.assertEqual(url, f"/q/assets/{self.asset_it.asset_code}/")

    def test_generate_asset_qr_image(self):
        img_bytes = qr_services.generate_asset_qr_image(self.asset_it)
        self.assertIsInstance(img_bytes, bytes)
        # PNG Header Magic Bytes: \x89PNG\r\n\x1a\n
        self.assertTrue(img_bytes.startswith(b'\x89PNG\r\n\x1a\n'))

    def test_generate_asset_qr_data_uri(self):
        data_uri = qr_services.generate_asset_qr_data_uri(self.asset_it)
        self.assertTrue(data_uri.startswith('data:image/png;base64,'))
        self.assertGreater(len(data_uri), 100)

    def test_verify_asset_service_does_not_mutate_asset(self):
        initial_dept = self.asset_it.department
        initial_loc = self.asset_it.current_location
        initial_cond = self.asset_it.condition

        # Perform verification observing a location and condition mismatch
        verification = qr_services.verify_asset(
            asset=self.asset_it,
            verified_by=self.admin,
            observed_department=self.dept_ba,
            observed_location=self.loc_dean,
            observed_condition=Asset.Condition.POOR,
            remarks='Audit observed item moved and degraded.'
        )

        self.assertEqual(verification.result, AssetVerification.VerificationResult.LOCATION_AND_CONDITION_MISMATCH)
        self.assertEqual(verification.expected_department, initial_dept)
        self.assertEqual(verification.expected_location, initial_loc)
        self.assertEqual(verification.expected_condition, initial_cond)

        # Crucial verification invariant: canonical asset state MUST NOT be altered
        self.asset_it.refresh_from_db()
        self.assertEqual(self.asset_it.department, initial_dept)
        self.assertEqual(self.asset_it.current_location, initial_loc)
        self.assertEqual(self.asset_it.condition, initial_cond)

        # Check Audit Log
        audit_entry = AuditLog.objects.filter(action='ASSET_VERIFIED', object_id=str(self.asset_it.pk)).first()
        self.assertIsNotNone(audit_entry)
        self.assertEqual(audit_entry.changes.get('result'), AssetVerification.VerificationResult.LOCATION_AND_CONDITION_MISMATCH)


class QRAssetLookupViewSecurityTests(Phase6BaseTestCase):
    def test_anonymous_redirect(self):
        url = reverse('qr_asset_lookup', kwargs={'asset_code': self.asset_it.asset_code})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('accounts:login'), response.url)

    def test_admin_access_allowed(self):
        self.client.force_login(self.admin)
        url = reverse('qr_asset_lookup', kwargs={'asset_code': self.asset_it.asset_code})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.asset_it.asset_code)

    def test_dean_access_allowed(self):
        self.client.force_login(self.dean)
        url = reverse('qr_asset_lookup', kwargs={'asset_code': self.asset_it.asset_code})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.asset_it.asset_code)

    def test_chair_can_access_own_department_asset(self):
        self.client.force_login(self.chair_it_user)
        url = reverse('qr_asset_lookup', kwargs={'asset_code': self.asset_it.asset_code})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.asset_it.asset_code)

    def test_chair_denied_other_department_asset(self):
        self.client.force_login(self.chair_it_user)
        # asset_ba belongs to BA department
        url = reverse('qr_asset_lookup', kwargs={'asset_code': self.asset_ba.asset_code})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 403)

    def test_faculty_can_access_own_assigned_asset(self):
        self.client.force_login(self.faculty_user)
        url = reverse('qr_asset_lookup', kwargs={'asset_code': self.asset_assigned.asset_code})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.asset_assigned.asset_code)

    def test_faculty_denied_unassigned_or_other_asset(self):
        self.client.force_login(self.faculty_user)
        url = reverse('qr_asset_lookup', kwargs={'asset_code': self.asset_it.asset_code})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 403)

    def test_qr_asset_lookup_nonexistent_returns_404(self):
        self.client.force_login(self.admin)
        url = reverse('qr_asset_lookup', kwargs={'asset_code': 'CBA-XX-99999'})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)


class QRAssetImageViewTests(Phase6BaseTestCase):
    def test_admin_gets_png_image(self):
        self.client.force_login(self.admin)
        url = reverse('inventory:asset_qr_image', kwargs={'asset_code': self.asset_it.asset_code})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'image/png')
        self.assertTrue(response.content.startswith(b'\x89PNG\r\n\x1a\n'))

    def test_faculty_denied_unassigned_qr_image(self):
        self.client.force_login(self.faculty_user)
        url = reverse('inventory:asset_qr_image', kwargs={'asset_code': self.asset_it.asset_code})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 403)


class ScanAssetViewTests(Phase6BaseTestCase):
    def test_get_scan_page(self):
        self.client.force_login(self.faculty_user)
        url = reverse('inventory:asset_scan')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Scan Asset QR Code')

    def test_manual_code_lookup_success(self):
        self.client.force_login(self.admin)
        url = reverse('inventory:asset_scan')
        response = self.client.post(url, {'asset_code': self.asset_it.asset_code})
        self.assertRedirects(response, reverse('qr_asset_lookup', kwargs={'asset_code': self.asset_it.asset_code}))

    def test_manual_code_lookup_invalid_asset(self):
        self.client.force_login(self.admin)
        url = reverse('inventory:asset_scan')
        response = self.client.post(url, {'asset_code': 'INVALID-CODE-999'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "was not found in the system")


class AssetQRLabelViewTests(Phase6BaseTestCase):
    def test_admin_single_label_view(self):
        self.client.force_login(self.admin)
        url = reverse('inventory:asset_qr_label', kwargs={'asset_code': self.asset_it.asset_code})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.asset_it.asset_code)
        self.assertContains(response, 'data:image/png;base64,')

    def test_faculty_denied_label_view(self):
        self.client.force_login(self.faculty_user)
        url = reverse('inventory:asset_qr_label', kwargs={'asset_code': self.asset_assigned.asset_code})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 403)


class BulkQRLabelPrintViewTests(Phase6BaseTestCase):
    def test_admin_bulk_label_list(self):
        self.client.force_login(self.admin)
        url = reverse('inventory:qr_labels_bulk')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Bulk Asset QR Labels')
        self.assertContains(response, self.asset_it.asset_code)

    def test_admin_bulk_print_sheet(self):
        self.client.force_login(self.admin)
        url = reverse('inventory:qr_labels_bulk') + '?print=true'
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'sticker-card')
        self.assertContains(response, 'window.print()')

    def test_dean_denied_bulk_labels(self):
        self.client.force_login(self.dean)
        url = reverse('inventory:qr_labels_bulk')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 403)


class AssetVerifyViewTests(Phase6BaseTestCase):
    def test_get_verify_page_admin(self):
        self.client.force_login(self.admin)
        url = reverse('inventory:asset_verify', kwargs={'asset_code': self.asset_it.asset_code})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f"Verify Physical Asset - {self.asset_it.asset_code}")

    def test_non_admin_denied_verify(self):
        self.client.force_login(self.dean)
        url = reverse('inventory:asset_verify', kwargs={'asset_code': self.asset_it.asset_code})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 403)

    def test_submit_verification_exact_match(self):
        self.client.force_login(self.admin)
        url = reverse('inventory:asset_verify', kwargs={'asset_code': self.asset_it.asset_code})
        post_data = {
            'observed_department': self.dept_it.pk,
            'observed_location': self.loc_lab.pk,
            'observed_condition': self.asset_it.condition,
            'remarks': 'Physical audit complete. Sticker readable and serial verified.'
        }
        response = self.client.post(url, post_data)
        self.assertRedirects(response, reverse('inventory:asset_detail', kwargs={'asset_code': self.asset_it.asset_code}))

        # Verify database record
        v = AssetVerification.objects.filter(asset=self.asset_it).first()
        self.assertIsNotNone(v)
        self.assertEqual(v.result, AssetVerification.VerificationResult.VERIFIED)
        self.assertEqual(v.verified_by, self.admin)

    def test_submit_verification_location_mismatch_preserves_asset(self):
        self.client.force_login(self.admin)
        url = reverse('inventory:asset_verify', kwargs={'asset_code': self.asset_it.asset_code})
        post_data = {
            'observed_department': self.dept_ba.pk,
            'observed_location': self.loc_dean.pk,
            'observed_condition': self.asset_it.condition,
            'remarks': 'Found in Dean Office during room inspection.'
        }
        response = self.client.post(url, post_data)
        self.assertRedirects(response, reverse('inventory:asset_detail', kwargs={'asset_code': self.asset_it.asset_code}))

        v = AssetVerification.objects.filter(asset=self.asset_it).first()
        self.assertIsNotNone(v)
        self.assertEqual(v.result, AssetVerification.VerificationResult.LOCATION_MISMATCH)

        # Asset location remains unchanged
        self.asset_it.refresh_from_db()
        self.assertEqual(self.asset_it.department, self.dept_it)
        self.assertEqual(self.asset_it.current_location, self.loc_lab)


class PhysicalVerificationListViewTests(Phase6BaseTestCase):
    def test_admin_access_verification_list(self):
        self.client.force_login(self.admin)
        url = reverse('inventory:physical_verification_list')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Physical Inventory Verification')
        self.assertContains(response, 'Total Assets')

    def test_dean_access_verification_list(self):
        self.client.force_login(self.dean)
        url = reverse('inventory:physical_verification_list')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

    def test_chair_scoped_to_own_department(self):
        self.client.force_login(self.chair_it_user)
        url = reverse('inventory:physical_verification_list')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.asset_it.asset_code)
        self.assertNotContains(response, self.asset_ba.asset_code)

    def test_faculty_denied_verification_list(self):
        self.client.force_login(self.faculty_user)
        url = reverse('inventory:physical_verification_list')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 403)
