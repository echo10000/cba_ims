from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from django.core.exceptions import ValidationError, PermissionDenied
from django.db.models import ProtectedError
from datetime import timedelta, date
from decimal import Decimal

from apps.accounts.models import User
from apps.organizations.models import Department, Location, Employee
from apps.inventory.models import AssetCategory, Brand, Asset
from apps.assignments.models import AssetAssignment
from apps.borrowing.models import AssetBorrowing
from apps.maintenance.models import AssetMaintenance
from apps.maintenance import services
from apps.audit.models import AuditLog


class MaintenanceBaseTestCase(TestCase):
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
            position='Associate Professor',
            is_active=True
        )

        self.emp_faculty2 = Employee.objects.create(
            user=self.faculty_user2,
            employee_id='EMP-FAC-02',
            first_name='Jose',
            last_name='Rizal',
            department=self.dept_acct,
            location=self.loc_fac_acct,
            position='Instructor',
            is_active=True
        )

        # Category & Brand
        self.cat_it = AssetCategory.objects.create(
            code='IT', name='IT Equipment', description='Computers and peripherals'
        )
        self.brand_hp = Brand.objects.create(name='HP')

        # Assets
        self.asset_available = Asset.objects.create(
            item_name='HP LaserJet Pro 4103',
            category=self.cat_it,
            brand=self.brand_hp,
            department=self.dept_ba,
            current_location=self.loc_storage,
            condition=Asset.Condition.GOOD,
            status=Asset.Status.AVAILABLE,
            property_number='PN-TEST-001',
            acquisition_cost=Decimal('25000.00'),
            acquisition_date=timezone.now().date() - timedelta(days=100),
            created_by=self.admin_user
        )

        self.asset_assigned = Asset.objects.create(
            item_name='HP EliteBook 840',
            category=self.cat_it,
            brand=self.brand_hp,
            department=self.dept_ba,
            current_location=self.loc_fac_ba,
            condition=Asset.Condition.GOOD,
            status=Asset.Status.ASSIGNED,
            property_number='PN-TEST-002',
            acquisition_cost=Decimal('65000.00'),
            acquisition_date=timezone.now().date() - timedelta(days=150),
            created_by=self.admin_user
        )
        self.assignment = AssetAssignment.objects.create(
            asset=self.asset_assigned,
            employee=self.emp_faculty1,
            assigned_by=self.admin_user,
            assigned_date=timezone.now().date() - timedelta(days=40),
            condition_at_assignment=Asset.Condition.GOOD,
            status=AssetAssignment.Status.ACTIVE
        )

        self.asset_acct = Asset.objects.create(
            item_name='Accounting Desktop Workstation',
            category=self.cat_it,
            brand=self.brand_hp,
            department=self.dept_acct,
            current_location=self.loc_fac_acct,
            condition=Asset.Condition.GOOD,
            status=Asset.Status.AVAILABLE,
            property_number='PN-TEST-003',
            acquisition_cost=Decimal('45000.00'),
            acquisition_date=timezone.now().date() - timedelta(days=50),
            created_by=self.admin_user
        )


class MaintenanceModelTestCase(MaintenanceBaseTestCase):
    """Tests for AssetMaintenance model integrity, case numbering, constraints, and protection."""

    def test_case_number_auto_generation(self):
        """Case numbers follow MNT-YYYY-SEQ format sequentially without collision."""
        current_year = timezone.now().year
        m1 = services.report_issue(
            asset=self.asset_available,
            reported_by=self.admin_user,
            issue_title='Toner Smear',
            issue_description='Printouts exhibit black horizontal lines across the page.'
        )
        self.assertTrue(m1.case_number.startswith(f"MNT-{current_year}-"))
        self.assertEqual(len(m1.case_number), 14)

        m2 = services.report_issue(
            asset=self.asset_acct,
            reported_by=self.admin_user,
            issue_title='Power Fault',
            issue_description='System fails to power on.'
        )
        self.assertTrue(m2.case_number.startswith(f"MNT-{current_year}-"))
        # Verify sequence increments
        seq1 = int(m1.case_number.split('-')[-1])
        seq2 = int(m2.case_number.split('-')[-1])
        self.assertEqual(seq2, seq1 + 1)

    def test_condition_before_snapshot(self):
        """The asset's condition at the time of report is accurately snapshotted."""
        self.asset_available.condition = Asset.Condition.POOR
        self.asset_available.save(update_fields=['condition'])

        m = services.report_issue(
            asset=self.asset_available,
            reported_by=self.admin_user,
            issue_title='Fuser Unit Breakdown',
            issue_description='Smells of burnt plastic.'
        )
        self.assertEqual(m.condition_before, Asset.Condition.POOR)

    def test_deletion_protection_on_asset(self):
        """Assets with maintenance records cannot be deleted due to PROTECT foreign key."""
        m = services.report_issue(
            asset=self.asset_available,
            reported_by=self.admin_user,
            issue_title='Defective Tray',
            issue_description='Tray 2 spring is snapped.'
        )
        with self.assertRaises(ProtectedError):
            self.asset_available.delete()

    def test_negative_repair_cost_validation(self):
        """Model clean() rejects negative repair costs."""
        m = AssetMaintenance(
            asset=self.asset_available,
            reported_by=self.admin_user,
            issue_title='Test',
            issue_description='Test',
            repair_cost=Decimal('-50.00')
        )
        with self.assertRaises(ValidationError):
            m.clean()


