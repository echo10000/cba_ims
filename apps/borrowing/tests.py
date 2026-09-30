from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from django.core.exceptions import ValidationError, PermissionDenied
from django.db.models import ProtectedError
from datetime import timedelta
from decimal import Decimal

from apps.accounts.models import User
from apps.organizations.models import Department, Location, Employee
from apps.inventory.models import AssetCategory, Brand, Asset
from apps.borrowing.models import AssetBorrowing
from apps.borrowing import services as borrowing_services
from apps.audit.models import AuditLog


class BorrowingBaseTestCase(TestCase):
    """Sets up standard organizational entities, role-based users, and assets for testing."""

    def setUp(self):
        # Departments
        self.dept_ba = Department.objects.create(code='BA', name='Department of Business Administration')
        self.dept_acct = Department.objects.create(code='ACCT', name='Department of Accountancy')

        # Locations
        self.loc_storage = Location.objects.create(
            name='Equipment Storage', building='CBA Main', room_number='B-01', department=self.dept_ba
        )
        self.loc_fac_ba = Location.objects.create(
            name='BA Faculty Room', building='CBA Main', room_number='201', department=self.dept_ba
        )
        self.loc_fac_acct = Location.objects.create(
            name='Accountancy Office', building='CBA Annex', room_number='301', department=self.dept_acct
        )

        # Users with distinct roles
        self.admin_user = User.objects.create_superuser('admin_custodian', 'admin@cba.edu', 'Pass1234!')
        self.admin_user.role = User.Role.ADMIN
        self.admin_user.save()

        self.dean_user = User.objects.create_user('dean_user', 'dean@cba.edu', 'Pass1234!', role=User.Role.DEAN)
        self.chair_ba_user = User.objects.create_user('chair_ba', 'chair.ba@cba.edu', 'Pass1234!', role=User.Role.DEPT_CHAIR)
        self.chair_acct_user = User.objects.create_user('chair_acct', 'chair.acct@cba.edu', 'Pass1234!', role=User.Role.DEPT_CHAIR)
        self.faculty_user1 = User.objects.create_user('fac_maria', 'maria@cba.edu', 'Pass1234!', role=User.Role.FACULTY)
        self.faculty_user2 = User.objects.create_user('fac_jose', 'jose@cba.edu', 'Pass1234!', role=User.Role.FACULTY)

        # Employee Profiles
        self.emp_chair_ba = Employee.objects.create(
            user=self.chair_ba_user,
            employee_id='EMP-CH-01',
            first_name='Carlos',
            last_name='Mendoza',
            department=self.dept_ba,
            location=self.loc_fac_ba,
            position='Chairperson, BA',
            is_active=True
        )
        self.dept_ba.head = self.emp_chair_ba
        self.dept_ba.save()

        self.emp_chair_acct = Employee.objects.create(
            user=self.chair_acct_user,
            employee_id='EMP-CH-02',
            first_name='Elena',
            last_name='Santos',
            department=self.dept_acct,
            location=self.loc_fac_acct,
            position='Chairperson, Accountancy',
            is_active=True
        )
        self.dept_acct.head = self.emp_chair_acct
        self.dept_acct.save()

        self.emp_faculty1 = Employee.objects.create(
            user=self.faculty_user1,
            employee_id='EMP-FAC-01',
            first_name='Maria',
            last_name='Clara',
            department=self.dept_ba,
            location=self.loc_fac_ba,
            position='Assistant Professor',
            is_active=True
        )

        self.emp_faculty2 = Employee.objects.create(
            user=self.faculty_user2,
            employee_id='EMP-FAC-02',
            first_name='Jose',
            last_name='Rizal',
            department=self.dept_acct,
            location=self.loc_fac_acct,
            position='Associate Professor',
            is_active=True
        )

        # Category and Brand
        self.cat_av = AssetCategory.objects.create(code='AV', name='Audio-Visual')
        self.brand_epson = Brand.objects.create(name='Epson')

        # Durable Assets
        self.asset_projector = Asset.objects.create(
            item_name='Epson EB-E01 Projector',
            category=self.cat_av,
            brand=self.brand_epson,
            model='EB-E01',
            property_number='NORSU-CBA-2026-AV101',
            department=self.dept_ba,
            current_location=self.loc_storage,
            condition=Asset.Condition.GOOD,
            status=Asset.Status.AVAILABLE,
            acquisition_date=timezone.now().date() - timedelta(days=60),
            acquisition_cost=Decimal('25000.00'),
            created_by=self.admin_user
        )

        self.asset_clicker = Asset.objects.create(
            item_name='Wireless Presentation Clicker',
            category=self.cat_av,
            brand=self.brand_epson,
            model='Click-90',
            property_number='NORSU-CBA-2026-AV102',
            department=self.dept_acct,
            current_location=self.loc_storage,
            condition=Asset.Condition.GOOD,
            status=Asset.Status.AVAILABLE,
            acquisition_date=timezone.now().date() - timedelta(days=60),
            acquisition_cost=Decimal('3500.00'),
            created_by=self.admin_user
        )

        # Clients
        self.client_admin = Client()
        self.client_admin.force_login(self.admin_user)

        self.client_dean = Client()
        self.client_dean.force_login(self.dean_user)

        self.client_chair_ba = Client()
        self.client_chair_ba.force_login(self.chair_ba_user)

        self.client_faculty1 = Client()
        self.client_faculty1.force_login(self.faculty_user1)

        self.client_faculty2 = Client()
        self.client_faculty2.force_login(self.faculty_user2)


