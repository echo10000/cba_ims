from datetime import timedelta
from django.test import TestCase, Client, RequestFactory
from django.utils import timezone
from django.core.exceptions import ValidationError, PermissionDenied
from django.core.cache import cache

from apps.accounts.models import User
from apps.organizations.models import Department, Location, Employee
from apps.inventory.models import AssetCategory, Brand, Asset
from apps.borrowing.models import AssetBorrowing
from apps.borrowing import services as borrowing_services
from apps.assignments.models import AssetAssignment
from apps.assignments import services as assignment_services
from apps.student_reservations.models import StudentReservation
from apps.student_reservations import services as student_services
from apps.student_reservations.security import check_submission_rate_limit, mask_contact_info


class StudentReservationBaseTestCase(TestCase):
    """Sets up standard organizational structure, users, assets, and categories."""

    def setUp(self):
        cache.clear()

        # Department & Location
        self.dept_cba = Department.objects.create(code='CBA', name='College of Business Administration')
        self.loc_office = Location.objects.create(
            name='CBA Property Office',
            building='CBA Main',
            room_number='101',
            department=self.dept_cba
        )

        # Users
        self.custodian_user = User.objects.create_superuser(
            'custodian', 'custodian@cba.edu', 'Pass1234!', role=User.Role.ADMIN
        )
        self.faculty_user = User.objects.create_user(
            'faculty_prof', 'faculty@cba.edu', 'Pass1234!', role=User.Role.FACULTY
        )
        self.chair_user = User.objects.create_user(
            'dept_chair', 'chair@cba.edu', 'Pass1234!', role=User.Role.DEPT_CHAIR
        )

        # Employee Profile for Faculty
        self.emp_faculty = Employee.objects.create(
            user=self.faculty_user,
            employee_id='EMP-FAC-99',
            first_name='Juan',
            last_name='Luna',
            department=self.dept_cba,
            location=self.loc_office,
            position='Instructor',
            is_active=True
        )

        # Categories
        self.cat_av = AssetCategory.objects.create(
            code='AV',
            name='Audio-Visual',
            is_active=True,
            is_reservable=True
        )
        self.cat_furniture = AssetCategory.objects.create(
            code='FN',
            name='Office Furniture',
            is_active=True,
            is_reservable=False  # Non-reservable
        )

        self.brand_epson = Brand.objects.create(name='Epson')

        # The office has three individually tracked projectors
        self.proj_1 = Asset.objects.create(
            item_name='Epson EB-X06 Projector 1',
            category=self.cat_av,
            brand=self.brand_epson,
            model='EB-X06',
            serial_number='SN-PROJ-001',
            property_number='CBA-PROP-PROJ-01',
            department=self.dept_cba,
            current_location=self.loc_office,
            condition=Asset.Condition.GOOD,
            status=Asset.Status.AVAILABLE,
            is_reservable=True
        )
        self.proj_2 = Asset.objects.create(
            item_name='Epson EB-X06 Projector 2',
            category=self.cat_av,
            brand=self.brand_epson,
            model='EB-X06',
            serial_number='SN-PROJ-002',
            property_number='CBA-PROP-PROJ-02',
            department=self.dept_cba,
            current_location=self.loc_office,
            condition=Asset.Condition.GOOD,
            status=Asset.Status.AVAILABLE,
            is_reservable=True
        )
        self.proj_3 = Asset.objects.create(
            item_name='Epson EB-X06 Projector 3',
            category=self.cat_av,
            brand=self.brand_epson,
            model='EB-X06',
            serial_number='SN-PROJ-003',
            property_number='CBA-PROP-PROJ-03',
            department=self.dept_cba,
            current_location=self.loc_office,
            condition=Asset.Condition.GOOD,
            status=Asset.Status.AVAILABLE,
            is_reservable=True
        )

        # Default requested intervals
        self.now = timezone.now()
        self.t_start = self.now + timedelta(hours=2)
        self.t_end = self.t_start + timedelta(hours=2)


