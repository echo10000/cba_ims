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
from apps.assignments import services
from apps.assignments.forms import AssetAssignmentForm, AssetReturnForm
from apps.audit.models import AuditLog


class AssignmentBaseTestCase(TestCase):
    """Sets up realistic organizational structure, users with roles, and assets."""

    def setUp(self):
        # Departments
        self.dept_ba = Department.objects.create(code='BA', name='Department of Business Administration')
        self.dept_acct = Department.objects.create(code='ACCT', name='Department of Accountancy')

        # Locations with distinct building and room numbers
        self.loc_ba = Location.objects.create(
            name='BA Faculty Room', building='CBA Main', room_number='205', department=self.dept_ba
        )
        self.loc_acct = Location.objects.create(
            name='Accountancy Dept Office', building='CBA Annex', room_number='302', department=self.dept_acct
        )

        # Users
        self.admin_user = User.objects.create_superuser('admin_user', 'admin@cba.edu', 'Pass1234!')
        self.admin_user.role = User.Role.ADMIN
        self.admin_user.save()

        self.dean_user = User.objects.create_user('dean_user', 'dean@cba.edu', 'Pass1234!', role=User.Role.DEAN)
        self.chair_ba_user = User.objects.create_user('chair_ba', 'chair.ba@cba.edu', 'Pass1234!', role=User.Role.DEPT_CHAIR)
        self.chair_acct_user = User.objects.create_user('chair_acct', 'chair.acct@cba.edu', 'Pass1234!', role=User.Role.DEPT_CHAIR)
        self.faculty_ba_user = User.objects.create_user('fac_ba', 'fac.ba@cba.edu', 'Pass1234!', role=User.Role.FACULTY)
        self.faculty_acct_user = User.objects.create_user('fac_acct', 'fac.acct@cba.edu', 'Pass1234!', role=User.Role.FACULTY)

        # Employee Profiles
        self.emp_chair_ba = Employee.objects.create(
            user=self.chair_ba_user,
            employee_id='EMP-CBA-001',
            first_name='Carlos',
            last_name='Mendoza',
            department=self.dept_ba,
            location=self.loc_ba,
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
            location=self.loc_acct,
            position='Chairperson, Accountancy',
            is_active=True
        )
        self.dept_acct.head = self.emp_chair_acct
        self.dept_acct.save()

        self.emp_fac_ba = Employee.objects.create(
            user=self.faculty_ba_user,
            employee_id='EMP-FAC-001',
            first_name='Maria',
            last_name='Cruz',
            department=self.dept_ba,
            location=self.loc_ba,
            position='Assistant Professor',
            is_active=True
        )

        self.emp_fac_acct = Employee.objects.create(
            user=self.faculty_acct_user,
            employee_id='EMP-FAC-002',
            first_name='Juan',
            last_name='Dela Cruz',
            department=self.dept_acct,
            location=self.loc_acct,
            position='Instructor I',
            is_active=True
        )

        self.inactive_emp = Employee.objects.create(
            employee_id='EMP-INACT-001',
            first_name='Inactive',
            last_name='Staff',
            department=self.dept_ba,
            is_active=False
        )

        # Asset Categories & Brand
        self.cat_it = AssetCategory.objects.create(name='Information Technology', code='IT')
        self.cat_oe = AssetCategory.objects.create(name='Office Equipment', code='OE')
        self.brand_dell = Brand.objects.create(name='Dell')

        # Assets
        self.asset_laptop = Asset.objects.create(
            asset_code='CBA-IT-00010',
            item_name='Dell Latitude 5430 Laptop',
            category=self.cat_it,
            brand=self.brand_dell,
            department=self.dept_ba,
            current_location=self.loc_ba,
            condition=Asset.Condition.GOOD,
            status=Asset.Status.AVAILABLE,
            acquisition_cost=Decimal('48000.00'),
            created_by=self.admin_user
        )

        self.asset_printer = Asset.objects.create(
            asset_code='CBA-OE-00010',
            item_name='HP LaserJet Enterprise Printer',
            category=self.cat_oe,
            department=self.dept_acct,
            current_location=self.loc_acct,
            condition=Asset.Condition.GOOD,
            status=Asset.Status.AVAILABLE,
            created_by=self.admin_user
        )


