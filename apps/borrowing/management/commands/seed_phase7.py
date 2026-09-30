from datetime import timedelta
from decimal import Decimal
from django.core.management.base import BaseCommand, CommandError
from django.core.management import call_command
from django.utils import timezone

from apps.accounts.models import User
from apps.organizations.models import Department, Location, Employee
from apps.inventory.models import Asset, AssetCategory, Brand
from apps.borrowing.models import AssetBorrowing


class Command(BaseCommand):
    help = 'Seed realistic temporary borrowing and equipment reservation records for CBA IMS Phase 7'

    def add_arguments(self, parser):
        parser.add_argument(
            '--force-demo-data',
            action='store_true',
            help='Required to run seed commands outside of DEBUG mode. THIS CREATES DEMO ACCOUNTS WITH KNOWN PASSWORDS.',
        )

    def handle(self, *args, **options):
        from django.conf import settings
        if not settings.DEBUG and not options.get('force_demo_data'):
            raise CommandError(
                'SAFETY: Seed commands create demo accounts with known passwords.\n'
                'Running them in a production environment (DEBUG=False) is not allowed.\n'
                'If you INTENTIONALLY want to populate a non-debug environment with demo data,\n'
                'pass --force-demo-data flag. THIS IS NOT RECOMMENDED FOR PRODUCTION.'
            )
        if not settings.DEBUG and options.get('force_demo_data'):
            self.stdout.write(self.style.WARNING(
                'WARNING: Running demo seed data in a non-DEBUG environment. '
                'Demo accounts with known passwords are being created. '
                'Change or remove these accounts before any real use.'
            ))
        self.stdout.write(self.style.NOTICE('Seeding CBA IMS Phase 7 Equipment Borrowing & Reservations...'))

        # Ensure Phase 1, Phase 2, and Phase 3 data exist
        if not Department.objects.exists():
            self.stdout.write('  Running seed_phase1...')
            call_command('seed_phase1')
        if not Asset.objects.exists():
            self.stdout.write('  Running seed_phase2...')
            call_command('seed_phase2')
        if not Employee.objects.filter(assignments__isnull=False).exists():
            self.stdout.write('  Running seed_phase3...')
            call_command('seed_phase3')

        admin = User.objects.filter(role=User.Role.ADMIN).first()
        if not admin:
            admin = User.objects.create_superuser('admin', 'admin@cba.edu', 'admin123')
            admin.role = User.Role.ADMIN
            admin.save()

        dept_ba = Department.objects.filter(code='BA').first() or Department.objects.first()
        dept_acct = Department.objects.filter(code='ACCT').first() or dept_ba
        loc_storage = Location.objects.filter(name__icontains='Storage').first() or Location.objects.first()

        cat_av = AssetCategory.objects.filter(code='AV').first()
        if not cat_av:
            cat_av = AssetCategory.objects.create(
                code='AV',
                name='Audio-Visual & Presentation Equipment',
                description='Projectors, presentation remotes, PA speakers, webcams and media gear.'
            )

        brand_epson = Brand.objects.filter(name__icontains='Epson').first()
        brand_logitech = Brand.objects.filter(name__icontains='Logitech').first()
        if not brand_logitech:
            brand_logitech = Brand.objects.create(name='Logitech')

        brand_sony = Brand.objects.filter(name__icontains='Sony').first()
        if not brand_sony:
            brand_sony = Brand.objects.create(name='Sony')

        # Ensure borrowable pool assets exist
        def get_or_create_asset(item_name, cat, brand, model, prop_num, cost, desc):
            asset = Asset.objects.filter(property_number=prop_num).first()
            if not asset:
                asset = Asset.objects.create(
                    item_name=item_name,
                    category=cat,
                    brand=brand,
                    model=model,
                    property_number=prop_num,
                    department=dept_ba,
                    current_location=loc_storage,
                    condition=Asset.Condition.GOOD,
                    status=Asset.Status.AVAILABLE,
                    acquisition_date=timezone.now().date() - timedelta(days=120),
                    acquisition_cost=Decimal(str(cost)),
                    supplier='CBA Media & Academic Solutions',
                    description=desc,
                    remarks='Designated for faculty temporary loan and institutional reservations.',
                    created_by=admin
                )
            return asset

        asset_projector = get_or_create_asset(
            'Epson EB-FH52 Full HD Wireless Projector',
            cat_av, brand_epson, 'EB-FH52', 'NORSU-CBA-2026-AV001',
            38500.00, '4,000 lumens Full HD 1080p wireless business projector.'
        )

        asset_clicker = get_or_create_asset(
            'Logitech Spotlight Wireless Presentation Remote',
            cat_av, brand_logitech, 'Spotlight Plus', 'NORSU-CBA-2026-AV002',
            6200.00, 'Advanced pointer system with timer vibration and Bluetooth/2.4GHz connectivity.'
        )

        asset_speaker = get_or_create_asset(
            'Sony SRS-XP500 Portable Wireless PA Speaker',
            cat_av, brand_sony, 'SRS-XP500', 'NORSU-CBA-2026-AV003',
            18990.00, 'Rechargeable wireless party/PA speaker with dual microphone inputs.'
        )

        asset_webcam = get_or_create_asset(
            'Logitech Brio 4K Ultra HD Conference Webcam',
            cat_av, brand_logitech, 'Brio 4K', 'NORSU-CBA-2026-AV004',
            11500.00, '4K webcam with HDR, dual omnidirectional microphones, and tripod clip.'
        )

        prof_maria = Employee.objects.filter(employee_id='EMP-FAC-001').first()
        prof_garcia = Employee.objects.filter(employee_id='EMP-FAC-002').first()
        chair_santos = Employee.objects.filter(employee_id='EMP-ACCT-001').first()

        now = timezone.now()

        # ----------------------------------------------------------------------
        # 1. PENDING Request: Presentation Remote requested by Prof. Maria
        # ----------------------------------------------------------------------
        req1_purpose = 'CBA Faculty Research Colloquium - Wireless presentation remote needed for research paper delivery.'
        b1 = AssetBorrowing.objects.filter(purpose=req1_purpose).first()
        if not b1 and prof_maria:
            b1 = AssetBorrowing.objects.create(
                asset=asset_clicker,
                borrower=prof_maria,
                borrower_department=prof_maria.department or dept_ba,
                requested_start=now + timedelta(days=1, hours=1),
                requested_return=now + timedelta(days=1, hours=5),
                purpose=req1_purpose,
                status=AssetBorrowing.Status.PENDING,
                remarks='Requested with USB receiver and protective pouch.'
            )
            self.stdout.write(self.style.SUCCESS(
                f"  [1/5 PENDING] Seeded request #{b1.pk} for '{asset_clicker.asset_code}' by {prof_maria.full_name}"
            ))
        else:
            self.stdout.write("  [1/5 PENDING] Already exists.")

        # ----------------------------------------------------------------------
        # 2. APPROVED Future Reservation: PA Speaker requested by Prof. Garcia
        # ----------------------------------------------------------------------
        req2_purpose = 'Departmental Seminar on Modern Financial Accounting in CBA Conference Hall.'
        b2 = AssetBorrowing.objects.filter(purpose=req2_purpose).first()
        if not b2 and prof_garcia:
            b2 = AssetBorrowing.objects.create(
                asset=asset_speaker,
                borrower=prof_garcia,
                borrower_department=prof_garcia.department or dept_ba,
                requested_start=now + timedelta(days=3, hours=4),
                requested_return=now + timedelta(days=3, hours=8),
                purpose=req2_purpose,
                status=AssetBorrowing.Status.APPROVED,
                reviewed_by=admin,
                reviewed_at=now - timedelta(hours=12),
                remarks='Approved for conference hall academic seminar.'
            )
            self.stdout.write(self.style.SUCCESS(
                f"  [2/5 APPROVED] Seeded reservation #{b2.pk} for '{asset_speaker.asset_code}' by {prof_garcia.full_name}"
            ))
        else:
            self.stdout.write("  [2/5 APPROVED] Already exists.")

        # ----------------------------------------------------------------------
        # 3. CURRENTLY BORROWED (RELEASED): Projector on loan to Chair Santos
        # ----------------------------------------------------------------------
        req3_purpose = 'Special Executive Committee Meeting and Curriculum Review presentation.'
        b3 = AssetBorrowing.objects.filter(purpose=req3_purpose).first()
        if not b3 and chair_santos:
            b3 = AssetBorrowing.objects.create(
                asset=asset_projector,
                borrower=chair_santos,
                borrower_department=chair_santos.department or dept_acct,
                requested_start=now - timedelta(hours=3),
                requested_return=now + timedelta(hours=21),
                purpose=req3_purpose,
                status=AssetBorrowing.Status.RELEASED,
                reviewed_by=admin,
                reviewed_at=now - timedelta(hours=4),
                released_by=admin,
                released_at=now - timedelta(hours=3),
                condition_at_release=Asset.Condition.GOOD,
                remarks='Released with HDMI cable, power cord, and remote controller.'
            )
            # Update asset status to reflect actual release
            asset_projector.status = Asset.Status.BORROWED
            asset_projector.save(update_fields=['status'])
            self.stdout.write(self.style.SUCCESS(
                f"  [3/5 RELEASED] Seeded active loan #{b3.pk} for '{asset_projector.asset_code}' to {chair_santos.full_name}"
            ))
        else:
            self.stdout.write("  [3/5 RELEASED] Already exists.")

        # ----------------------------------------------------------------------
        # 4. RETURNED Historical Loan: 4K Webcam returned by Prof. Garcia
        # ----------------------------------------------------------------------
        req4_purpose = 'Regional Academic Accreditation Virtual Exhibit and live streaming.'
        b4 = AssetBorrowing.objects.filter(purpose=req4_purpose).first()
        if not b4 and prof_garcia:
            b4 = AssetBorrowing.objects.create(
                asset=asset_webcam,
                borrower=prof_garcia,
                borrower_department=prof_garcia.department or dept_ba,
                requested_start=now - timedelta(days=6),
                requested_return=now - timedelta(days=4),
                purpose=req4_purpose,
                status=AssetBorrowing.Status.RETURNED,
                reviewed_by=admin,
                reviewed_at=now - timedelta(days=7),
                released_by=admin,
                released_at=now - timedelta(days=6),
                condition_at_release=Asset.Condition.GOOD,
                returned_to=admin,
                returned_at=now - timedelta(days=4),
                condition_at_return=Asset.Condition.GOOD,
                return_remarks='Returned complete in original box; lens clean, operational test passed.',
                remarks='Clean return without issues.'
            )
            # Ensure asset is available
            asset_webcam.status = Asset.Status.AVAILABLE
            asset_webcam.save(update_fields=['status'])
            self.stdout.write(self.style.SUCCESS(
                f"  [4/5 RETURNED] Seeded historical loan #{b4.pk} for '{asset_webcam.asset_code}' by {prof_garcia.full_name}"
            ))
        else:
            self.stdout.write("  [4/5 RETURNED] Already exists.")

        # ----------------------------------------------------------------------
        # 5. REJECTED Request: Student summit workshop request
        # ----------------------------------------------------------------------
        req5_purpose = 'Student organization weekend leadership workshop in main auditorium.'
        b5 = AssetBorrowing.objects.filter(purpose=req5_purpose).first()
        if not b5 and prof_maria:
            b5 = AssetBorrowing.objects.create(
                asset=asset_speaker,
                borrower=prof_maria,
                borrower_department=prof_maria.department or dept_ba,
                requested_start=now + timedelta(days=7, hours=2),
                requested_return=now + timedelta(days=7, hours=6),
                purpose=req5_purpose,
                status=AssetBorrowing.Status.REJECTED,
                reviewed_by=admin,
                reviewed_at=now - timedelta(hours=6),
                rejection_reason='Equipment already scheduled for college accreditation audit presentation during this time window.',
                remarks='Advised borrower to coordinate with University Student Affairs for external sound equipment.'
            )
            self.stdout.write(self.style.SUCCESS(
                f"  [5/5 REJECTED] Seeded rejected request #{b5.pk} for '{asset_speaker.asset_code}' by {prof_maria.full_name}"
            ))
        else:
            self.stdout.write("  [5/5 REJECTED] Already exists.")

        self.stdout.write(self.style.SUCCESS('Successfully completed Phase 7 seed data generation.'))