class MaintenanceServicesTestCase(MaintenanceBaseTestCase):
    """Tests for the atomic services layer covering the complete lifecycle."""

    def test_report_issue_leaves_asset_operational_status_unchanged(self):
        """Invariant: reporting a defect does NOT prematurely transition asset to MAINTENANCE."""
        self.assertEqual(self.asset_available.status, Asset.Status.AVAILABLE)
        m = services.report_issue(
            asset=self.asset_available,
            reported_by=self.admin_user,
            issue_title='Paper Jam',
            issue_description='Paper jams frequently.'
        )
        self.asset_available.refresh_from_db()
        self.assertEqual(m.status, AssetMaintenance.Status.REPORTED)
        self.assertEqual(self.asset_available.status, Asset.Status.AVAILABLE)

        # Assigned asset retains ASSIGNED status upon reporting
        self.assertEqual(self.asset_assigned.status, Asset.Status.ASSIGNED)
        m_assigned = services.report_issue(
            asset=self.asset_assigned,
            reported_by=self.faculty_user1,
            issue_title='Trackpad Glitch',
            issue_description='Cursor jumps erratically.'
        )
        self.asset_assigned.refresh_from_db()
        self.assertEqual(self.asset_assigned.status, Asset.Status.ASSIGNED)

    def test_report_issue_audit_logging(self):
        """Submitting a maintenance report creates an immutable audit log entry."""
        initial_count = AuditLog.objects.count()
        m = services.report_issue(
            asset=self.asset_available,
            reported_by=self.admin_user,
            issue_title='Network Card Malfunction',
            issue_description='Ethernet port link LED does not light up.'
        )
        self.assertGreater(AuditLog.objects.count(), initial_count)
        log = AuditLog.objects.filter(action='MAINTENANCE_REPORTED').latest('timestamp')
        self.assertEqual(log.user, self.admin_user)
        self.assertIn(m.case_number, log.changes.get('case_number', ''))

    def test_duplicate_open_report_prevention(self):
        """Attempting to open duplicate active reports with same title raises ValidationError."""
        services.report_issue(
            asset=self.asset_available,
            reported_by=self.admin_user,
            issue_title='Paper Feed Roller Defect',
            issue_description='First report.'
        )
        with self.assertRaises(ValidationError) as ctx:
            services.report_issue(
                asset=self.asset_available,
                reported_by=self.admin_user,
                issue_title='Paper Feed Roller Defect',
                issue_description='Second identical report.'
            )
        self.assertIn('already open', str(ctx.exception))

    def test_validate_can_report_permissions(self):
        """Enforces conservative reporting authorization by role."""
        # 1. Admin can report any asset
        services.validate_can_report(self.admin_user, self.asset_available)
        services.validate_can_report(self.admin_user, self.asset_acct)

        # 2. Dean can report any asset
        services.validate_can_report(self.dean_user, self.asset_available)
        services.validate_can_report(self.dean_user, self.asset_acct)

        # 3. Chair BA can report BA asset, but not ACCT asset
        services.validate_can_report(self.chair_ba_user, self.asset_available)
        with self.assertRaises(PermissionDenied):
            services.validate_can_report(self.chair_ba_user, self.asset_acct)

        # 4. Faculty 1 can report actively assigned asset
        services.validate_can_report(self.faculty_user1, self.asset_assigned)

        # 5. Faculty 1 CANNOT report unassigned asset or asset assigned to someone else
        with self.assertRaises(PermissionDenied):
            services.validate_can_report(self.faculty_user1, self.asset_available)
        with self.assertRaises(PermissionDenied):
            services.validate_can_report(self.faculty_user2, self.asset_assigned)

    def test_technical_assessment_workflow(self):
        """Assessing an issue records technical diagnosis and transitions to ASSESSED."""
        m = services.report_issue(
            asset=self.asset_available,
            reported_by=self.admin_user,
            issue_title='Scanner Glass Cracked',
            issue_description='Cracked upper left glass.'
        )
        assessed_case = services.assess_issue(
            maintenance=m,
            assessed_by=self.admin_user,
            severity=AssetMaintenance.Severity.MEDIUM,
            diagnosis='Scanner flatbed glass has a 4-inch diagonal fracture. CCD optical sensor intact.',
            recommended_action='Replace flatbed glass assembly.',
            remarks='Ordered replacement part.'
        )
        self.assertEqual(assessed_case.status, AssetMaintenance.Status.ASSESSED)
        self.assertEqual(assessed_case.severity, AssetMaintenance.Severity.MEDIUM)
        self.assertEqual(assessed_case.assessed_by, self.admin_user)
        self.assertIsNotNone(assessed_case.assessed_at)

    def test_start_repair_transitions_asset_to_maintenance(self):
        """Starting repair sets the asset's operational status to UNDER MAINTENANCE."""
        m = services.report_issue(
            asset=self.asset_available,
            reported_by=self.admin_user,
            issue_title='Main Logic Board Failure',
            issue_description='No boot LED.'
        )
        services.assess_issue(
            maintenance=m,
            assessed_by=self.admin_user,
            severity=AssetMaintenance.Severity.HIGH,
            diagnosis='Blown SMD capacitor on 12V rail.',
            recommended_action='Component level repair.'
        )

        repair_case = services.start_repair(
            maintenance=m,
            user=self.admin_user,
            service_provider='CBA IT Workshop',
            technician='Technician Noel',
            remarks='Work order #WO-101'
        )
        self.assertEqual(repair_case.status, AssetMaintenance.Status.IN_REPAIR)
        self.asset_available.refresh_from_db()
        self.assertEqual(self.asset_available.status, Asset.Status.MAINTENANCE)

    def test_cannot_start_repair_on_actively_borrowed_equipment(self):
        """Assets out on temporary loan (BORROWED) cannot begin repair until formally returned."""
        borrowed_asset = Asset.objects.create(
            item_name='Projector For Loan',
            category=self.cat_it,
            brand=self.brand_hp,
            department=self.dept_ba,
            current_location=self.loc_storage,
            condition=Asset.Condition.GOOD,
            status=Asset.Status.BORROWED,
            property_number='PN-TEST-BORROWED',
            created_by=self.admin_user
        )
        loan = AssetBorrowing.objects.create(
            asset=borrowed_asset,
            borrower=self.emp_faculty1,
            borrower_department=self.dept_ba,
            purpose='Lecture presentation',
            requested_start=timezone.now(),
            requested_return=timezone.now() + timedelta(days=2),
            status=AssetBorrowing.Status.RELEASED,
            released_by=self.admin_user,
            released_at=timezone.now()
        )

        m = services.report_issue(
            asset=borrowed_asset,
            reported_by=self.faculty_user1,
            issue_title='Flickering Lamp',
            issue_description='Lamp flickers on and off.'
        )
        services.assess_issue(
            maintenance=m,
            assessed_by=self.admin_user,
            severity=AssetMaintenance.Severity.HIGH,
            diagnosis='Lamp reaching end of life.'
        )

        with self.assertRaises(ValidationError) as ctx:
            services.start_repair(
                maintenance=m,
                user=self.admin_user,
                service_provider='Vendor'
            )
        self.assertIn('borrowed on loan', str(ctx.exception))

    def test_complete_repair_unassigned_asset_restores_available_status(self):
        """Repairing an unassigned asset with serviceable condition restores status to AVAILABLE."""
        m = services.report_issue(
            asset=self.asset_available,
            reported_by=self.admin_user,
            issue_title='Pickup Roller Jam',
            issue_description='Roller slipping.'
        )
        services.assess_issue(
            maintenance=m,
            assessed_by=self.admin_user,
            severity=AssetMaintenance.Severity.MEDIUM,
            diagnosis='Worn rubber.'
        )
        services.start_repair(
            maintenance=m,
            user=self.admin_user,
            service_provider='In-House Repair'
        )

        completed_case = services.complete_repair(
            maintenance=m,
            user=self.admin_user,
            final_condition=Asset.Condition.GOOD,
            action_taken='Replaced pickup and separation rollers.',
            parts_replaced='HP Pickup Roller Assembly (RM2-5399)',
            repair_cost=Decimal('850.00'),
            remarks='Tested 50-page print job without jams.'
        )

        self.assertEqual(completed_case.status, AssetMaintenance.Status.COMPLETED)
        self.assertEqual(completed_case.final_condition, Asset.Condition.GOOD)
        self.assertEqual(completed_case.repair_cost, Decimal('850.00'))
        self.asset_available.refresh_from_db()
        self.assertEqual(self.asset_available.status, Asset.Status.AVAILABLE)
        self.assertEqual(self.asset_available.condition, Asset.Condition.GOOD)

    def test_complete_repair_assigned_asset_preserves_accountability(self):
        """When an actively assigned laptop is repaired, status restores to ASSIGNED, preserving accountability."""
        m = services.report_issue(
            asset=self.asset_assigned,
            reported_by=self.faculty_user1,
            issue_title='Dead Battery',
            issue_description='Battery does not hold charge.'
        )
        services.assess_issue(
            maintenance=m,
            assessed_by=self.admin_user,
            severity=AssetMaintenance.Severity.MEDIUM,
            diagnosis='Battery internal resistance high.'
        )
        services.start_repair(
            maintenance=m,
            user=self.admin_user,
            service_provider='HP Official Service'
        )

        self.asset_assigned.refresh_from_db()
        self.assertEqual(self.asset_assigned.status, Asset.Status.MAINTENANCE)

        # Complete repair
        services.complete_repair(
            maintenance=m,
            user=self.admin_user,
            final_condition=Asset.Condition.GOOD,
            action_taken='Installed OEM battery pack.',
            parts_replaced='HP 3-cell 53Wh Battery',
            repair_cost=Decimal('3200.00')
        )

        self.asset_assigned.refresh_from_db()
        # Status MUST be ASSIGNED, not AVAILABLE, because Maria Clara's assignment remains ACTIVE
        self.assertEqual(self.asset_assigned.status, Asset.Status.ASSIGNED)
        self.assertEqual(self.assignment.status, AssetAssignment.Status.ACTIVE)

    def test_complete_repair_unserviceable_condition_sets_damaged_status(self):
        """Completing a repair with final_condition=UNSERVICEABLE forces status to DAMAGED."""
        m = services.report_issue(
            asset=self.asset_available,
            reported_by=self.admin_user,
            issue_title='Severe Overheating',
            issue_description='Smoke observed.'
        )
        services.assess_issue(
            maintenance=m,
            assessed_by=self.admin_user,
            severity=AssetMaintenance.Severity.CRITICAL,
            diagnosis='Burned multilayer board.'
        )
        services.start_repair(
            maintenance=m,
            user=self.admin_user,
            service_provider='Electronics Lab'
        )
        services.complete_repair(
            maintenance=m,
            user=self.admin_user,
            final_condition=Asset.Condition.UNSERVICEABLE,
            action_taken='Board traces destroyed; unable to repair.',
            repair_cost=Decimal('0.00')
        )
        self.asset_available.refresh_from_db()
        self.assertEqual(self.asset_available.status, Asset.Status.DAMAGED)
        self.assertEqual(self.asset_available.condition, Asset.Condition.UNSERVICEABLE)

    def test_mark_for_replacement_workflow(self):
        """Marking for replacement sets status to FOR_REPLACEMENT and asset to DAMAGED / UNSERVICEABLE."""
        m = services.report_issue(
            asset=self.asset_available,
            reported_by=self.admin_user,
            issue_title='Bent Chassis & Motor Seizure',
            issue_description='Dropped during move.'
        )
        services.assess_issue(
            maintenance=m,
            assessed_by=self.admin_user,
            severity=AssetMaintenance.Severity.HIGH,
            diagnosis='Chassis deformed beyond tolerance.'
        )
        replaced_case = services.mark_for_replacement(
            maintenance=m,
            user=self.admin_user,
            remarks='Estimated repair cost 150% of new unit. Recommended for phase 9 condemnation.'
        )
        self.assertEqual(replaced_case.status, AssetMaintenance.Status.FOR_REPLACEMENT)
        self.asset_available.refresh_from_db()
        self.assertEqual(self.asset_available.status, Asset.Status.DAMAGED)
        self.assertEqual(self.asset_available.condition, Asset.Condition.UNSERVICEABLE)

    def test_cancel_maintenance_workflow(self):
        """Cancelling restores asset status and records cancellation reason."""
        m = services.report_issue(
            asset=self.asset_available,
            reported_by=self.admin_user,
            issue_title='False Alarm Jam',
            issue_description='User thought paper was jammed.'
        )
        cancelled = services.cancel_maintenance(
            maintenance=m,
            user=self.admin_user,
            cancellation_reason='Operator error; paper tray was merely empty.'
        )
        self.assertEqual(cancelled.status, AssetMaintenance.Status.CANCELLED)
        self.assertEqual(cancelled.cancelled_by, self.admin_user)
        self.assertIsNotNone(cancelled.cancelled_at)