class AssetAssignmentModelTests(AssignmentBaseTestCase):
    """Tests model validation, single active assignment constraint, and protect cascades."""

    def test_single_active_assignment_constraint(self):
        """Ensures an asset cannot have two ACTIVE assignments simultaneously."""
        # Create first active assignment
        AssetAssignment.objects.create(
            asset=self.asset_laptop,
            employee=self.emp_fac_ba,
            assigned_date=date.today(),
            condition_at_assignment=Asset.Condition.GOOD,
            assigned_by=self.admin_user,
            status=AssetAssignment.Status.ACTIVE
        )

        # Attempting second active assignment on the same asset must fail constraint
        with self.assertRaises(Exception):
            AssetAssignment.objects.create(
                asset=self.asset_laptop,
                employee=self.emp_fac_acct,
                assigned_date=date.today(),
                condition_at_assignment=Asset.Condition.GOOD,
                assigned_by=self.admin_user,
                status=AssetAssignment.Status.ACTIVE
            )

    def test_reassignment_after_return_allowed(self):
        """Once returned, the same asset can have a new active assignment."""
        assign1 = AssetAssignment.objects.create(
            asset=self.asset_laptop,
            employee=self.emp_fac_ba,
            assigned_date=date.today() - timedelta(days=60),
            returned_date=date.today() - timedelta(days=10),
            condition_at_assignment=Asset.Condition.GOOD,
            condition_at_return=Asset.Condition.GOOD,
            assigned_by=self.admin_user,
            status=AssetAssignment.Status.RETURNED
        )
        self.assertEqual(assign1.status, AssetAssignment.Status.RETURNED)

        # Now creating new active assignment must succeed
        assign2 = AssetAssignment.objects.create(
            asset=self.asset_laptop,
            employee=self.emp_fac_acct,
            assigned_date=date.today(),
            condition_at_assignment=Asset.Condition.GOOD,
            assigned_by=self.admin_user,
            status=AssetAssignment.Status.ACTIVE
        )
        self.assertEqual(assign2.status, AssetAssignment.Status.ACTIVE)
        self.assertEqual(self.asset_laptop.assignments.count(), 2)

    def test_deletion_protection(self):
        """Asset and Employee cannot be deleted if assignment records exist (models.PROTECT)."""
        AssetAssignment.objects.create(
            asset=self.asset_laptop,
            employee=self.emp_fac_ba,
            assigned_date=date.today(),
            condition_at_assignment=Asset.Condition.GOOD,
            assigned_by=self.admin_user,
            status=AssetAssignment.Status.ACTIVE
        )

        with self.assertRaises(ProtectedError):
            self.asset_laptop.delete()

        with self.assertRaises(ProtectedError):
            self.emp_fac_ba.delete()


class AssetAssignmentServiceTests(AssignmentBaseTestCase):
    """Tests atomic assignment and return service functions with state transitions and auditing."""

    def test_assign_asset_success(self):
        """assign_asset successfully transitions asset status to ASSIGNED and logs audit entry."""
        assignment = services.assign_asset(
            asset=self.asset_laptop,
            employee=self.emp_fac_ba,
            assigned_by=self.admin_user,
            assigned_date=date.today(),
            expected_return_date=date.today() + timedelta(days=90),
            purpose='Classroom Instruction',
            remarks='Complete with power brick and carrying case.'
        )

        self.asset_laptop.refresh_from_db()
        self.assertEqual(self.asset_laptop.status, Asset.Status.ASSIGNED)
        self.assertEqual(assignment.status, AssetAssignment.Status.ACTIVE)
        self.assertEqual(assignment.condition_at_assignment, Asset.Condition.GOOD)

        # Check audit log
        log = AuditLog.objects.filter(action='ASSET_ASSIGNED').first()
        self.assertIsNotNone(log)
        self.assertEqual(log.user, self.admin_user)
        self.assertIn('CBA-IT-00010', str(log.changes))

    def test_assign_asset_non_available_fails(self):
        """Attempting to assign an asset that is not AVAILABLE raises ValidationError."""
        self.asset_laptop.status = Asset.Status.MAINTENANCE
        self.asset_laptop.save()

        with self.assertRaises(ValidationError) as cm:
            services.assign_asset(
                asset=self.asset_laptop,
                employee=self.emp_fac_ba,
                assigned_by=self.admin_user
            )
        self.assertIn('cannot be assigned', str(cm.exception))

    def test_assign_to_inactive_employee_fails(self):
        """Attempting to assign to an inactive employee raises ValidationError."""
        with self.assertRaises(ValidationError) as cm:
            services.assign_asset(
                asset=self.asset_laptop,
                employee=self.inactive_emp,
                assigned_by=self.admin_user
            )
        self.assertIn('inactive employee', str(cm.exception))

    def test_return_asset_success_available(self):
        """return_asset marks assignment RETURNED and reverts asset status to AVAILABLE."""
        assignment = services.assign_asset(
            asset=self.asset_laptop,
            employee=self.emp_fac_ba,
            assigned_by=self.admin_user,
            assigned_date=date.today() - timedelta(days=30)
        )

        returned = services.return_asset(
            assignment=assignment,
            returned_by=self.admin_user,
            returned_date=date.today(),
            condition_at_return=Asset.Condition.GOOD,
            remarks='Returned on schedule with all items intact.'
        )

        self.assertEqual(returned.status, AssetAssignment.Status.RETURNED)
        self.assertEqual(returned.returned_date, date.today())
        self.asset_laptop.refresh_from_db()
        self.assertEqual(self.asset_laptop.status, Asset.Status.AVAILABLE)
        self.assertEqual(self.asset_laptop.condition, Asset.Condition.GOOD)

        # Check audit log
        log = AuditLog.objects.filter(action='ASSET_RETURNED').first()
        self.assertIsNotNone(log)
        self.assertEqual(log.user, self.admin_user)

    def test_return_asset_unserviceable_transitions_to_damaged(self):
        """If returned as UNSERVICEABLE, asset transitions to DAMAGED (not AVAILABLE)."""
        assignment = services.assign_asset(
            asset=self.asset_laptop,
            employee=self.emp_fac_ba,
            assigned_by=self.admin_user,
            assigned_date=date.today() - timedelta(days=30)
        )

        services.return_asset(
            assignment=assignment,
            returned_by=self.admin_user,
            returned_date=date.today(),
            condition_at_return=Asset.Condition.UNSERVICEABLE,
            remarks='Screen broken due to accidental drop.'
        )

        self.asset_laptop.refresh_from_db()
        self.assertEqual(self.asset_laptop.status, Asset.Status.DAMAGED)
        self.assertEqual(self.asset_laptop.condition, Asset.Condition.UNSERVICEABLE)


