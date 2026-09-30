from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from django.core.exceptions import ValidationError, PermissionDenied
from django.db.models import ProtectedError
from datetime import date, timedelta
from decimal import Decimal

from apps.accounts.models import User
from apps.organizations.models import Department, Location, Employee
from apps.inventory.models import AssetCategory, Brand, Asset
from apps.assignments.models import AssetAssignment
from apps.assignments import services as assignment_services
from apps.transfers.models import AssetTransfer
from apps.transfers import services as transfer_services
from apps.transfers.forms import AssetTransferRequestForm
from apps.audit.models import AuditLog


class TransferBaseTestCase(TestCase):
    """Sets up realistic organizational entities, users with roles, and assets."""

    def setUp(self):
        # Departments
        self.dept_ba = Department.objects.create(code='BA', name='Department of Business Administration')
        self.dept_acct = Department.objects.create(code='ACCT', name='Department of Accountancy')
        self.dept_hm = Department.objects.create(code='HM', name='Department of Hospitality Management')

        # Locations with distinct building & room numbers to respect unique constraint
        self.loc_storage = Location.objects.create(
            name='Storage Room', building='CBA Main', room_number='B-01', department=self.dept_ba
        )
        self.loc_dean = Location.objects.create(
            name="Dean's Office", building='CBA Main', room_number='101', department=self.dept_ba
        )
        self.loc_ba_fac = Location.objects.create(
            name='BA Faculty Room', building='CBA Main', room_number='205', department=self.dept_ba
        )
        self.loc_acct_off = Location.objects.create(
            name='Accountancy Dept Office', building='CBA Annex', room_number='302', department=self.dept_acct
        )
        self.loc_hm_lab = Location.objects.create(
            name='HM Training Center', building='CBA Annex', room_number='105', department=self.dept_hm
        )

        # Users
        self.admin_user = User.objects.create_superuser('admin_custodian', 'admin@cba.edu', 'Pass1234!')
        self.admin_user.role = User.Role.ADMIN
        self.admin_user.save()

        self.dean_user = User.objects.create_user('dean_robert', 'dean@cba.edu', 'Pass1234!', role=User.Role.DEAN)
        self.chair_ba_user = User.objects.create_user('chair_ba', 'chair.ba@cba.edu', 'Pass1234!', role=User.Role.DEPT_CHAIR)
        self.chair_acct_user = User.objects.create_user('chair_acct', 'chair.acct@cba.edu', 'Pass1234!', role=User.Role.DEPT_CHAIR)
        self.faculty_user = User.objects.create_user('faculty_maria', 'maria@cba.edu', 'Pass1234!', role=User.Role.FACULTY)

        # Employee Profiles
        self.emp_chair_ba = Employee.objects.create(
            user=self.chair_ba_user,
            employee_id='EMP-CBA-001',
            first_name='Carlos',
            last_name='Mendoza',
            department=self.dept_ba,
            location=self.loc_ba_fac,
            position='Chairperson, BA',
            is_active=True
        )
        self.dept_ba.head = self.emp_chair_ba
        self.dept_ba.save()

        self.emp_chair_acct = Employee.objects.create(
            user=self.chair_acct_user,
            employee_id='EMP-ACCT-001',
            first_name='Elena',
            last_name='Santos',
            department=self.dept_acct,
            location=self.loc_acct_off,
            position='Chairperson, Accountancy',
            is_active=True
        )
        self.dept_acct.head = self.emp_chair_acct
        self.dept_acct.save()

        self.emp_faculty = Employee.objects.create(
            user=self.faculty_user,
            employee_id='EMP-FAC-001',
            first_name='Maria',
            last_name='Santos',
            department=self.dept_ba,
            location=self.loc_ba_fac,
            position='Assistant Professor',
            is_active=True
        )

        # Asset Category & Brand
        self.cat_it = AssetCategory.objects.create(name='Information Technology', code='IT')
        self.cat_oe = AssetCategory.objects.create(name='Office Equipment', code='OE')
        self.brand_epson = Brand.objects.create(name='Epson')
        self.brand_lenovo = Brand.objects.create(name='Lenovo')

        # Assets
        self.asset_available = Asset.objects.create(
            asset_code='CBA-OE-00021',
            item_name='Epson EcoTank L3210 Printer',
            category=self.cat_oe,
            brand=self.brand_epson,
            department=self.dept_ba,
            current_location=self.loc_storage,
            condition=Asset.Condition.GOOD,
            status=Asset.Status.AVAILABLE,
            acquisition_cost=Decimal('12500.00'),
            created_by=self.admin_user
        )

        self.asset_assigned = Asset.objects.create(
            asset_code='CBA-IT-00022',
            item_name='Lenovo ThinkPad L14 Laptop',
            category=self.cat_it,
            brand=self.brand_lenovo,
            department=self.dept_ba,
            current_location=self.loc_ba_fac,
            condition=Asset.Condition.GOOD,
            status=Asset.Status.AVAILABLE,
            acquisition_cost=Decimal('54000.00'),
            created_by=self.admin_user
        )

        # Assign asset_assigned to emp_faculty
        self.active_assignment = assignment_services.assign_asset(
            asset=self.asset_assigned,
            employee=self.emp_faculty,
            assigned_by=self.admin_user,
            purpose='Classroom Instruction and Research'
        )
        self.asset_assigned.refresh_from_db()