class StudentReservationLifecycleTestCase(StudentReservationBaseTestCase):
    """Tests reservation submission, approval, release, direct return, and cancellation."""

    def test_reservation_creation(self):
        """Students can submit a reservation without an account, generating an unguessable token."""
        res = student_services.submit_reservation(
            student_id='2024-10001',
            student_name='Clara Del Rosario',
            course_year_section='BSBA 3-B',
            email='clara@student.cba.edu',
            contact_number='09171234567',
            category=self.cat_av,
            equipment_type='Projector',
            requested_pickup=self.t_start,
            requested_return=self.t_end,
            purpose='Marketing presentation in Rm 204',
            room_venue='Room 204'
        )

        self.assertEqual(res.status, StudentReservation.Status.PENDING)
        self.assertIsNone(res.asset)
        self.assertTrue(len(res.lookup_token) >= 32)
        self.assertEqual(res.student_id, '2024-10001')
        self.assertEqual(res.category, self.cat_av)
        self.assertFalse(res.id_deposit_verified)
        self.assertIsNone(res.id_deposited_at)
        self.assertIsNone(res.id_collected_at)

    def test_approval_and_allocation(self):
        """Property Custodian can approve a pending reservation by allocating an available asset."""
        res = student_services.submit_reservation(
            student_id='2024-10001',
            student_name='Clara Del Rosario',
            course_year_section='BSBA 3-B',
            email='clara@student.cba.edu',
            contact_number='09171234567',
            category=self.cat_av,
            equipment_type='Projector',
            requested_pickup=self.t_start,
            requested_return=self.t_end,
            purpose='Presentation'
        )

        approved_res = student_services.approve_reservation(
            reservation=res,
            asset=self.proj_1,
            reviewed_by=self.custodian_user,
            grace_period_minutes=15,
            remarks='Allocated Unit 1'
        )

        self.assertEqual(approved_res.status, StudentReservation.Status.APPROVED)
        self.assertEqual(approved_res.asset, self.proj_1)
        self.assertEqual(approved_res.reviewed_by, self.custodian_user)
        self.assertIsNotNone(approved_res.reviewed_at)
        self.assertEqual(approved_res.grace_period_minutes, 15)

    def test_release_and_school_id_deposit(self):
        """Physical equipment release records original school ID deposit and updates asset status to BORROWED."""
        res = student_services.submit_reservation(
            student_id='2024-10001',
            student_name='Clara Del Rosario',
            course_year_section='BSBA 3-B',
            email='clara@student.cba.edu',
            contact_number='09171234567',
            category=self.cat_av,
            requested_pickup=self.t_start,
            requested_return=self.t_end,
            purpose='Presentation'
        )
        student_services.approve_reservation(res, self.proj_1, self.custodian_user)

        released_res = student_services.release_equipment(
            reservation=res,
            released_by=self.custodian_user,
            condition_at_release=Asset.Condition.GOOD
        )

        self.assertEqual(released_res.status, StudentReservation.Status.RELEASED)
        self.assertTrue(released_res.id_deposit_verified)
        self.assertIsNotNone(released_res.id_deposited_at)
        self.assertTrue(released_res.is_id_in_custody)

        self.proj_1.refresh_from_db()
        self.assertEqual(self.proj_1.status, Asset.Status.BORROWED)

    def test_direct_office_return_and_id_collection(self):
        """Direct office return restores asset to AVAILABLE and allows student to collect deposited ID."""
        res = student_services.submit_reservation(
            student_id='2024-10001',
            student_name='Clara Del Rosario',
            course_year_section='BSBA 3-B',
            email='clara@student.cba.edu',
            contact_number='09171234567',
            category=self.cat_av,
            requested_pickup=self.t_start,
            requested_return=self.t_end,
            purpose='Presentation'
        )
        student_services.approve_reservation(res, self.proj_1, self.custodian_user)
        student_services.release_equipment(res, self.custodian_user)

        returned_res = student_services.return_equipment_to_office(
            reservation=res,
            returned_to=self.custodian_user,
            condition_at_return=Asset.Condition.GOOD,
            return_remarks='Returned complete with HDMI cable',
            id_collected_now=True
        )

        self.assertEqual(returned_res.status, StudentReservation.Status.RETURNED)
        self.assertIsNotNone(returned_res.returned_at)
        self.assertIsNotNone(returned_res.id_collected_at)
        self.assertFalse(returned_res.is_id_in_custody)

        self.proj_1.refresh_from_db()
        self.assertEqual(self.proj_1.status, Asset.Status.AVAILABLE)

    def test_direct_office_return_unserviceable_sets_damaged(self):
        """Returning unserviceable/broken equipment sets canonical asset status to DAMAGED."""
        res = student_services.submit_reservation(
            student_id='2024-10001',
            student_name='Clara Del Rosario',
            course_year_section='BSBA 3-B',
            email='clara@student.cba.edu',
            contact_number='09171234567',
            category=self.cat_av,
            requested_pickup=self.t_start,
            requested_return=self.t_end,
            purpose='Presentation'
        )
        student_services.approve_reservation(res, self.proj_1, self.custodian_user)
        student_services.release_equipment(res, self.custodian_user)

        student_services.return_equipment_to_office(
            reservation=res,
            returned_to=self.custodian_user,
            condition_at_return=Asset.Condition.UNSERVICEABLE,
            return_remarks='Lens cracked and power port loose'
        )

        self.proj_1.refresh_from_db()
        self.assertEqual(self.proj_1.status, Asset.Status.DAMAGED)
        self.assertEqual(self.proj_1.condition, Asset.Condition.UNSERVICEABLE)

    def test_rejection_and_cancellation(self):
        """Custodians can reject with reason; students can cancel pending reservations using token."""
        res1 = student_services.submit_reservation(
            student_id='2024-10001',
            student_name='Student 1',
            course_year_section='BSBA 1-A',
            email='s1@student.cba.edu',
            contact_number='09170000001',
            category=self.cat_av,
            requested_pickup=self.t_start,
            requested_return=self.t_end,
            purpose='Purpose'
        )
        rejected = student_services.reject_reservation(
            res1, self.custodian_user, rejection_reason='Equipment scheduled for maintenance'
        )
        self.assertEqual(rejected.status, StudentReservation.Status.REJECTED)
        self.assertEqual(rejected.rejection_reason, 'Equipment scheduled for maintenance')

        res2 = student_services.submit_reservation(
            student_id='2024-10002',
            student_name='Student 2',
            course_year_section='BSBA 1-B',
            email='s2@student.cba.edu',
            contact_number='09170000002',
            category=self.cat_av,
            requested_pickup=self.t_start,
            requested_return=self.t_end,
            purpose='Purpose'
        )
        cancelled = student_services.cancel_reservation(
            res2, lookup_token=res2.lookup_token, reason='Activity cancelled by professor'
        )
        self.assertEqual(cancelled.status, StudentReservation.Status.CANCELLED)