class MaintenanceViewsTestCase(MaintenanceBaseTestCase):
    """Tests for UI views, forms, permissions, and role-based access control."""

    def setUp(self):
        super().setUp()
        self.client = Client()

    def test_queue_access_non_faculty_only(self):
        """Admin, Dean, and Chair can view queue; Faculty is redirected to My Reports."""
        # Anonymous -> redirected to login
        response = self.client.get(reverse('maintenance:case_list'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/', response.url)

        # Faculty -> redirected to my_reports
        self.client.force_login(self.faculty_user1)
        response = self.client.get(reverse('maintenance:case_list'))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('maintenance:my_reports'), response.url)

        # Admin -> 200 OK
        self.client.force_login(self.admin_user)
        response = self.client.get(reverse('maintenance:case_list'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'maintenance/maintenance_list.html')

        # Dean -> 200 OK
        self.client.force_login(self.dean_user)
        response = self.client.get(reverse('maintenance:case_list'))
        self.assertEqual(response.status_code, 200)

        # Chair -> 200 OK
        self.client.force_login(self.chair_ba_user)
        response = self.client.get(reverse('maintenance:case_list'))
        self.assertEqual(response.status_code, 200)

    def test_chair_department_scoping_in_queue(self):
        """Department Chair only sees maintenance cases for assets belonging to their department."""
        m_ba = services.report_issue(
            asset=self.asset_available,
            reported_by=self.admin_user,
            issue_title='BA Printer Issue',
            issue_description='Tray issue.'
        )
        m_acct = services.report_issue(
            asset=self.asset_acct,
            reported_by=self.admin_user,
            issue_title='ACCT PC Issue',
            issue_description='PSU issue.'
        )

        # Chair BA sees BA case, not ACCT case
        self.client.force_login(self.chair_ba_user)
        response = self.client.get(reverse('maintenance:case_list'))
        self.assertContains(response, m_ba.case_number)
        self.assertNotContains(response, m_acct.case_number)

    def test_my_maintenance_view_faculty(self):
        """Faculty sees cases filed by them or for equipment assigned to them."""
        m_assigned = services.report_issue(
            asset=self.asset_assigned,
            reported_by=self.faculty_user1,
            issue_title='Keyboard Sticky',
            issue_description='Keys sticking.'
        )
        m_other = services.report_issue(
            asset=self.asset_acct,
            reported_by=self.admin_user,
            issue_title='Accounting Server',
            issue_description='Disk fail.'
        )

        self.client.force_login(self.faculty_user1)
        response = self.client.get(reverse('maintenance:my_reports'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, m_assigned.case_number)
        self.assertNotContains(response, m_other.case_number)

    def test_detail_view_permissions(self):
        """Enforces view permissions on case detail page."""
        m_assigned = services.report_issue(
            asset=self.asset_assigned,
            reported_by=self.faculty_user1,
            issue_title='Keyboard Sticky',
            issue_description='Keys sticking.'
        )

        # Admin and Dean can view
        self.client.force_login(self.admin_user)
        res = self.client.get(reverse('maintenance:maintenance_detail', args=[m_assigned.pk]))
        self.assertEqual(res.status_code, 200)

        self.client.force_login(self.dean_user)
        res = self.client.get(reverse('maintenance:maintenance_detail', args=[m_assigned.pk]))
        self.assertEqual(res.status_code, 200)

        # Maria (assignee/reporter) can view
        self.client.force_login(self.faculty_user1)
        res = self.client.get(reverse('maintenance:maintenance_detail', args=[m_assigned.pk]))
        self.assertEqual(res.status_code, 200)

        # Jose (unrelated faculty) gets 403 Forbidden
        self.client.force_login(self.faculty_user2)
        res = self.client.get(reverse('maintenance:maintenance_detail', args=[m_assigned.pk]))
        self.assertEqual(res.status_code, 403)

    def test_action_views_restricted_to_admin(self):
        """Mutating actions (Assess, Start Repair, Complete, For Replacement) reject non-admins with 403."""
        m = services.report_issue(
            asset=self.asset_available,
            reported_by=self.admin_user,
            issue_title='Test Defect',
            issue_description='Details.'
        )

        for user in [self.dean_user, self.chair_ba_user, self.faculty_user1]:
            self.client.force_login(user)

            # Assess
            res = self.client.get(reverse('maintenance:maintenance_assess', args=[m.pk]))
            self.assertEqual(res.status_code, 403)

            # Start Repair
            res = self.client.get(reverse('maintenance:maintenance_start_repair', args=[m.pk]))
            self.assertEqual(res.status_code, 403)

            # Complete
            res = self.client.get(reverse('maintenance:maintenance_complete', args=[m.pk]))
            self.assertEqual(res.status_code, 403)

            # For Replacement
            res = self.client.get(reverse('maintenance:maintenance_for_replacement', args=[m.pk]))
            self.assertEqual(res.status_code, 403)

    def test_faculty_can_cancel_own_reported_case(self):
        """Faculty can cancel their own REPORTED case, but cannot cancel an ASSESSED case or others' cases."""
        m = services.report_issue(
            asset=self.asset_assigned,
            reported_by=self.faculty_user1,
            issue_title='False Alarm Issue',
            issue_description='Glitch resolved after reboot.'
        )
        self.client.force_login(self.faculty_user1)

        # Can access cancel form
        res = self.client.get(reverse('maintenance:maintenance_cancel', args=[m.pk]))
        self.assertEqual(res.status_code, 200)

        # Post cancellation
        res = self.client.post(reverse('maintenance:maintenance_cancel', args=[m.pk]), {
            'cancellation_reason': 'System reboot fixed the issue.'
        })
        self.assertEqual(res.status_code, 302)
        m.refresh_from_db()
        self.assertEqual(m.status, AssetMaintenance.Status.CANCELLED)

        # Now test that faculty cannot cancel an ASSESSED case
        m2 = services.report_issue(
            asset=self.asset_assigned,
            reported_by=self.faculty_user1,
            issue_title='Real Hardware Issue',
            issue_description='Keys dead.'
        )
        services.assess_issue(
            maintenance=m2,
            assessed_by=self.admin_user,
            severity=AssetMaintenance.Severity.HIGH,
            diagnosis='Hardware fault.'
        )

        res = self.client.get(reverse('maintenance:maintenance_cancel', args=[m2.pk]))
        self.assertEqual(res.status_code, 403)

    def test_asset_delete_blocked_by_maintenance_history(self):
        """AssetDeleteView prevents permanent deletion when an asset has maintenance history."""
        m = services.report_issue(
            asset=self.asset_available,
            reported_by=self.admin_user,
            issue_title='Broken Hinge',
            issue_description='Left hinge cracked.'
        )
        self.client.force_login(self.admin_user)

        # GET request redirects to detail with error message
        res = self.client.get(reverse('inventory:asset_delete', args=[self.asset_available.asset_code]))
        self.assertEqual(res.status_code, 302)
        self.assertIn(reverse('inventory:asset_detail', args=[self.asset_available.asset_code]), res.url)

        # POST request also redirects and asset remains intact
        res = self.client.post(reverse('inventory:asset_delete', args=[self.asset_available.asset_code]))
        self.assertEqual(res.status_code, 302)
        self.assertTrue(Asset.objects.filter(pk=self.asset_available.pk).exists())