class AssetTransferModelTests(TransferBaseTestCase):
    """Tests model validation, origin snapshot immutability, constraints, and protect cascades."""

    def test_create_transfer_and_origin_snapshot(self):
        """Origin department and location snapshots represent state at creation time."""
        transfer = transfer_services.request_transfer(
            asset=self.asset_available,
            to_department=self.dept_ba,
            to_location=self.loc_dean,
            requested_by=self.admin_user,
            reason='Administrative deployment'
        )

        self.assertEqual(transfer.status, AssetTransfer.Status.PENDING)
        self.assertEqual(transfer.from_department, self.dept_ba)
        self.assertEqual(transfer.from_location, self.loc_storage)
        self.assertEqual(transfer.to_department, self.dept_ba)
        self.assertEqual(transfer.to_location, self.loc_dean)
        self.assertTrue(transfer.is_open)
        self.assertFalse(transfer.is_completed)

    def test_single_open_transfer_constraint(self):
        """An asset cannot have multiple simultaneous open (PENDING/APPROVED) transfers."""
        transfer_services.request_transfer(
            asset=self.asset_available,
            to_department=self.dept_ba,
            to_location=self.loc_dean,
            requested_by=self.admin_user,
            reason='First request'
        )

        # Attempting second open transfer on the same asset must fail
        with self.assertRaises(ValidationError):
            transfer_services.request_transfer(
                asset=self.asset_available,
                to_department=self.dept_acct,
                to_location=self.loc_acct_off,
                requested_by=self.admin_user,
                reason='Second conflicting request'
            )

    def test_deletion_protection_on_referenced_entities(self):
        """Asset, Department, and Location referenced in transfers cannot be deleted (PROTECT)."""
        transfer = transfer_services.request_transfer(
            asset=self.asset_available,
            to_department=self.dept_ba,
            to_location=self.loc_dean,
            requested_by=self.admin_user,
            reason='Office deployment'
        )

        with self.assertRaises(ProtectedError):
            self.asset_available.delete()

        with self.assertRaises(ProtectedError):
            self.dept_ba.delete()

        with self.assertRaises(ProtectedError):
            self.loc_storage.delete()