class ThreeProjectorAvailabilityTestCase(StudentReservationBaseTestCase):
    """
    Tests the confirmed business rule:
    'The office has three individually tracked projectors.
    Students request an equipment type; the Custodian allocates a specific available asset when approving.'
    """

    def test_three_projectors_saturation_and_availability(self):
        """Checks availability counts and allocation when all 3 projectors are booked."""
        # 1. Initial state: All 3 projectors available
        avail = student_services.get_available_assets_for_category(
            category=self.cat_av,
            requested_pickup=self.t_start,
            requested_return=self.t_end
        )
        self.assertEqual(len(avail), 3)

        # 2. Student 1 reserves and is allocated Proj 1
        r1 = student_services.submit_reservation(
            'ST-1', 'Student 1', 'BSBA 1', 's1@cba.edu', '09171111111',
            self.cat_av, self.t_start, self.t_end, 'Presentation'
        )
        student_services.approve_reservation(r1, self.proj_1, self.custodian_user)

        # 2 projectors remaining
        avail = student_services.get_available_assets_for_category(
            category=self.cat_av,
            requested_pickup=self.t_start,
            requested_return=self.t_end
        )
        self.assertEqual(len(avail), 2)
        self.assertNotIn(self.proj_1, avail)

        # 3. Student 2 reserves overlapping slot (starts 30m later) and is allocated Proj 2
        r2 = student_services.submit_reservation(
            'ST-2', 'Student 2', 'BSBA 2', 's2@cba.edu', '09172222222',
            self.cat_av, self.t_start + timedelta(minutes=30), self.t_end, 'Defense'
        )
        student_services.approve_reservation(r2, self.proj_2, self.custodian_user)

        # 1 projector remaining
        avail = student_services.get_available_assets_for_category(
            category=self.cat_av,
            requested_pickup=self.t_start,
            requested_return=self.t_end
        )
        self.assertEqual(len(avail), 1)
        self.assertEqual(avail[0], self.proj_3)

        # 4. Student 3 reserves overlapping slot and is allocated Proj 3
        r3 = student_services.submit_reservation(
            'ST-3', 'Student 3', 'BSBA 3', 's3@cba.edu', '09173333333',
            self.cat_av, self.t_start, self.t_end, 'Webinar'
        )
        student_services.approve_reservation(r3, self.proj_3, self.custodian_user)

        # 0 projectors remaining for this overlapping slot
        avail = student_services.get_available_assets_for_category(
            category=self.cat_av,
            requested_pickup=self.t_start,
            requested_return=self.t_end
        )
        self.assertEqual(len(avail), 0)

        # 5. A 4th overlapping reservation cannot allocate any projector
        r4 = student_services.submit_reservation(
            'ST-4', 'Student 4', 'BSBA 4', 's4@cba.edu', '09174444444',
            self.cat_av, self.t_start, self.t_end, 'Class'
        )
        with self.assertRaises(ValidationError):
            student_services.approve_reservation(r4, self.proj_1, self.custodian_user)

        # 6. Non-overlapping future slot (later that day) still has all 3 projectors available
        future_start = self.t_end + timedelta(hours=1)
        future_end = future_start + timedelta(hours=2)
        future_avail = student_services.get_available_assets_for_category(
            category=self.cat_av,
            requested_pickup=future_start,
            requested_return=future_end
        )
        self.assertEqual(len(future_avail), 3)

        # 7. If Student 1 cancels, Proj 1 immediately becomes available again
        student_services.cancel_reservation(r1, lookup_token=r1.lookup_token)
        avail = student_services.get_available_assets_for_category(
            category=self.cat_av,
            requested_pickup=self.t_start,
            requested_return=self.t_end
        )
        self.assertEqual(len(avail), 1)
        self.assertEqual(avail[0], self.proj_1)


class OverlappingAndConflictTestCase(StudentReservationBaseTestCase):
    """Tests strict prevention of overlapping bookings and double-booking."""

    def test_prevent_double_booking_same_asset(self):
        """An asset approved for interval [t1, t2] cannot be allocated to another reservation overlapping [t1, t2]."""
        r1 = student_services.submit_reservation(
            'ST-1', 'Student 1', 'BSBA 1', 's1@cba.edu', '09171111111',
            self.cat_av, self.t_start, self.t_end, 'Event'
        )
        student_services.approve_reservation(r1, self.proj_1, self.custodian_user)

        r2 = student_services.submit_reservation(
            'ST-2', 'Student 2', 'BSBA 2', 's2@cba.edu', '09172222222',
            self.cat_av, self.t_start + timedelta(minutes=15), self.t_end + timedelta(minutes=15), 'Event'
        )
        with self.assertRaises(ValidationError) as ctx:
            student_services.approve_reservation(r2, self.proj_1, self.custodian_user)
        self.assertIn("overlapping approved student reservation", str(ctx.exception))

    def test_pending_reservations_do_not_block_equipment(self):
        """Confirmed rule: Pending requests do not block equipment until Custodian approval."""
        r1 = student_services.submit_reservation(
            'ST-1', 'Student 1', 'BSBA 1', 's1@cba.edu', '09171111111',
            self.cat_av, self.t_start, self.t_end, 'Event'
        )
        self.assertEqual(r1.status, StudentReservation.Status.PENDING)

        # All 3 projectors must still be available
        avail = student_services.get_available_assets_for_category(
            self.cat_av, self.t_start, self.t_end
        )
        self.assertEqual(len(avail), 3)


