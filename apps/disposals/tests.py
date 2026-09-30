from decimal import Decimal
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from django.core.exceptions import ValidationError, PermissionDenied
from datetime import timedelta, date

from apps.accounts.models import User
from apps.organizations.models import Department, Location, Employee
from apps.inventory.models import Asset, AssetCategory, Brand, AssetVerification
from apps.assignments.models import AssetAssignment
from apps.assignments import services as assignment_services
from apps.transfers.models import AssetTransfer
from apps.transfers import services as transfer_services
from apps.borrowing.models import AssetBorrowing
from apps.borrowing import services as borrowing_services
from apps.maintenance.models import AssetMaintenance
from apps.maintenance import services as maintenance_services
from apps.audit.models import AuditLog
from apps.disposals.models import AssetDisposal
from apps.disposals import services as disposal_services


class Phase9DisposalBaseTestCase(TestCase):
    def setUp(self):
        self.client = Client()

        # Users
        self.admin = User.objects.create_user(
            username='admin_test',
            password='password123',
            role=User.Role.ADMIN
        )
        self.dean = User.objects.create_user(
            username='dean_test',
            password='password123',
            role=User.Role.DEAN
        )
        self.chair = User.objects.create_user(
            username='chair_test',
            password='password123',
            role=User.Role.DEPT_CHAIR
        )
        self.faculty = User.objects.create_user(
            username='faculty_test',
            password='password123',
            role=User.Role.FACULTY
        )

        # Organization
        self.dept_ba = Department.objects.create(name='Business Administration', code='BA')
        self.dept_it = Department.objects.create(name='Information Technology', code='IT')

        self.loc_storage = Location.objects.create(name='Storage Room', building='Main Building', room_number='SR-101', department=self.dept_ba)
        self.loc_lab = Location.objects.create(name='Computer Lab', building='IT Wing', room_number='LAB-201', department=self.dept_it)

        self.emp_chair = Employee.objects.create(
            user=self.chair,
            employee_id='EMP-CHAIR-001',
            first_name='Chair',
            last_name='User',
            department=self.dept_ba,
            location=self.loc_storage,
            is_active=True
        )
        self.emp_faculty = Employee.objects.create(
            user=self.faculty,
            employee_id='EMP-FAC-001',
            first_name='Faculty',
            last_name='User',
            department=self.dept_ba,
            location=self.loc_storage,
            is_active=True
        )

        # Inventory
        self.category = AssetCategory.objects.create(name='Computers', code='IT')
        self.brand = Brand.objects.create(name='Dell')

        self.asset = Asset.objects.create(
            item_name='Test Workstation',
            category=self.category,
            brand=self.brand,
            department=self.dept_ba,
            current_location=self.loc_storage,
            condition=Asset.Condition.POOR,
            status=Asset.Status.AVAILABLE,
            acquisition_cost=Decimal('45000.00'),
            acquisition_date=date(2020, 1, 1),
            created_by=self.admin
        )


class DisposalModelAndNumberingTests(Phase9DisposalBaseTestCase):
    def test_disposal_number_format_and_sequence(self):
        """Test disposal number generates DSP-YYYY-XXXXX format sequentially."""
        year = timezone.now().year
        num1 = AssetDisposal.generate_disposal_number(year)
        self.assertTrue(num1.startswith(f"DSP-{year}-"))
        self.assertEqual(len(num1.split('-')[-1]), 5)

        d1 = AssetDisposal.objects.create(
            asset=self.asset,
            requested_by=self.admin,
            reason='Obsolete hardware',
            condition_at_disposal=Asset.Condition.POOR
        )
        self.assertEqual(d1.disposal_number, num1)

        num2 = AssetDisposal.generate_disposal_number(year)
        expected_seq = int(num1.split('-')[-1]) + 1
        self.assertEqual(int(num2.split('-')[-1]), expected_seq)

    def test_proceeds_negative_validation(self):
        """Validation error on negative proceeds."""
        dsp = AssetDisposal(
            asset=self.asset,
            requested_by=self.admin,
            reason='Negative proceeds test',
            condition_at_disposal=Asset.Condition.POOR,
            proceeds_amount=Decimal('-50.00')
        )
        with self.assertRaises(ValidationError):
            dsp.full_clean()