class AssetTransferServiceTests(TransferBaseTestCase):
    """Tests transfer lifecycle transitions, state preservation, conflicts, and audit trails."""

    def test_request_transfer_same_origin_and_destination_rejected(self):
        """A transfer with identical origin and destination is rejected."""
        with self.assertRaises(ValidationError) as cm:
            transfer_services.request_transfer(
                asset=self.asset_available,
                to_department=self.dept_ba,
                to_location=self.loc_storage,  # same location and department
                requested_by=self.admin_user,
                reason='Redundant move'
            )
        self.assertIn('cannot be identical', str(cm.exception))

    def test_request_transfer_ineligible_asset_status_rejected(self):
        """Assets that are DAMAGED, LOST, or MAINTENANCE cannot be transferred."""
        self.asset_available.status = Asset.Status.DAMAGED
        self.asset_available.save()

        with self.assertRaises(ValidationError) as cm:
            transfer_services.request_transfer(
                asset=self.asset_available,
                to_department=self.dept_ba,
                to_location=self.loc_dean,
                requested_by=self.admin_user,
                reason='Damaged asset transfer'
            )
        self.assertIn('cannot be transferred', str(cm.exception))

    def test_request_transfer_mismatched_department_location_rejected(self):
        """Selecting a destination location belonging to another department is rejected."""
        with self.assertRaises(ValidationError) as cm:
            transfer_services.request_transfer(
                asset=self.asset_available,
                to_department=self.dept_ba,
                to_location=self.loc_acct_off,  # belongs to Accountancy, not BA
                requested_by=self.admin_user,
                reason='Mismatched location'
            )
        self.assertIn('belongs to', str(cm.exception))

    def test_approve_and_complete_available_asset(self):
        """
        Complete lifecycle for AVAILABLE asset:
        PENDING -> APPROVED -> COMPLETED
        Asset department and location update; status remains AVAILABLE.
        """
        transfer = transfer_services.request_transfer(
            asset=self.asset_available,
            to_department=self.dept_ba,
            to_location=self.loc_dean,
            requested_by=self.admin_user,
            reason='Dean office relocation'
        )

        # 1. Approve
        approved = transfer_services.approve_transfer(
            transfer=transfer,
            approved_by=self.admin_user,
            remarks='Approved for relocation'
        )
        self.assertEqual(approved.status, AssetTransfer.Status.APPROVED)
        self.assertIsNotNone(approved.approved_at)

        # 2. Complete
        completed = transfer_services.complete_transfer(
            transfer=approved,
            processed_by=self.admin_user,
            remarks='Delivered and verified in Room 101'
        )
        self.assertEqual(completed.status, AssetTransfer.Status.COMPLETED)
        self.assertIsNotNone(completed.completed_at)

        # Asset State Verification
        self.asset_available.refresh_from_db()
        self.assertEqual(self.asset_available.department, self.dept_ba)
        self.assertEqual(self.asset_available.current_location, self.loc_dean)
        self.assertEqual(self.asset_available.status, Asset.Status.AVAILABLE)  # Preserved!

        # Audit Log Check
        self.assertTrue(AuditLog.objects.filter(action='TRANSFER_COMPLETED').exists())

    def test_transfer_assigned_asset_preserves_accountability(self):
        """
        Transferring an ASSIGNED asset relocates physical location but preserves
        personal employee accountability.
        """
        self.assertEqual(self.asset_assigned.status, Asset.Status.ASSIGNED)

        transfer = transfer_services.request_transfer(
            asset=self.asset_assigned,
            to_department=self.dept_acct,
            to_location=self.loc_acct_off,
            requested_by=self.admin_user,
            reason='Faculty teaching reallocation'
        )
        transfer_services.approve_transfer(transfer, self.admin_user)
        transfer_services.complete_transfer(transfer, self.admin_user)

        self.asset_assigned.refresh_from_db()
        self.assertEqual(self.asset_assigned.department, self.dept_acct)
        self.assertEqual(self.asset_assigned.current_location, self.loc_acct_off)
        self.assertEqual(self.asset_assigned.status, Asset.Status.ASSIGNED)  # Preserved!

        # Employee accountability check: still active and assigned to emp_faculty
        active_assign = self.asset_assigned.assignments.filter(status=AssetAssignment.Status.ACTIVE).first()
        self.assertIsNotNone(active_assign)
        self.assertEqual(active_assign.employee, self.emp_faculty)

    def test_stale_source_state_conflict_rejected(self):
        """
        If asset's actual current location changes between request and completion,
        completion must be rejected with a stale origin conflict.
        """
        transfer = transfer_services.request_transfer(
            asset=self.asset_available,
            to_department=self.dept_ba,
            to_location=self.loc_dean,
            requested_by=self.admin_user,
            reason='Dean office relocation'
        )
        transfer_services.approve_transfer(transfer, self.admin_user)

        # Manually simulate another operation changing asset's current location
        self.asset_available.current_location = self.loc_ba_fac
        self.asset_available.save(update_fields=['current_location'])

        # Attempting completion must detect origin conflict
        with self.assertRaises(ValidationError) as cm:
            transfer_services.complete_transfer(transfer, self.admin_user)
        self.assertIn('Origin conflict', str(cm.exception))

    def test_reject_and_cancel_transfer(self):
        """Tests rejection of pending transfer and cancellation of approved transfer."""
        # 1. Reject
        t1 = transfer_services.request_transfer(
            asset=self.asset_available,
            to_department=self.dept_ba,
            to_location=self.loc_dean,
            requested_by=self.admin_user,
            reason='Request to reject'
        )
        rejected = transfer_services.reject_transfer(t1, self.admin_user, reason='Budget reallocated')
        self.assertEqual(rejected.status, AssetTransfer.Status.REJECTED)

        # 2. Cancel approved transfer
        t2 = transfer_services.request_transfer(
            asset=self.asset_available,
            to_department=self.dept_ba,
            to_location=self.loc_dean,
            requested_by=self.admin_user,
            reason='Request to cancel'
        )
        transfer_services.approve_transfer(t2, self.admin_user)
        cancelled = transfer_services.cancel_transfer(t2, self.admin_user, reason='Equipment needed elsewhere')
        self.assertEqual(cancelled.status, AssetTransfer.Status.CANCELLED)
        self.assertIsNotNone(cancelled.cancelled_at)