class SharedAvailabilityIntegrationTestCase(StudentReservationBaseTestCase):
    """
    Tests shared availability rules:
    - Existing faculty borrowings block student reservations.
    - Student reservations block faculty borrowings.
    - Active employee assignments block student reservations.
    - Student reservations block employee assignments.
    """

    def test_faculty_borrowing_blocks_student_reservation(self):
        """Faculty borrowing in apps/borrowing blocks student reservation for that interval."""
        # Faculty borrows Proj 1
        borrowing = borrowing_services.request_borrowing(
            asset=self.proj_1,
            borrower=self.emp_faculty,
            purpose='Lecture instruction',
            requested_start=self.t_start,
            requested_return=self.t_end
        )
        borrowing_services.approve_borrowing(borrowing, reviewed_by=self.custodian_user)

        # Check availability for student reservation: Proj 1 must not be available
        avail = student_services.get_available_assets_for_category(
            self.cat_av, self.t_start, self.t_end
        )
        self.assertNotIn(self.proj_1, avail)

        # Attempting to allocate Proj 1 to a student reservation must raise ValidationError
        student_res = student_services.submit_reservation(
            'ST-1', 'Student 1', 'BSBA 1', 's1@cba.edu', '09171111111',
            self.cat_av, self.t_start, self.t_end, 'Student Meeting'
        )
        with self.assertRaises(ValidationError) as ctx:
            student_services.approve_reservation(student_res, self.proj_1, self.custodian_user)
        self.assertIn("overlapping faculty borrowing", str(ctx.exception))

    def test_student_reservation_blocks_faculty_borrowing(self):
        """Approved student reservation blocks faculty borrowing from taking the same equipment."""
        student_res = student_services.submit_reservation(
            'ST-1', 'Student 1', 'BSBA 1', 's1@cba.edu', '09171111111',
            self.cat_av, self.t_start, self.t_end, 'Classroom Activity'
        )
        student_services.approve_reservation(student_res, self.proj_1, self.custodian_user)

        # Faculty attempts to request Proj 1 for the same interval
        with self.assertRaises(ValidationError) as ctx:
            borrowing_services.request_borrowing(
                asset=self.proj_1,
                borrower=self.emp_faculty,
                purpose='Faculty instruction',
                requested_start=self.t_start,
                requested_return=self.t_end
            )
        self.assertIn("already reserved for a student", str(ctx.exception))

    def test_active_assignment_blocks_student_reservation(self):
        """Asset with active long-term AssetAssignment cannot be reserved by students."""
        assignment_services.assign_asset(
            asset=self.proj_2,
            employee=self.emp_faculty,
            assigned_by=self.custodian_user,
            purpose='Permanent office accountability'
        )

        avail = student_services.get_available_assets_for_category(
            self.cat_av, self.t_start, self.t_end
        )
        self.assertNotIn(self.proj_2, avail)

        student_res = student_services.submit_reservation(
            'ST-1', 'Student 1', 'BSBA 1', 's1@cba.edu', '09171111111',
            self.cat_av, self.t_start, self.t_end, 'Presentation'
        )
        with self.assertRaises(ValidationError) as ctx:
            student_services.approve_reservation(student_res, self.proj_2, self.custodian_user)
        self.assertIn("ongoing employee accountability", str(ctx.exception))

    def test_student_reservation_blocks_assignment(self):
        """Asset with approved student reservation cannot be assigned under ongoing employee accountability."""
        student_res = student_services.submit_reservation(
            'ST-1', 'Student 1', 'BSBA 1', 's1@cba.edu', '09171111111',
            self.cat_av, self.t_start, self.t_end, 'Presentation'
        )
        student_services.approve_reservation(student_res, self.proj_1, self.custodian_user)

        with self.assertRaises(ValidationError) as ctx:
            assignment_services.assign_asset(
                asset=self.proj_1,
                employee=self.emp_faculty,
                assigned_by=self.custodian_user,
                purpose='New assignment'
            )
        self.assertIn("approved or active student reservation", str(ctx.exception))