class BorrowingModelTestCase(BorrowingBaseTestCase):
    """Verifies model validations, properties, deletion protection, and constraints."""

    def test_borrowing_creation_and_clean_validation(self):
        now = timezone.now()
        # Invalid: return datetime earlier than start datetime
        b = AssetBorrowing(
            asset=self.asset_projector,
            borrower=self.emp_faculty1,
            borrower_department=self.dept_ba,
            requested_start=now + timedelta(days=2),
            requested_return=now + timedelta(days=1),
            purpose='Lecture presentation'
        )
        with self.assertRaises(ValidationError):
            b.clean()

        # Valid: return datetime after start datetime
        b.requested_return = now + timedelta(days=2, hours=3)
        b.clean()
        b.save()
        self.assertIsNotNone(b.pk)
        self.assertEqual(b.status, AssetBorrowing.Status.PENDING)

    def test_overdue_property_and_effective_status(self):
        now = timezone.now()
        b = AssetBorrowing.objects.create(
            asset=self.asset_projector,
            borrower=self.emp_faculty1,
            borrower_department=self.dept_ba,
            requested_start=now - timedelta(days=2),
            requested_return=now - timedelta(hours=2),
            status=AssetBorrowing.Status.RELEASED,
            purpose='Overdue test'
        )
        self.assertTrue(b.is_overdue)
        self.assertEqual(b.effective_status, 'OVERDUE')

        # If already RETURNED, not overdue
        b.status = AssetBorrowing.Status.RETURNED
        self.assertFalse(b.is_overdue)
        self.assertEqual(b.effective_status, 'RETURNED')

    def test_asset_delete_protection_with_borrowing_history(self):
        now = timezone.now()
        AssetBorrowing.objects.create(
            asset=self.asset_projector,
            borrower=self.emp_faculty1,
            borrower_department=self.dept_ba,
            requested_start=now + timedelta(days=1),
            requested_return=now + timedelta(days=1, hours=2),
            purpose='Colloquium'
        )
        # Attempting to delete the asset directly must raise ProtectedError
        with self.assertRaises(ProtectedError):
            self.asset_projector.delete()