class DisposalServiceLifecycleTests(Phase9DisposalBaseTestCase):
    def test_complete_disposal_lifecycle(self):
        """Test PENDING -> APPROVED -> COMPLETED transitions and Asset.status -> DISPOSED."""
        # 1. Request
        dsp = disposal_services.request_disposal(
            asset=self.asset,
            requested_by=self.admin,
            reason='Total logic board failure and chassis crack',
            condition_at_disposal=Asset.Condition.UNSERVICEABLE
        )
        self.assertEqual(dsp.status, AssetDisposal.Status.PENDING)
        self.asset.refresh_from_db()
        # Invariant: asset status NOT yet modified
        self.assertEqual(self.asset.status, Asset.Status.AVAILABLE)

        # 2. Approve
        dsp = disposal_services.approve_disposal(
            disposal=dsp,
            reviewed_by=self.admin,
            review_remarks='Approved by Property Custodian'
        )
        self.assertEqual(dsp.status, AssetDisposal.Status.APPROVED)
        self.asset.refresh_from_db()
        self.assertEqual(self.asset.status, Asset.Status.AVAILABLE)

        # 3. Complete
        dsp = disposal_services.complete_disposal(
            disposal=dsp,
            processed_by=self.admin,
            disposal_method=AssetDisposal.DisposalMethod.SCRAP,
            disposal_date=timezone.now().date(),
            recipient_or_destination='Certified Green Recycler',
            reference_number='REC-9988',
            proceeds_amount=Decimal('500.00'),
            remarks='Parts sold for scrap metal'
        )
        self.assertEqual(dsp.status, AssetDisposal.Status.COMPLETED)
        self.assertIsNotNone(dsp.completed_at)

        # Invariant: Asset status is now DISPOSED
        self.asset.refresh_from_db()
        self.assertEqual(self.asset.status, Asset.Status.DISPOSED)

        # Audit logs recorded
        self.assertTrue(AuditLog.objects.filter(action='DISPOSAL_REQUESTED').exists())
        self.assertTrue(AuditLog.objects.filter(action='DISPOSAL_APPROVED').exists())
        self.assertTrue(AuditLog.objects.filter(action='ASSET_DISPOSED').exists())

    def test_reject_disposal_workflow(self):
        """Test PENDING -> REJECTED."""
        dsp = disposal_services.request_disposal(
            asset=self.asset,
            requested_by=self.admin,
            reason='Minor defect'
        )
        dsp = disposal_services.reject_disposal(
            disposal=dsp,
            reviewed_by=self.admin,
            review_remarks='Can still be repaired in-house.'
        )
        self.assertEqual(dsp.status, AssetDisposal.Status.REJECTED)
        self.asset.refresh_from_db()
        self.assertEqual(self.asset.status, Asset.Status.AVAILABLE)
        self.assertTrue(AuditLog.objects.filter(action='DISPOSAL_REJECTED').exists())

    def test_cancel_disposal_workflow(self):
        """Test PENDING or APPROVED -> CANCELLED."""
        dsp = disposal_services.request_disposal(
            asset=self.asset,
            requested_by=self.admin,
            reason='Duplicate entry test'
        )
        dsp = disposal_services.cancel_disposal(
            disposal=dsp,
            cancelled_by=self.admin,
            cancellation_reason='Created by mistake'
        )
        self.assertEqual(dsp.status, AssetDisposal.Status.CANCELLED)
        self.asset.refresh_from_db()
        self.assertEqual(self.asset.status, Asset.Status.AVAILABLE)
        self.assertTrue(AuditLog.objects.filter(action='DISPOSAL_CANCELLED').exists())