class NoShowAndGracePeriodTestCase(StudentReservationBaseTestCase):
    """
    Tests pickup grace period (15 minutes default, extendable) and no-show handling.
    Confirmed rule: 'Treat expired uncollected reservations correctly, without requiring a background task.'
    """

    def test_grace_period_calculation_and_extension(self):
        """Default grace period is 15 minutes; Custodian can extend it."""
        pickup = self.now + timedelta(minutes=10)
        res = student_services.submit_reservation(
            'ST-1', 'Student 1', 'BSBA 1', 's1@cba.edu', '09171111111',
            self.cat_av, pickup, pickup + timedelta(hours=2), 'Presentation'
        )
        student_services.approve_reservation(res, self.proj_1, self.custodian_user, grace_period_minutes=15)

        self.assertEqual(res.grace_period_minutes, 15)
        self.assertEqual(res.pickup_deadline, pickup + timedelta(minutes=15))

        # Custodian extends grace period by 20 minutes
        student_services.extend_grace_period(
            res, additional_minutes=20, extended_by=self.custodian_user, reason='Student delayed in traffic'
        )
        res.refresh_from_db()
        self.assertEqual(res.grace_period_minutes, 35)
        self.assertEqual(res.pickup_deadline, pickup + timedelta(minutes=35))

    def test_expired_uncollected_reservation_does_not_block_equipment(self):
        """
        When pickup grace deadline has passed, the approved reservation is expired
        and does NOT block other bookings, even without an external cron/celery worker.
        """
        past_pickup = self.now - timedelta(minutes=30)
        res = StudentReservation.objects.create(
            student_id='ST-1',
            student_name='Student 1',
            course_year_section='BSBA 1',
            email='s1@cba.edu',
            contact_number='09171111111',
            category=self.cat_av,
            asset=self.proj_1,
            requested_pickup=past_pickup,
            requested_return=past_pickup + timedelta(hours=2),
            purpose='Presentation',
            status=StudentReservation.Status.APPROVED,
            reviewed_by=self.custodian_user,
            reviewed_at=past_pickup - timedelta(hours=1),
            grace_period_minutes=15
        )

        # 30 minutes have passed since pickup; with 15m grace period, deadline was 15m ago
        self.assertTrue(res.is_pickup_expired)

        # Checking availability for Proj 1 for a new reservation right now
        avail = student_services.get_available_assets_for_category(
            self.cat_av, self.now, self.now + timedelta(hours=2)
        )
        # Proj 1 is treated as available because previous reservation expired uncollected!
        self.assertIn(self.proj_1, avail)

        # Auto-expiration lazily marks it as NO_SHOW in DB
        res.refresh_from_db()
        self.assertEqual(res.status, StudentReservation.Status.NO_SHOW)

    def test_releasing_expired_reservation_without_extension_fails(self):
        """Attempting to release an approved reservation after grace period expires raises ValidationError."""
        past_pickup = self.now - timedelta(minutes=20)
        res = StudentReservation.objects.create(
            student_id='ST-1',
            student_name='Student 1',
            course_year_section='BSBA 1',
            email='s1@cba.edu',
            contact_number='09171111111',
            category=self.cat_av,
            asset=self.proj_1,
            requested_pickup=past_pickup,
            requested_return=past_pickup + timedelta(hours=2),
            purpose='Presentation',
            status=StudentReservation.Status.APPROVED,
            reviewed_by=self.custodian_user,
            reviewed_at=past_pickup - timedelta(hours=1),
            grace_period_minutes=15
        )

        with self.assertRaises(ValidationError) as ctx:
            student_services.release_equipment(res, self.custodian_user)
        err = str(ctx.exception)
        self.assertTrue("Pickup grace period expired" in err or "No Show" in err)


class GuardReturnWorkflowTestCase(StudentReservationBaseTestCase):
    """
    Tests security guard return and CBA office inspection workflow:
    - Return to guard after hours.
    - CBA records handover next day using actual documented handover time.
    - Asset remains unavailable (BORROWED) until CBA inspects it.
    - Student collects deposited ID at CBA office.
    """

    def test_guard_return_and_cba_inspection_workflow(self):
        """Complete workflow for after-hours guard handover and inspection."""
        res = student_services.submit_reservation(
            'ST-1', 'Student 1', 'BSBA 1', 's1@cba.edu', '09171111111',
            self.cat_av, self.t_start, self.t_end, 'Evening Study'
        )
        student_services.approve_reservation(res, self.proj_1, self.custodian_user)
        student_services.release_equipment(res, self.custodian_user)

        # Simulate elapsed time so handover occurred earlier today
        released_time = self.now - timedelta(hours=3)
        guard_handover_time = self.now - timedelta(hours=1)
        StudentReservation.objects.filter(pk=res.pk).update(released_at=released_time)
        res.refresh_from_db()

        recorded_guard_res = student_services.record_guard_return(
            reservation=res,
            recorded_by=self.custodian_user,
            guard_returned_at=guard_handover_time,
            guard_handover_details='Security Guard R. Cruz, CBA Lobby Post Logbook Entry #88',
            remarks='Handed over to guard at 7:15 PM'
        )

        self.assertEqual(recorded_guard_res.status, StudentReservation.Status.RETURNED_TO_GUARD)
        self.assertEqual(recorded_guard_res.guard_returned_at, guard_handover_time)
        self.assertEqual(recorded_guard_res.guard_recorded_by, self.custodian_user)

        # Asset remains BORROWED / unavailable until inspected!
        self.proj_1.refresh_from_db()
        self.assertEqual(self.proj_1.status, Asset.Status.BORROWED)

        # Student ID is still deposited in CBA office (guard does NOT have the ID)
        self.assertTrue(recorded_guard_res.is_id_in_custody)
        self.assertIsNone(recorded_guard_res.id_collected_at)

        # Proj 1 is completely unavailable for other reservations
        is_avail, reason = student_services.check_asset_availability(
            self.proj_1, self.t_end + timedelta(hours=2), self.t_end + timedelta(hours=4)
        )
        self.assertFalse(is_avail)
        self.assertIn("awaiting CBA inspection", reason)

        # Next working day: CBA Custodian completes inspection
        inspected_res = student_services.complete_inspection(
            reservation=recorded_guard_res,
            inspected_by=self.custodian_user,
            condition_at_return=Asset.Condition.GOOD,
            inspection_remarks='Tested unit, bulb working, remote and VGA/HDMI cables present',
            id_collected_now=False
        )

        self.assertEqual(inspected_res.status, StudentReservation.Status.RETURNED)
        self.assertIsNotNone(inspected_res.cba_inspected_at)

        # Proj 1 is now AVAILABLE again
        self.proj_1.refresh_from_db()
        self.assertEqual(self.proj_1.status, Asset.Status.AVAILABLE)

        # Student subsequently visits CBA office to collect their deposited school ID
        collected_id_res = student_services.record_id_collection(
            reservation=inspected_res,
            returned_by=self.custodian_user,
            remarks='Original school ID released to student Clara upon signing logbook'
        )
        self.assertIsNotNone(collected_id_res.id_collected_at)
        self.assertFalse(collected_id_res.is_id_in_custody)