class ReservationConflictTestCase(BorrowingBaseTestCase):
    """Verifies datetime reservation conflict detection."""

    def test_detects_overlapping_reservation(self):
        now = timezone.now()
        # Approved reservation: Day 2, 10:00 to 14:00
        start1 = now + timedelta(days=2, hours=10)
        end1 = now + timedelta(days=2, hours=14)

        b1 = AssetBorrowing.objects.create(
            asset=self.asset_projector,
            borrower=self.emp_faculty1,
            borrower_department=self.dept_ba,
            requested_start=start1,
            requested_return=end1,
            status=AssetBorrowing.Status.APPROVED,
            purpose='Reserved slot'
        )

        # Conflicting request: Day 2, 12:00 to 16:00 (overlaps with b1)
        start2 = now + timedelta(days=2, hours=12)
        end2 = now + timedelta(days=2, hours=16)

        conflicts = borrowing_services.check_reservation_conflict(
            asset=self.asset_projector,
            requested_start=start2,
            requested_return=end2
        )
        self.assertTrue(conflicts.exists())
        self.assertEqual(conflicts.first().pk, b1.pk)

    def test_permits_non_overlapping_and_touching_boundary_reservation(self):
        now = timezone.now()
        # Approved reservation: Day 2, 10:00 to 14:00
        start1 = now + timedelta(days=2, hours=10)
        end1 = now + timedelta(days=2, hours=14)

        AssetBorrowing.objects.create(
            asset=self.asset_projector,
            borrower=self.emp_faculty1,
            borrower_department=self.dept_ba,
            requested_start=start1,
            requested_return=end1,
            status=AssetBorrowing.Status.APPROVED,
            purpose='Reserved slot 1'
        )

        # Touching boundary: starts exactly when slot 1 ends (14:00 to 18:00)
        start_touch = end1
        end_touch = now + timedelta(days=2, hours=18)

        conflicts = borrowing_services.check_reservation_conflict(
            asset=self.asset_projector,
            requested_start=start_touch,
            requested_return=end_touch
        )
        self.assertFalse(conflicts.exists())

        # Completely separate day: Day 3
        start_separate = now + timedelta(days=3, hours=9)
        end_separate = now + timedelta(days=3, hours=12)

        conflicts2 = borrowing_services.check_reservation_conflict(
            asset=self.asset_projector,
            requested_start=start_separate,
            requested_return=end_separate
        )
        self.assertFalse(conflicts2.exists())

    def test_rejected_and_cancelled_reservations_do_not_conflict(self):
        now = timezone.now()
        start1 = now + timedelta(days=2, hours=10)
        end1 = now + timedelta(days=2, hours=14)

        # Rejected reservation
        AssetBorrowing.objects.create(
            asset=self.asset_projector,
            borrower=self.emp_faculty1,
            borrower_department=self.dept_ba,
            requested_start=start1,
            requested_return=end1,
            status=AssetBorrowing.Status.REJECTED,
            purpose='Rejected request'
        )

        conflicts = borrowing_services.check_reservation_conflict(
            asset=self.asset_projector,
            requested_start=start1,
            requested_return=end1
        )
        self.assertFalse(conflicts.exists())