class DisposalEligibilityAndBlockingTests(Phase9DisposalBaseTestCase):
    def test_cannot_dispose_borrowed_asset(self):
        """Cannot request disposal while asset is physically on loan."""
        borrowing = borrowing_services.request_borrowing(
            asset=self.asset,
            borrower=self.emp_faculty,
            purpose='Lectures',
            requested_start=timezone.now() + timedelta(hours=1),
            requested_return=timezone.now() + timedelta(hours=5),
            created_by=self.admin
        )
        borrowing_services.approve_borrowing(borrowing, self.admin)
        borrowing_services.release_asset(borrowing, self.admin)

        self.asset.refresh_from_db()
        self.assertEqual(self.asset.status, Asset.Status.BORROWED)

        with self.assertRaises(ValidationError) as ctx:
            disposal_services.request_disposal(
                asset=self.asset,
                requested_by=self.admin,
                reason='Attempt while borrowed'
            )
        self.assertIn('on loan', str(ctx.exception))

    def test_cannot_dispose_asset_under_maintenance(self):
        """Cannot request disposal while asset is actively IN_REPAIR."""
        maint = maintenance_services.report_issue(
            asset=self.asset,
            reported_by=self.admin,
            issue_title='Broken PSU',
            issue_description='Smoke detected'
        )
        maintenance_services.assess_issue(
            maintenance=maint,
            assessed_by=self.admin,
            severity=AssetMaintenance.Severity.HIGH,
            diagnosis='Blown capacitors'
        )
        maintenance_services.start_repair(
            maintenance=maint,
            user=self.admin,
            service_provider='In-house IT'
        )
        self.asset.refresh_from_db()
        self.assertEqual(self.asset.status, Asset.Status.MAINTENANCE)

        with self.assertRaises(ValidationError) as ctx:
            disposal_services.request_disposal(
                asset=self.asset,
                requested_by=self.admin,
                reason='Attempt while in repair'
            )
        self.assertIn('under maintenance', str(ctx.exception))

    def test_cannot_complete_disposal_with_active_assignment(self):
        """Cannot complete disposal if asset has not undergone accountability turnover/return."""
        # Create an assignment
        assignment_services.assign_asset(
            asset=self.asset,
            employee=self.emp_faculty,
            assigned_by=self.admin,
            purpose='Teaching accountability'
        )
        self.asset.refresh_from_db()
        self.assertEqual(self.asset.status, Asset.Status.ASSIGNED)

        # Request and approve disposal
        dsp = disposal_services.request_disposal(
            asset=self.asset,
            requested_by=self.admin,
            reason='Condemned equipment'
        )
        disposal_services.approve_disposal(dsp, self.admin)

        # Attempt to complete without return
        with self.assertRaises(ValidationError) as ctx:
            disposal_services.complete_disposal(
                disposal=dsp,
                processed_by=self.admin,
                disposal_method=AssetDisposal.DisposalMethod.DESTRUCTION
            )
        self.assertIn("still assigned", str(ctx.exception))

        # Now return asset
        assignment = self.asset.assignments.get(status=AssetAssignment.Status.ACTIVE)
        assignment_services.return_asset(
            assignment=assignment,
            returned_by=self.admin,
            condition_at_return=Asset.Condition.UNSERVICEABLE
        )
        self.asset.refresh_from_db()

        # Now completion succeeds
        dsp = disposal_services.complete_disposal(
            disposal=dsp,
            processed_by=self.admin,
            disposal_method=AssetDisposal.DisposalMethod.DESTRUCTION
        )
        self.assertEqual(dsp.status, AssetDisposal.Status.COMPLETED)
        self.asset.refresh_from_db()
        self.assertEqual(self.asset.status, Asset.Status.DISPOSED)

    def test_disposed_asset_blocks_subsequent_operations(self):
        """Once Asset.status = DISPOSED, all other lifecycle modules must reject it."""
        dsp = disposal_services.request_disposal(self.asset, self.admin, 'Obsolete')
        disposal_services.approve_disposal(dsp, self.admin)
        disposal_services.complete_disposal(dsp, self.admin, AssetDisposal.DisposalMethod.SCRAP)

        self.asset.refresh_from_db()
        self.assertEqual(self.asset.status, Asset.Status.DISPOSED)

        # 1. Cannot assign
        with self.assertRaises(ValidationError):
            assignment_services.assign_asset(self.asset, self.emp_faculty, self.admin)

        # 2. Cannot transfer
        with self.assertRaises(ValidationError):
            transfer_services.request_transfer(self.asset, self.dept_it, self.loc_lab, self.admin)

        # 3. Cannot borrow
        with self.assertRaises(ValidationError):
            borrowing_services.request_borrowing(
                self.asset, self.emp_faculty, 'Class',
                timezone.now() + timedelta(hours=1), timezone.now() + timedelta(hours=2)
            )

        # 4. Cannot report maintenance
        with self.assertRaises(ValidationError):
            maintenance_services.report_issue(self.asset, self.admin, 'Test', 'Test defect')

        # 5. Cannot verify physical asset (via view)
        self.client.login(username='admin_test', password='password123')
        resp = self.client.get(reverse('inventory:asset_verify', kwargs={'asset_code': self.asset.asset_code}))
        self.assertEqual(resp.status_code, 302)  # redirected away with error