class OverdueCalculationTestCase(StudentReservationBaseTestCase):
    """Tests overdue calculations based on expected return deadline and actual handover time."""

    def test_released_equipment_overdue(self):
        """Released equipment past return deadline is dynamically calculated as overdue."""
        past_start = self.now - timedelta(hours=3)
        past_return = self.now - timedelta(hours=1)

        res = StudentReservation.objects.create(
            student_id='ST-1',
            student_name='Student 1',
            course_year_section='BSBA 1',
            email='s1@cba.edu',
            contact_number='09171111111',
            category=self.cat_av,
            asset=self.proj_1,
            requested_pickup=past_start,
            requested_return=past_return,
            purpose='Event',
            status=StudentReservation.Status.RELEASED,
            released_by=self.custodian_user,
            released_at=past_start,
            id_deposit_verified=True
        )

        self.assertTrue(res.is_overdue)
        self.assertGreater(res.overdue_duration.total_seconds(), 0)

    def test_guard_return_overdue_calculation(self):
        """Guard return handed over past deadline is calculated as overdue using documented handover time."""
        past_start = self.now - timedelta(hours=4)
        deadline = self.now - timedelta(hours=2)
        handover = self.now - timedelta(hours=1)  # 1 hour late

        res = StudentReservation.objects.create(
            student_id='ST-1',
            student_name='Student 1',
            course_year_section='BSBA 1',
            email='s1@cba.edu',
            contact_number='09171111111',
            category=self.cat_av,
            asset=self.proj_1,
            requested_pickup=past_start,
            requested_return=deadline,
            purpose='Event',
            status=StudentReservation.Status.RELEASED,
            released_by=self.custodian_user,
            released_at=past_start,
            id_deposit_verified=True
        )

        student_services.record_guard_return(
            reservation=res,
            recorded_by=self.custodian_user,
            guard_returned_at=handover,
            guard_handover_details='Guard post handover'
        )
        res.refresh_from_db()

        self.assertTrue(res.is_overdue)
        self.assertAlmostEqual(res.overdue_duration.total_seconds(), 3600, delta=10)


class SecurityAndAccessControlTestCase(StudentReservationBaseTestCase):
    """Tests security rules, permission checks, lookup protection, and rate limiting."""

    def test_non_admin_cannot_perform_office_actions(self):
        """Faculty, Chairs, and unauthenticated users cannot approve, release, or inspect equipment."""
        res = student_services.submit_reservation(
            'ST-1', 'Student 1', 'BSBA 1', 's1@cba.edu', '09171111111',
            self.cat_av, self.t_start, self.t_end, 'Event'
        )

        with self.assertRaises(PermissionDenied):
            student_services.approve_reservation(res, self.proj_1, self.faculty_user)

        with self.assertRaises(PermissionDenied):
            student_services.approve_reservation(res, self.proj_1, self.chair_user)

        with self.assertRaises(PermissionDenied):
            student_services.approve_reservation(res, self.proj_1, None)

    def test_public_lookup_by_token_and_privacy_masking(self):
        """Public lookup requires valid lookup_token and masks student contact information."""
        res = student_services.submit_reservation(
            'ST-1', 'Maria Clara', 'BSBA 2-A', 'mariaclara@student.edu', '09171234567',
            self.cat_av, self.t_start, self.t_end, 'Report'
        )

        # Lookup by token succeeds
        found = student_services.get_reservation_by_token(res.lookup_token)
        self.assertEqual(found.pk, res.pk)

        # Invalid token fails
        with self.assertRaises(ValidationError):
            student_services.get_reservation_by_token('non-existent-random-token-xyz')

        # Contact masking test
        masked_email, masked_phone = mask_contact_info(res.email, res.contact_number)
        self.assertNotEqual(masked_email, res.email)
        self.assertIn('***', masked_email)
        self.assertNotEqual(masked_phone, res.contact_number)
        self.assertIn('****', masked_phone)

    def test_rate_limiting_prevents_excessive_submissions(self):
        """Rate limiting prevents more than 3 pending requests for the same student ID."""
        for i in range(3):
            student_services.submit_reservation(
                'ST-SPAM-1', f'Spam Student {i}', 'BSBA 1', f'spam{i}@cba.edu', '09170000000',
                self.cat_av, self.t_start + timedelta(days=i), self.t_end + timedelta(days=i), 'Purpose'
            )

        factory = RequestFactory()
        req = factory.post('/student-reservations/request/')

        with self.assertRaises(ValidationError) as ctx:
            check_submission_rate_limit(req, 'ST-SPAM-1')
        self.assertIn("already has 3 pending reservations", str(ctx.exception))

    def test_non_reservable_category_excluded_from_catalog(self):
        """Items in non-reservable categories cannot be reserved."""
        with self.assertRaises(ValidationError) as ctx:
            student_services.submit_reservation(
                'ST-1', 'Student 1', 'BSBA 1', 's1@cba.edu', '09171111111',
                self.cat_furniture, self.t_start, self.t_end, 'Need chairs'
            )
        self.assertIn("not currently available for reservations", str(ctx.exception))