class BorrowingServiceTestCase(BorrowingBaseTestCase):
    """Verifies atomic lifecycle transitions, asset state, condition tracking, and audit logging."""

    def test_request_and_approval_workflow(self):
        now = timezone.now()
        b = borrowing_services.request_borrowing(
            asset=self.asset_projector,
            borrower=self.emp_faculty1,
            requested_start=now + timedelta(days=1),
            requested_return=now + timedelta(days=1, hours=3),
            purpose='Academic defense presentation'
        )
        self.assertEqual(b.status, AssetBorrowing.Status.PENDING)
        # In PENDING status, asset remains AVAILABLE
        self.asset_projector.refresh_from_db()
        self.assertEqual(self.asset_projector.status, Asset.Status.AVAILABLE)

        # Approve
        approved = borrowing_services.approve_borrowing(
            borrowing=b,
            reviewed_by=self.admin_user,
            remarks='Approved for defense'
        )
        self.assertEqual(approved.status, AssetBorrowing.Status.APPROVED)
        self.assertEqual(approved.reviewed_by, self.admin_user)
        # Even when APPROVED, asset is still AVAILABLE until physical release
        self.asset_projector.refresh_from_db()
        self.assertEqual(self.asset_projector.status, Asset.Status.AVAILABLE)

        # Audit log verification
        self.assertTrue(AuditLog.objects.filter(action='BORROW_REQUEST_APPROVED').exists())

    def test_rejection_workflow(self):
        now = timezone.now()
        b = borrowing_services.request_borrowing(
            asset=self.asset_projector,
            borrower=self.emp_faculty1,
            requested_start=now + timedelta(days=1),
            requested_return=now + timedelta(days=1, hours=3),
            purpose='Classroom movie'
        )
        rejected = borrowing_services.reject_borrowing(
            borrowing=b,
            reviewed_by=self.admin_user,
            rejection_reason='Non-academic use not permitted.'
        )
        self.assertEqual(rejected.status, AssetBorrowing.Status.REJECTED)
        self.assertEqual(rejected.rejection_reason, 'Non-academic use not permitted.')
        self.asset_projector.refresh_from_db()
        self.assertEqual(self.asset_projector.status, Asset.Status.AVAILABLE)
        self.assertTrue(AuditLog.objects.filter(action='BORROW_REQUEST_REJECTED').exists())

    def test_release_and_return_normal_condition(self):
        now = timezone.now()
        b = borrowing_services.request_borrowing(
            asset=self.asset_projector,
            borrower=self.emp_faculty1,
            requested_start=now,
            requested_return=now + timedelta(hours=4),
            purpose='Classroom lecture'
        )
        borrowing_services.approve_borrowing(borrowing=b, reviewed_by=self.admin_user)

        # Physical Release
        released = borrowing_services.release_asset(
            borrowing=b,
            released_by=self.admin_user,
            condition_at_release=Asset.Condition.GOOD,
            remarks='Released with HDMI cable.'
        )
        self.assertEqual(released.status, AssetBorrowing.Status.RELEASED)
        self.asset_projector.refresh_from_db()
        # Asset status transitions to BORROWED strictly on physical release
        self.assertEqual(self.asset_projector.status, Asset.Status.BORROWED)
        self.assertTrue(AuditLog.objects.filter(action='ASSET_BORROW_RELEASED').exists())

        # Return asset in GOOD condition
        returned = borrowing_services.return_borrowed_asset(
            borrowing=released,
            returned_to=self.admin_user,
            condition_at_return=Asset.Condition.GOOD,
            return_remarks='Returned complete and functional.'
        )
        self.assertEqual(returned.status, AssetBorrowing.Status.RETURNED)
        self.asset_projector.refresh_from_db()
        # Asset status transitions back to AVAILABLE
        self.assertEqual(self.asset_projector.status, Asset.Status.AVAILABLE)
        self.assertEqual(self.asset_projector.condition, Asset.Condition.GOOD)
        self.assertTrue(AuditLog.objects.filter(action='ASSET_BORROW_RETURNED').exists())

    def test_return_unserviceable_condition_marks_asset_damaged(self):
        now = timezone.now()
        b = borrowing_services.request_borrowing(
            asset=self.asset_projector,
            borrower=self.emp_faculty1,
            requested_start=now,
            requested_return=now + timedelta(hours=4),
            purpose='Outdoor assembly'
        )
        borrowing_services.approve_borrowing(borrowing=b, reviewed_by=self.admin_user)
        borrowing_services.release_asset(
            borrowing=b,
            released_by=self.admin_user,
            condition_at_release=Asset.Condition.GOOD
        )
        self.asset_projector.refresh_from_db()
        self.assertEqual(self.asset_projector.status, Asset.Status.BORROWED)

        # Return in UNSERVICEABLE condition
        returned = borrowing_services.return_borrowed_asset(
            borrowing=b,
            returned_to=self.admin_user,
            condition_at_return=Asset.Condition.UNSERVICEABLE,
            return_remarks='Lamp exploded during presentation; power unit burned.'
        )
        self.assertEqual(returned.status, AssetBorrowing.Status.RETURNED)
        self.asset_projector.refresh_from_db()
        # Asset must transition to DAMAGED, NOT available
        self.assertEqual(self.asset_projector.status, Asset.Status.DAMAGED)
        self.assertEqual(self.asset_projector.condition, Asset.Condition.UNSERVICEABLE)

    def test_cannot_release_second_borrowing_on_already_released_asset(self):
        now = timezone.now()
        b1 = borrowing_services.request_borrowing(
            asset=self.asset_projector,
            borrower=self.emp_faculty1,
            requested_start=now,
            requested_return=now + timedelta(hours=4),
            purpose='Lecture 1'
        )
        borrowing_services.approve_borrowing(borrowing=b1, reviewed_by=self.admin_user)
        borrowing_services.release_asset(borrowing=b1, released_by=self.admin_user)

        # Create second borrowing in APPROVED status
        b2 = AssetBorrowing.objects.create(
            asset=self.asset_projector,
            borrower=self.emp_faculty2,
            borrower_department=self.dept_acct,
            requested_start=now + timedelta(hours=5),
            requested_return=now + timedelta(hours=8),
            status=AssetBorrowing.Status.APPROVED,
            purpose='Lecture 2'
        )
        # Attempting to release b2 while b1 is RELEASED must raise ValidationError
        with self.assertRaises(ValidationError):
            borrowing_services.release_asset(borrowing=b2, released_by=self.admin_user)

    def test_cancellation_rules(self):
        now = timezone.now()
        b = borrowing_services.request_borrowing(
            asset=self.asset_projector,
            borrower=self.emp_faculty1,
            requested_start=now + timedelta(days=2),
            requested_return=now + timedelta(days=2, hours=3),
            purpose='Event'
        )
        # Borrower can cancel their own PENDING request
        cancelled = borrowing_services.cancel_borrowing(
            borrowing=b,
            cancelled_by=self.faculty_user1,
            reason='Class canceled.'
        )
        self.assertEqual(cancelled.status, AssetBorrowing.Status.CANCELLED)

        # RELEASED borrowing cannot be cancelled
        b2 = borrowing_services.request_borrowing(
            asset=self.asset_clicker,
            borrower=self.emp_faculty2,
            requested_start=now,
            requested_return=now + timedelta(hours=3),
            purpose='Clicker event'
        )
        borrowing_services.approve_borrowing(borrowing=b2, reviewed_by=self.admin_user)
        borrowing_services.release_asset(borrowing=b2, released_by=self.admin_user)
        with self.assertRaises(ValidationError):
            borrowing_services.cancel_borrowing(borrowing=b2, cancelled_by=self.admin_user)