class DeletionAndHistoryProtectionTests(Phase9DisposalBaseTestCase):
    def test_asset_delete_blocked_when_disposal_record_exists(self):
        """Asset with disposal record cannot be permanently deleted."""
        disposal_services.request_disposal(self.asset, self.admin, 'End of life')

        self.client.login(username='admin_test', password='password123')
        del_url = reverse('inventory:asset_delete', kwargs={'asset_code': self.asset.asset_code})

        # GET confirmation page redirects away
        resp_get = self.client.get(del_url)
        self.assertEqual(resp_get.status_code, 302)

        # POST delete redirects away and does not delete
        resp_post = self.client.post(del_url)
        self.assertEqual(resp_post.status_code, 302)
        self.assertTrue(Asset.objects.filter(pk=self.asset.pk).exists())


class DisposalRBACTests(Phase9DisposalBaseTestCase):
    def test_dean_has_read_only_access(self):
        """Dean can view list and detail, but cannot mutate disposal workflows."""
        dsp = disposal_services.request_disposal(self.asset, self.admin, 'Test RBAC')

        self.client.login(username='dean_test', password='password123')

        # Can view queue and detail
        r1 = self.client.get(reverse('disposals:pending_list'))
        self.assertEqual(r1.status_code, 200)

        r2 = self.client.get(reverse('disposals:disposal_detail', kwargs={'pk': dsp.pk}))
        self.assertEqual(r2.status_code, 200)

        # CANNOT create request
        r3 = self.client.get(reverse('disposals:request_create'))
        self.assertEqual(r3.status_code, 403)

        # CANNOT approve
        r4 = self.client.get(reverse('disposals:disposal_approve', kwargs={'pk': dsp.pk}))
        self.assertEqual(r4.status_code, 403)

    def test_dept_chair_is_department_scoped_read_only(self):
        """Dept chair only sees assets in their department, and cannot mutate."""
        dsp_ba = disposal_services.request_disposal(self.asset, self.admin, 'BA Asset')

        # Asset in IT department
        asset_it = Asset.objects.create(
            item_name='IT Server',
            category=self.category,
            department=self.dept_it,
            status=Asset.Status.AVAILABLE,
            condition=Asset.Condition.POOR,
            created_by=self.admin
        )
        dsp_it = disposal_services.request_disposal(asset_it, self.admin, 'IT Asset')

        self.client.login(username='chair_test', password='password123')

        # Detail for BA asset is accessible
        r_ba = self.client.get(reverse('disposals:disposal_detail', kwargs={'pk': dsp_ba.pk}))
        self.assertEqual(r_ba.status_code, 200)

        # Detail for IT asset raises 403
        r_it = self.client.get(reverse('disposals:disposal_detail', kwargs={'pk': dsp_it.pk}))
        self.assertEqual(r_it.status_code, 403)

        # Mutation raises 403
        r_app = self.client.get(reverse('disposals:disposal_approve', kwargs={'pk': dsp_ba.pk}))
        self.assertEqual(r_app.status_code, 403)

    def test_faculty_forbidden_from_queue(self):
        """Ordinary faculty members cannot access the disposal queue."""
        self.client.login(username='faculty_test', password='password123')
        resp = self.client.get(reverse('disposals:pending_list'))
        self.assertEqual(resp.status_code, 403)