class InvalidStatusTransitionsTestCase(StudentReservationBaseTestCase):
    """Tests that illegal or out-of-order lifecycle transitions are strictly rejected."""

    def test_cannot_release_pending_reservation(self):
        """A reservation must be in APPROVED status before it can be released."""
        res = student_services.submit_reservation(
            'ST-1', 'Student 1', 'BSBA 1', 's1@cba.edu', '09171111111',
            self.cat_av, self.t_start, self.t_end, 'Event'
        )
        with self.assertRaises(ValidationError):
            student_services.release_equipment(res, self.custodian_user)

    def test_cannot_return_unreleased_reservation(self):
        """A reservation must be in RELEASED status before it can be returned."""
        res = student_services.submit_reservation(
            'ST-1', 'Student 1', 'BSBA 1', 's1@cba.edu', '09171111111',
            self.cat_av, self.t_start, self.t_end, 'Event'
        )
        student_services.approve_reservation(res, self.proj_1, self.custodian_user)

        with self.assertRaises(ValidationError):
            student_services.return_equipment_to_office(
                res, self.custodian_user, Asset.Condition.GOOD
            )

    def test_cannot_inspect_direct_office_return(self):
        """Guard inspection is only valid for reservations in RETURNED_TO_GUARD status."""
        res = student_services.submit_reservation(
            'ST-1', 'Student 1', 'BSBA 1', 's1@cba.edu', '09171111111',
            self.cat_av, self.t_start, self.t_end, 'Event'
        )
        student_services.approve_reservation(res, self.proj_1, self.custodian_user)
        student_services.release_equipment(res, self.custodian_user)
        student_services.return_equipment_to_office(res, self.custodian_user, Asset.Condition.GOOD)

        with self.assertRaises(ValidationError):
            student_services.complete_inspection(res, self.custodian_user, Asset.Condition.GOOD)