class AssignmentFormTests(AssignmentBaseTestCase):
    """Tests form filtering and validation."""

    def test_asset_assignment_form_filters_available_assets(self):
        """Form only displays AVAILABLE assets and active employees."""
        self.asset_printer.status = Asset.Status.ASSIGNED
        self.asset_printer.save()

        form = AssetAssignmentForm()
        asset_queryset = form.fields['asset'].queryset
        self.assertIn(self.asset_laptop, asset_queryset)
        self.assertNotIn(self.asset_printer, asset_queryset)

        emp_queryset = form.fields['employee'].queryset
        self.assertIn(self.emp_fac_ba, emp_queryset)
        self.assertNotIn(self.inactive_emp, emp_queryset)

    def test_asset_return_form_validation(self):
        """Return form validates date and condition."""
        form = AssetReturnForm(data={
            'returned_date': date.today(),
            'condition_at_return': Asset.Condition.GOOD,
            'remarks': 'Normal inspection.'
        })
        self.assertTrue(form.is_valid())


class AssignmentViewsAndRBACTests(AssignmentBaseTestCase):
    """Tests role-based access control and scoping across all assignment views."""

    def setUp(self):
        super().setUp()
        self.client = Client()

        # Create active assignments in both departments
        self.assign_ba = services.assign_asset(
            asset=self.asset_laptop,
            employee=self.emp_fac_ba,
            assigned_by=self.admin_user,
            purpose='BA Instruction'
        )
        self.assign_acct = services.assign_asset(
            asset=self.asset_printer,
            employee=self.emp_fac_acct,
            assigned_by=self.admin_user,
            purpose='Accountancy Lab'
        )

    def test_admin_full_access(self):
        """Admin can view current list, history, and access assign/return forms."""
        self.client.force_login(self.admin_user)

        # Current list
        res = self.client.get(reverse('assignments:current_list'))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'CBA-IT-00010')
        self.assertContains(res, 'CBA-OE-00010')

        # Assign view
        res = self.client.get(reverse('assignments:assign_create'))
        self.assertEqual(res.status_code, 200)

        # Return view
        res = self.client.get(reverse('assignments:asset_return', kwargs={'pk': self.assign_ba.pk}))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'Process Asset Return')

    def test_dean_read_all_no_write(self):
        """Dean can view all assignments across departments, but cannot assign or return."""
        self.client.force_login(self.dean_user)

        # Read current list (all depts)
        res = self.client.get(reverse('assignments:current_list'))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'CBA-IT-00010')
        self.assertContains(res, 'CBA-OE-00010')

        # Cannot assign
        res = self.client.get(reverse('assignments:assign_create'))
        self.assertEqual(res.status_code, 403)

        # Cannot return
        res = self.client.get(reverse('assignments:asset_return', kwargs={'pk': self.assign_ba.pk}))
        self.assertEqual(res.status_code, 403)

    def test_dept_chair_scoped_to_department(self):
        """BA Dept Chair sees only BA assignments; Accountancy assignments are hidden."""
        self.client.force_login(self.chair_ba_user)

        res = self.client.get(reverse('assignments:current_list'))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'CBA-IT-00010')   # BA laptop
        self.assertNotContains(res, 'CBA-OE-00010') # ACCT printer

        # Chair cannot assign or return
        res = self.client.get(reverse('assignments:assign_create'))
        self.assertEqual(res.status_code, 403)

        res = self.client.get(reverse('assignments:asset_return', kwargs={'pk': self.assign_ba.pk}))
        self.assertEqual(res.status_code, 403)

    def test_faculty_redirected_to_my_accountability(self):
        """Faculty accessing general current list is redirected to My Accountability."""
        self.client.force_login(self.faculty_ba_user)

        res = self.client.get(reverse('assignments:current_list'))
        self.assertRedirects(res, reverse('assignments:my_accountability'))

    def test_my_accountability_view(self):
        """Faculty can view equipment assigned to them on My Accountability."""
        self.client.force_login(self.faculty_ba_user)

        res = self.client.get(reverse('assignments:my_accountability'))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'CBA-IT-00010')
        self.assertNotContains(res, 'CBA-OE-00010')

    def test_faculty_asset_detail_access_scoped_to_assigned(self):
        """Faculty can view detail page of equipment assigned to them, but forbidden for others."""
        self.client.force_login(self.faculty_ba_user)

        # Assigned to self -> 200
        res = self.client.get(reverse('inventory:asset_detail', kwargs={'asset_code': self.asset_laptop.asset_code}))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'Dell Latitude 5430 Laptop')

        # Assigned to another faculty -> 403
        res = self.client.get(reverse('inventory:asset_detail', kwargs={'asset_code': self.asset_printer.asset_code}))
        self.assertEqual(res.status_code, 403)

    def test_printable_accountability_permissions(self):
        """Print certificate allows Admin, Dean, Chair (own dept), and the Employee themselves."""
        # 1. Admin can view for BA faculty
        self.client.force_login(self.admin_user)
        res = self.client.get(reverse('assignments:print_accountability', kwargs={'employee_id': self.emp_fac_ba.pk}))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'Property Acknowledgement Receipt')

        # 2. Dean can view for ACCT faculty
        self.client.force_login(self.dean_user)
        res = self.client.get(reverse('assignments:print_accountability', kwargs={'employee_id': self.emp_fac_acct.pk}))
        self.assertEqual(res.status_code, 200)

        # 3. BA Chair can view for BA faculty
        self.client.force_login(self.chair_ba_user)
        res = self.client.get(reverse('assignments:print_accountability', kwargs={'employee_id': self.emp_fac_ba.pk}))
        self.assertEqual(res.status_code, 200)

        # 4. BA Chair CANNOT view for ACCT faculty (403)
        res = self.client.get(reverse('assignments:print_accountability', kwargs={'employee_id': self.emp_fac_acct.pk}))
        self.assertEqual(res.status_code, 403)

        # 5. Faculty can view own certificate
        self.client.force_login(self.faculty_ba_user)
        res = self.client.get(reverse('assignments:print_accountability', kwargs={'employee_id': self.emp_fac_ba.pk}))
        self.assertEqual(res.status_code, 200)

        # 6. Faculty CANNOT view another employee's certificate
        res = self.client.get(reverse('assignments:print_accountability', kwargs={'employee_id': self.emp_fac_acct.pk}))
        self.assertEqual(res.status_code, 403)

    def test_asset_delete_protection_view(self):
        """Asset with assignment history cannot be deleted via AssetDeleteView."""
        self.client.force_login(self.admin_user)

        # Return the asset first so it is available, but still has history
        services.return_asset(
            assignment=self.assign_ba,
            returned_by=self.admin_user
        )

        res = self.client.post(reverse('inventory:asset_delete', kwargs={'asset_code': self.asset_laptop.asset_code}))
        self.assertRedirects(res, reverse('inventory:asset_detail', kwargs={'asset_code': self.asset_laptop.asset_code}))
        self.assertTrue(Asset.objects.filter(asset_code=self.asset_laptop.asset_code).exists())