class BorrowingRBACTestCase(BorrowingBaseTestCase):
    """Verifies strict conservative RBAC enforcement on borrowing views."""

    def setUp(self):
        super().setUp()
        now = timezone.now()
        self.borrowing_ba = AssetBorrowing.objects.create(
            asset=self.asset_projector,
            borrower=self.emp_faculty1,
            borrower_department=self.dept_ba,
            requested_start=now + timedelta(days=1),
            requested_return=now + timedelta(days=1, hours=3),
            status=AssetBorrowing.Status.PENDING,
            purpose='BA Lecture'
        )
        self.borrowing_acct = AssetBorrowing.objects.create(
            asset=self.asset_clicker,
            borrower=self.emp_faculty2,
            borrower_department=self.dept_acct,
            requested_start=now + timedelta(days=2),
            requested_return=now + timedelta(days=2, hours=3),
            status=AssetBorrowing.Status.PENDING,
            purpose='ACCT Lecture'
        )

    def test_admin_has_full_queue_and_action_access(self):
        resp = self.client_admin.get(reverse('borrowing:request_list'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, self.asset_projector.asset_code)
        self.assertContains(resp, self.asset_clicker.asset_code)

        # Admin can approve
        resp_appr = self.client_admin.post(
            reverse('borrowing:borrowing_approve', kwargs={'pk': self.borrowing_ba.pk}),
            {'remarks': 'Approved by admin'}
        )
        self.assertEqual(resp_appr.status_code, 302)
        self.borrowing_ba.refresh_from_db()
        self.assertEqual(self.borrowing_ba.status, AssetBorrowing.Status.APPROVED)

    def test_dean_has_read_only_access_and_cannot_mutate(self):
        # Dean can view queue
        resp = self.client_dean.get(reverse('borrowing:request_list'))
        self.assertEqual(resp.status_code, 200)

        # Dean CANNOT approve (403)
        resp_appr = self.client_dean.post(
            reverse('borrowing:borrowing_approve', kwargs={'pk': self.borrowing_ba.pk}),
            {'remarks': 'Dean approval attempt'}
        )
        self.assertEqual(resp_appr.status_code, 403)

        # Dean CANNOT reject (403)
        resp_rej = self.client_dean.post(
            reverse('borrowing:borrowing_reject', kwargs={'pk': self.borrowing_ba.pk}),
            {'rejection_reason': 'Dean rejection attempt'}
        )
        self.assertEqual(resp_rej.status_code, 403)

    def test_chair_has_department_scoped_read_only_access(self):
        # Chair BA only sees requests in BA department
        resp = self.client_chair_ba.get(reverse('borrowing:request_list'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, self.asset_projector.asset_code)
        self.assertNotContains(resp, self.asset_clicker.asset_code)

        # Chair CANNOT approve (403)
        resp_appr = self.client_chair_ba.post(
            reverse('borrowing:borrowing_approve', kwargs={'pk': self.borrowing_ba.pk}),
            {'remarks': 'Chair approval attempt'}
        )
        self.assertEqual(resp_appr.status_code, 403)

    def test_faculty_queue_restrictions_and_personal_portal(self):
        # Faculty is redirected to My Borrowings when accessing admin queues
        resp_list = self.client_faculty1.get(reverse('borrowing:request_list'))
        self.assertEqual(resp_list.status_code, 302)
        self.assertRedirects(resp_list, reverse('borrowing:my_borrowings'))

        resp_active = self.client_faculty1.get(reverse('borrowing:active_list'))
        self.assertEqual(resp_active.status_code, 302)
        self.assertRedirects(resp_active, reverse('borrowing:my_borrowings'))

        # Faculty CAN access My Borrowings portal
        resp_my = self.client_faculty1.get(reverse('borrowing:my_borrowings'))
        self.assertEqual(resp_my.status_code, 200)
        self.assertContains(resp_my, 'BA Lecture')

        # Faculty CANNOT view other faculty's borrowing detail (403)
        resp_other = self.client_faculty1.get(
            reverse('borrowing:borrowing_detail', kwargs={'pk': self.borrowing_acct.pk})
        )
        self.assertEqual(resp_other.status_code, 403)

        # Faculty CANNOT approve (403)
        resp_appr = self.client_faculty1.post(
            reverse('borrowing:borrowing_approve', kwargs={'pk': self.borrowing_ba.pk}),
            {'remarks': 'Self-approval attempt'}
        )
        self.assertEqual(resp_appr.status_code, 403)

        # Faculty CAN cancel own PENDING request
        resp_cancel = self.client_faculty1.post(
            reverse('borrowing:borrowing_cancel', kwargs={'pk': self.borrowing_ba.pk}),
            {'reason': 'Changed my mind'}
        )
        self.assertEqual(resp_cancel.status_code, 302)
        self.borrowing_ba.refresh_from_db()
        self.assertEqual(self.borrowing_ba.status, AssetBorrowing.Status.CANCELLED)


class QRAndIntegrationTestCase(BorrowingBaseTestCase):
    """Verifies QR asset lookup, scan gateway, and inventory integration for borrowings."""

    def test_qr_lookup_displays_borrowing_status_and_actions(self):
        now = timezone.now()
        # Approve and release projector to faculty 1
        b = borrowing_services.request_borrowing(
            asset=self.asset_projector,
            borrower=self.emp_faculty1,
            requested_start=now,
            requested_return=now + timedelta(hours=3),
            purpose='AV presentation'
        )
        borrowing_services.approve_borrowing(borrowing=b, reviewed_by=self.admin_user)
        borrowing_services.release_asset(borrowing=b, released_by=self.admin_user)

        # Admin scans QR
        resp = self.client_admin.get(
            reverse('qr_asset_lookup', kwargs={'asset_code': self.asset_projector.asset_code})
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Equipment Currently On Loan')
        self.assertContains(resp, self.emp_faculty1.full_name)
        self.assertContains(resp, 'Process Equipment Return')

        # Faculty 1 (the borrower) can also view the QR lookup of the equipment they are holding
        resp_fac = self.client_faculty1.get(
            reverse('qr_asset_lookup', kwargs={'asset_code': self.asset_projector.asset_code})
        )
        self.assertEqual(resp_fac.status_code, 200)
        self.assertContains(resp_fac, 'Equipment Currently On Loan')

        # Faculty 2 (unrelated) gets PermissionDenied (403) when scanning someone else's borrowed equipment
        resp_fac2 = self.client_faculty2.get(
            reverse('qr_asset_lookup', kwargs={'asset_code': self.asset_projector.asset_code})
        )
        self.assertEqual(resp_fac2.status_code, 403)

    def test_asset_detail_displays_borrowing_card(self):
        now = timezone.now()
        b = borrowing_services.request_borrowing(
            asset=self.asset_projector,
            borrower=self.emp_faculty1,
            requested_start=now,
            requested_return=now + timedelta(hours=3),
            purpose='AV presentation in AVR 2'
        )
        borrowing_services.approve_borrowing(borrowing=b, reviewed_by=self.admin_user)
        borrowing_services.release_asset(borrowing=b, released_by=self.admin_user)

        resp = self.client_admin.get(
            reverse('inventory:asset_detail', kwargs={'asset_code': self.asset_projector.asset_code})
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Temporary Loan &amp; Reservation')
        self.assertContains(resp, 'Currently Borrowed')
        self.assertContains(resp, self.emp_faculty1.full_name)
        self.assertContains(resp, 'Return Loan')

    def test_asset_delete_view_protects_asset_with_borrowing_history(self):
        now = timezone.now()
        borrowing_services.request_borrowing(
            asset=self.asset_projector,
            borrower=self.emp_faculty1,
            requested_start=now + timedelta(days=1),
            requested_return=now + timedelta(days=1, hours=2),
            purpose='Colloquium'
        )
        # Attempt to delete via AssetDeleteView
        resp = self.client_admin.post(
            reverse('inventory:asset_delete', kwargs={'asset_code': self.asset_projector.asset_code})
        )
        # Should redirect back to asset detail with error message
        self.assertEqual(resp.status_code, 302)
        # Asset should still exist
        self.assertTrue(Asset.objects.filter(asset_code=self.asset_projector.asset_code).exists())