class StudentReservationFrontendViewTestCase(StudentReservationBaseTestCase):
    """
    Focused tests for Phase 2A student-facing views, templates, validation, and HTMX endpoints:
    1. Catalog view with reservable assets and availability checking
    2. Availability checker HTMX endpoint
    3. Mobile-friendly reservation form (GET & POST)
    4. Confirmation screen and tracking token
    5. Status lookup view (HTML, HTMX partial, and JSON API)
    """

    def setUp(self):
        super().setUp()
        self.client = Client()

    def test_catalog_view_renders_properly(self):
        """Catalog displays reservable categories and unit counts while excluding non-reservable categories."""
        response = self.client.get('/student-reservations/')
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'student_reservations/catalog.html')
        self.assertContains(response, 'Audio-Visual')
        self.assertContains(response, '3 Units Tracked')
        # Non-reservable category should not appear as a reservable card
        self.assertNotContains(response, 'Office Furniture')

    def test_check_availability_htmx_endpoint(self):
        """HTMX schedule availability checker returns live counts for requested timeslot."""
        pickup_str = self.t_start.strftime('%Y-%m-%dT%H:%M')
        return_str = self.t_end.strftime('%Y-%m-%dT%H:%M')

        # 1. Available check (all 3 projectors available)
        response = self.client.get(
            f'/student-reservations/check-availability/?pickup={pickup_str}&return={return_str}'
        )
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'student_reservations/partials/_availability_result.html')
        self.assertContains(response, '3 / 3 Available')

        # 2. Allocate and approve all 3 projectors for this timeslot
        for i, proj in enumerate([self.proj_1, self.proj_2, self.proj_3], start=1):
            r = student_services.submit_reservation(
                f'ST-TEST-{i}', f'Student {i}', 'BSBA 1', f'st{i}@cba.edu', '09170000000',
                self.cat_av, self.t_start, self.t_end, 'Event'
            )
            student_services.approve_reservation(r, proj, self.custodian_user)

        # 3. Check again: now 0 of 3 available (Fully Booked)
        response = self.client.get(
            f'/student-reservations/check-availability/?pickup={pickup_str}&return={return_str}'
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Fully Booked')

    def test_check_availability_validation_errors(self):
        """Availability checker displays errors on invalid timeslots."""
        # Return time before pickup time
        pickup_str = self.t_end.strftime('%Y-%m-%dT%H:%M')
        return_str = self.t_start.strftime('%Y-%m-%dT%H:%M')
        response = self.client.get(
            f'/student-reservations/check-availability/?pickup={pickup_str}&return={return_str}'
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Requested return time must be strictly after pickup time.')

    def test_reservation_form_get_and_post_submission(self):
        """Student reservation form renders properly and accepts valid submissions."""
        # 1. GET form
        response = self.client.get(f'/student-reservations/request/?category={self.cat_av.id}')
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'student_reservations/reservation_form.html')
        self.assertContains(response, 'Physical School ID Custody Policy')

        # 2. POST valid submission
        post_data = {
            'student_id': '2024-99881',
            'student_name': 'Jose Rizal',
            'course_year_section': 'BSBA MM 4-A',
            'email': 'j.rizal@student.cba.edu',
            'contact_number': '09181234567',
            'category': self.cat_av.id,
            'equipment_type': 'HDMI Projector',
            'requested_pickup': (timezone.now() + timedelta(hours=2)).strftime('%Y-%m-%dT%H:%M'),
            'requested_return': (timezone.now() + timedelta(hours=5)).strftime('%Y-%m-%dT%H:%M'),
            'purpose': 'Marketing thesis oral defense in AVR',
            'room_venue': 'AVR Hall',
        }
        post_resp = self.client.post('/student-reservations/request/', data=post_data)
        # Should redirect to confirmation page
        self.assertEqual(post_resp.status_code, 302)
        self.assertIn('/student-reservations/confirmed/', post_resp.url)

        res = StudentReservation.objects.get(student_id='2024-99881')
        self.assertEqual(res.status, StudentReservation.Status.PENDING)
        self.assertIsNotNone(res.lookup_token)

    def test_confirmation_page_renders_with_token(self):
        """Confirmation screen displays reservation token, summary, and next steps."""
        res = student_services.submit_reservation(
            '2024-55443', 'Andres Bonifacio', 'BSBA 3-B', 'a.bonifacio@cba.edu', '09191234567',
            self.cat_av, self.t_start, self.t_end, 'Leadership Seminar', 'Room 102'
        )
        response = self.client.get(f'/student-reservations/confirmed/{res.lookup_token}/')
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'student_reservations/confirmation.html')
        self.assertContains(response, res.lookup_token)
        self.assertContains(response, 'Andres Bonifacio')
        self.assertContains(response, 'What Happens Next?')

    def test_status_lookup_page_and_htmx_partial(self):
        """Status lookup renders full page and HTMX status card with privacy masking."""
        res = student_services.submit_reservation(
            '2024-11223', 'Apolinario Mabini', 'BSBA 2-A', 'mabini@cba.edu', '09179876543',
            self.cat_av, self.t_start, self.t_end, 'Research Presentation'
        )

        # 1. Empty lookup page
        response = self.client.get('/student-reservations/lookup/')
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'student_reservations/lookup.html')
        self.assertContains(response, 'Track Equipment Reservation')

        # 2. Lookup with token GET param
        response = self.client.get(f'/student-reservations/lookup/?token={res.lookup_token}')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Apolinario Mabini')
        self.assertContains(response, 'Pending Custodian Review')
        # Privacy masking: real email & phone are masked
        self.assertNotContains(response, 'mabini@cba.edu')
        self.assertNotContains(response, '09179876543')

        # 3. Direct lookup URL
        response = self.client.get(f'/student-reservations/lookup/{res.lookup_token}/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Apolinario Mabini')

        # 4. HTMX partial request
        htmx_resp = self.client.get(
            f'/student-reservations/lookup/{res.lookup_token}/',
            HTTP_HX_REQUEST='true'
        )
        self.assertEqual(htmx_resp.status_code, 200)
        self.assertTemplateUsed(htmx_resp, 'student_reservations/partials/_status_card.html')

        # 5. Invalid token renders warning
        invalid_resp = self.client.get('/student-reservations/lookup/?token=invalid-random-token')
        self.assertEqual(invalid_resp.status_code, 200)
        self.assertContains(invalid_resp, 'Reservation Not Found')

    def test_multi_day_longer_reservation_request_allowed(self):
        """
        Valid multi-day reservation requests (e.g. 72-hour weekend event) are accepted without
        an unapproved 48-hour ceiling, while remaining strictly in PENDING status for manual Custodian review.
        """
        # Friday 1:00 PM to Monday 1:00 PM (72 hours)
        long_pickup = timezone.now() + timedelta(days=2)
        long_return = long_pickup + timedelta(hours=72)

        post_data = {
            'student_id': '2024-77889',
            'student_name': 'Melchora Aquino',
            'course_year_section': 'BSBA 4-C',
            'email': 'm.aquino@student.cba.edu',
            'contact_number': '09171239876',
            'category': self.cat_av.id,
            'equipment_type': 'Projector',
            'requested_pickup': long_pickup.strftime('%Y-%m-%dT%H:%M'),
            'requested_return': long_return.strftime('%Y-%m-%dT%H:%M'),
            'purpose': 'College Business Leadership Weekend Symposium',
            'room_venue': 'University Auditorium',
        }
        response = self.client.post('/student-reservations/request/', data=post_data)
        # Successfully accepted and redirected to confirmation (not rejected by 48-hour error)
        self.assertEqual(response.status_code, 302)
        self.assertIn('/student-reservations/confirmed/', response.url)

        res = StudentReservation.objects.get(student_id='2024-77889')
        # Remains in PENDING status awaiting manual Custodian approval; not automatically approved
        self.assertEqual(res.status, StudentReservation.Status.PENDING)
        self.assertIsNone(res.asset)
        self.assertIsNone(res.reviewed_by)

    def test_check_availability_supports_multi_day_interval(self):
        """Availability checker supports intervals longer than 48 hours without error."""
        long_pickup = timezone.now() + timedelta(days=1)
        long_return = long_pickup + timedelta(hours=72)
        pickup_str = long_pickup.strftime('%Y-%m-%dT%H:%M')
        return_str = long_return.strftime('%Y-%m-%dT%H:%M')

        response = self.client.get(
            f'/student-reservations/check-availability/?pickup={pickup_str}&return={return_str}'
        )
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'student_reservations/partials/_availability_result.html')
        self.assertNotContains(response, '48 consecutive hours')
        self.assertContains(response, '3 / 3 Available')