class AssetTransferViewAndRBACTests(TransferBaseTestCase):
    """Tests HTTP views, scoping, permissions, and delete protection."""

    def setUp(self):
        super().setUp()
        self.client = Client()

        # Create sample transfers
        # Transfer 1: BA -> BA (loc_storage -> loc_dean)
        self.t_ba = transfer_services.request_transfer(
            asset=self.asset_available,
            to_department=self.dept_ba,
            to_location=self.loc_dean,
            requested_by=self.admin_user,
            reason='BA office move'
        )

        # Extra asset for create/reject/cancel testing
        self.asset_extra = Asset.objects.create(
            asset_code='CBA-OE-00099',
            item_name='Canon ImageClass Copier',
            category=self.cat_oe,
            brand=self.brand_epson,
            department=self.dept_acct,
            current_location=self.loc_acct_off,
            condition=Asset.Condition.GOOD,
            status=Asset.Status.AVAILABLE,
            acquisition_cost=Decimal('35000.00'),
            created_by=self.admin_user
        )

    def test_admin_full_transfer_access(self):
        """Admin can access pending list, history, request form, detail, and execute actions."""
        self.client.force_login(self.admin_user)

        # View lists and forms
        res = self.client.get(reverse('transfers:pending_list'))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'CBA-OE-00021')

        res = self.client.get(reverse('transfers:history_list'))
        self.assertEqual(res.status_code, 200)

        res = self.client.get(reverse('transfers:transfer_request'))
        self.assertEqual(res.status_code, 200)

        res = self.client.get(reverse('transfers:transfer_detail', kwargs={'pk': self.t_ba.pk}))
        self.assertEqual(res.status_code, 200)

        # 1. Admin can create transfer
        res = self.client.post(reverse('transfers:transfer_request'), {
            'asset': self.asset_extra.pk,
            'to_department': self.dept_ba.pk,
            'to_location': self.loc_dean.pk,
            'transfer_date': timezone.now().date(),
            'reason': 'Relocating to Dean office',
            'remarks': 'Approved by custodian'
        })
        self.assertRedirects(res, reverse('transfers:pending_list'))
        created_t = AssetTransfer.objects.get(asset=self.asset_extra)
        self.assertEqual(created_t.status, AssetTransfer.Status.PENDING)

        # 2. Admin can approve transfer
        res = self.client.post(reverse('transfers:transfer_approve', kwargs={'pk': self.t_ba.pk}), {'remarks': 'Approved'})
        self.assertRedirects(res, reverse('transfers:pending_list'))
        self.t_ba.refresh_from_db()
        self.assertEqual(self.t_ba.status, AssetTransfer.Status.APPROVED)

        # 3. Admin can complete transfer
        res = self.client.post(reverse('transfers:transfer_complete', kwargs={'pk': self.t_ba.pk}), {'remarks': 'Arrived'})
        self.assertRedirects(res, reverse('inventory:asset_detail', kwargs={'asset_code': self.asset_available.asset_code}))
        self.t_ba.refresh_from_db()
        self.assertEqual(self.t_ba.status, AssetTransfer.Status.COMPLETED)
        self.asset_available.refresh_from_db()
        self.assertEqual(self.asset_available.current_location, self.loc_dean)

        # 4. Admin can reject transfer
        res = self.client.post(reverse('transfers:transfer_reject', kwargs={'pk': created_t.pk}), {'reason': 'Budget constraints'})
        self.assertRedirects(res, reverse('transfers:pending_list'))
        created_t.refresh_from_db()
        self.assertEqual(created_t.status, AssetTransfer.Status.REJECTED)

        # 5. Admin can cancel transfer
        t_to_cancel = transfer_services.request_transfer(
            asset=self.asset_extra,
            to_department=self.dept_ba,
            to_location=self.loc_storage,
            requested_by=self.admin_user,
            reason='Move to storage'
        )
        transfer_services.approve_transfer(t_to_cancel, self.admin_user)
        res = self.client.post(reverse('transfers:transfer_cancel', kwargs={'pk': t_to_cancel.pk}), {'reason': 'Cancelled'})
        self.assertRedirects(res, reverse('transfers:pending_list'))
        t_to_cancel.refresh_from_db()
        self.assertEqual(t_to_cancel.status, AssetTransfer.Status.CANCELLED)

    def test_dean_read_only_access(self):
        """
        Dean:
        - can view all transfers
        - can view transfer history
        - can view transfer details
        - cannot create transfer (GET and POST rejected)
        - cannot approve (POST rejected)
        - cannot reject (POST rejected)
        - cannot complete (POST rejected)
        - cannot cancel (POST rejected)
        - direct POST attempts are rejected
        """
        self.client.force_login(self.dean_user)

        # 1. Can view all transfers
        res = self.client.get(reverse('transfers:pending_list'))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'CBA-OE-00021')

        # 2. Can view transfer history
        res = self.client.get(reverse('transfers:history_list'))
        self.assertEqual(res.status_code, 200)

        # 3. Can view transfer details
        res = self.client.get(reverse('transfers:transfer_detail', kwargs={'pk': self.t_ba.pk}))
        self.assertEqual(res.status_code, 200)

        # 4. Cannot create transfer (GET & POST 403)
        res = self.client.get(reverse('transfers:transfer_request'))
        self.assertEqual(res.status_code, 403)

        res = self.client.post(reverse('transfers:transfer_request'), {
            'asset': self.asset_extra.pk,
            'to_department': self.dept_ba.pk,
            'to_location': self.loc_dean.pk,
            'transfer_date': timezone.now().date(),
            'reason': 'Dean unauthorized creation'
        })
        self.assertEqual(res.status_code, 403)

        # 5. Cannot approve transfer (POST 403)
        res = self.client.post(reverse('transfers:transfer_approve', kwargs={'pk': self.t_ba.pk}), {'remarks': 'Dean approve'})
        self.assertEqual(res.status_code, 403)

        # 6. Cannot reject transfer (POST 403)
        res = self.client.post(reverse('transfers:transfer_reject', kwargs={'pk': self.t_ba.pk}), {'reason': 'Dean reject'})
        self.assertEqual(res.status_code, 403)

        # 7. Cannot complete transfer (POST 403)
        res = self.client.post(reverse('transfers:transfer_complete', kwargs={'pk': self.t_ba.pk}), {'remarks': 'Dean complete'})
        self.assertEqual(res.status_code, 403)

        # 8. Cannot cancel transfer (POST 403)
        res = self.client.post(reverse('transfers:transfer_cancel', kwargs={'pk': self.t_ba.pk}), {'reason': 'Dean cancel'})
        self.assertEqual(res.status_code, 403)

        # Verify transfer status remained unaffected
        self.t_ba.refresh_from_db()
        self.assertEqual(self.t_ba.status, AssetTransfer.Status.PENDING)

    def test_dept_chair_department_scoped_visibility_and_restrictions(self):
        """
        Department Chair:
        - can view transfers involving their department
        - cannot see unrelated department transfers
        - cannot create transfer (GET and POST rejected)
        - cannot approve (POST rejected)
        - cannot reject (POST rejected)
        - cannot complete (POST rejected)
        - cannot cancel (POST rejected)
        - direct POST attempts are rejected
        """
        # 1. BA Chair sees BA transfer in list and detail
        self.client.force_login(self.chair_ba_user)
        res = self.client.get(reverse('transfers:pending_list'))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'CBA-OE-00021')

        res = self.client.get(reverse('transfers:transfer_detail', kwargs={'pk': self.t_ba.pk}))
        self.assertEqual(res.status_code, 200)

        # 2. ACCT Chair does NOT see BA internal transfer and cannot view its detail (403)
        self.client.force_login(self.chair_acct_user)
        res = self.client.get(reverse('transfers:pending_list'))
        self.assertEqual(res.status_code, 200)
        self.assertNotContains(res, 'CBA-OE-00021')

        res = self.client.get(reverse('transfers:transfer_detail', kwargs={'pk': self.t_ba.pk}))
        self.assertEqual(res.status_code, 403)

        # 3. Chair cannot create transfer (GET and POST return 403)
        res = self.client.get(reverse('transfers:transfer_request'))
        self.assertEqual(res.status_code, 403)

        res = self.client.post(reverse('transfers:transfer_request'), {
            'asset': self.asset_extra.pk,
            'to_department': self.dept_ba.pk,
            'to_location': self.loc_dean.pk,
            'transfer_date': timezone.now().date(),
            'reason': 'Chair unauthorized creation'
        })
        self.assertEqual(res.status_code, 403)

        # 4. Chair cannot approve transfer (POST returns 403)
        res = self.client.post(reverse('transfers:transfer_approve', kwargs={'pk': self.t_ba.pk}), {'remarks': 'Chair approve'})
        self.assertEqual(res.status_code, 403)

        # 5. Chair cannot reject transfer (POST returns 403)
        res = self.client.post(reverse('transfers:transfer_reject', kwargs={'pk': self.t_ba.pk}), {'reason': 'Chair reject'})
        self.assertEqual(res.status_code, 403)

        # 6. Chair cannot complete transfer (POST returns 403)
        res = self.client.post(reverse('transfers:transfer_complete', kwargs={'pk': self.t_ba.pk}), {'remarks': 'Chair complete'})
        self.assertEqual(res.status_code, 403)

        # 7. Chair cannot cancel transfer (POST returns 403)
        res = self.client.post(reverse('transfers:transfer_cancel', kwargs={'pk': self.t_ba.pk}), {'reason': 'Chair cancel'})
        self.assertEqual(res.status_code, 403)

        # Verify transfer status remained unaffected
        self.t_ba.refresh_from_db()
        self.assertEqual(self.t_ba.status, AssetTransfer.Status.PENDING)

    def test_faculty_restricted_from_transfers(self):
        """
        Faculty:
        - cannot access transfer administration
        - can still see the current location of their assigned equipment through My Accountability
        - existing accountability access must remain functional
        """
        self.client.force_login(self.faculty_user)

        # Cannot browse transfer management pages
        res = self.client.get(reverse('transfers:pending_list'))
        self.assertRedirects(res, reverse('assignments:my_accountability'))

        res = self.client.get(reverse('transfers:history_list'))
        self.assertRedirects(res, reverse('assignments:my_accountability'))

        res = self.client.get(reverse('transfers:transfer_detail', kwargs={'pk': self.t_ba.pk}))
        self.assertRedirects(res, reverse('assignments:my_accountability'))

        # Direct action attempts rejected with 403
        res = self.client.get(reverse('transfers:transfer_request'))
        self.assertEqual(res.status_code, 403)

        res = self.client.post(reverse('transfers:transfer_request'), {
            'asset': self.asset_available.pk,
            'to_department': self.dept_ba.pk,
            'to_location': self.loc_dean.pk,
        })
        self.assertEqual(res.status_code, 403)

        res = self.client.post(reverse('transfers:transfer_approve', kwargs={'pk': self.t_ba.pk}))
        self.assertEqual(res.status_code, 403)

        res = self.client.post(reverse('transfers:transfer_reject', kwargs={'pk': self.t_ba.pk}))
        self.assertEqual(res.status_code, 403)

        res = self.client.post(reverse('transfers:transfer_complete', kwargs={'pk': self.t_ba.pk}))
        self.assertEqual(res.status_code, 403)

        res = self.client.post(reverse('transfers:transfer_cancel', kwargs={'pk': self.t_ba.pk}))
        self.assertEqual(res.status_code, 403)

        # Faculty can still see the current location of their assigned equipment through My Accountability
        res = self.client.get(reverse('assignments:my_accountability'))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'CBA-IT-00022')
        self.assertContains(res, self.loc_ba_fac.name)

        # Existing accountability access remains functional
        res = self.client.get(reverse('inventory:asset_detail', kwargs={'asset_code': self.asset_assigned.asset_code}))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'CBA-IT-00022')

    def test_asset_delete_protection_with_transfer_history(self):
        """Asset with transfer history cannot be deleted via AssetDeleteView."""
        self.client.force_login(self.admin_user)

        # Approve and complete the transfer
        transfer_services.approve_transfer(self.t_ba, self.admin_user)
        transfer_services.complete_transfer(self.t_ba, self.admin_user)

        # Attempt to delete the asset
        res = self.client.post(reverse('inventory:asset_delete', kwargs={'asset_code': self.asset_available.asset_code}))
        self.assertRedirects(res, reverse('inventory:asset_detail', kwargs={'asset_code': self.asset_available.asset_code}))
        self.assertTrue(Asset.objects.filter(asset_code=self.asset_available.asset_code).exists())
