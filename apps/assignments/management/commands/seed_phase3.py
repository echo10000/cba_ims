from django.core.management.base import BaseCommand, CommandError
from django.core.management import call_command
from datetime import date, timedelta
from apps.accounts.models import User
from apps.organizations.models import Employee
from apps.inventory.models import Asset
from apps.assignments.models import AssetAssignment
from apps.assignments import services


class Command(BaseCommand):
    help = 'Seed realistic sample asset assignments and turnover history for CBA IMS Phase 3'

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
        self.stdout.write(self.style.NOTICE('Seeding CBA IMS Phase 3 Assignments & Accountability...'))

        # Ensure Phase 1 and Phase 2 data exists
        if not Employee.objects.exists():
            self.stdout.write('  Running seed_phase1...')
            call_command('seed_phase1')
        if not Asset.objects.exists():
            self.stdout.write('  Running seed_phase2...')
            call_command('seed_phase2')

        admin = User.objects.filter(role=User.Role.ADMIN).first()
        if not admin:
            admin = User.objects.create_superuser('admin', 'admin@cba.edu', 'admin123')
            admin.role = User.Role.ADMIN
            admin.save()

        prof_maria = Employee.objects.filter(employee_id='EMP-FAC-001').first()
        chair_santos = Employee.objects.filter(employee_id='EMP-ACCT-001').first()
        prof_garcia = Employee.objects.filter(employee_id='EMP-FAC-002').first()

        # 1. Active Assignment: Laptop assigned to prof_maria (Faculty)
        if prof_maria and not prof_maria.assignments.filter(status=AssetAssignment.Status.ACTIVE).exists():
            laptop = Asset.objects.filter(
                category__code='IT',
                status=Asset.Status.AVAILABLE
            ).first()
            if laptop:
                assign1 = services.assign_asset(
                    asset=laptop,
                    employee=prof_maria,
                    assigned_by=admin,
                    assigned_date=date.today() - timedelta(days=45),
                    expected_return_date=date.today() + timedelta(days=120),
                    purpose='Classroom Instruction and Academic Research',
                    remarks='Issued with OEM power adapter, laptop sleeve, and wireless mouse.',
                )
                self.stdout.write(self.style.SUCCESS(
                    f"  [Active] Assigned '{laptop.asset_code}' ({laptop.item_name}) to {prof_maria.full_name}"
                ))
        else:
            self.stdout.write("  Faculty member already has active assignment.")

        # 2. Active Assignment: Printer or Office Equipment to chair_santos (Dept Chair)
        if chair_santos and not chair_santos.assignments.filter(status=AssetAssignment.Status.ACTIVE).exists():
            printer = Asset.objects.filter(
                category__code='OE',
                status=Asset.Status.AVAILABLE
            ).first()
            if printer:
                assign2 = services.assign_asset(
                    asset=printer,
                    employee=chair_santos,
                    assigned_by=admin,
                    assigned_date=date.today() - timedelta(days=30),
                    expected_return_date=None,  # Indefinite tenure assignment
                    purpose='Department Office Documentation and Printing Operations',
                    remarks='Set up in Accountancy Department Office with USB cable and extra ink pack.',
                )
                self.stdout.write(self.style.SUCCESS(
                    f"  [Active] Assigned '{printer.asset_code}' ({printer.item_name}) to {chair_santos.full_name}"
                ))
        else:
            self.stdout.write("  Department chair already has active assignment.")

        # 3. Completed Historical Turnover: An asset returned previously by prof_garcia
        if prof_garcia and not AssetAssignment.objects.filter(employee=prof_garcia, status=AssetAssignment.Status.RETURNED).exists():
            avail_asset = Asset.objects.filter(status=Asset.Status.AVAILABLE).exclude(
                assignments__isnull=False
            ).first()
            if avail_asset:
                AssetAssignment.objects.create(
                    asset=avail_asset,
                    employee=prof_garcia,
                    assigned_date=date(2025, 8, 15),
                    expected_return_date=date(2025, 12, 15),
                    returned_date=date(2025, 12, 18),
                    purpose='Semester Projector & Teaching Equipment Allocation',
                    condition_at_assignment=Asset.Condition.GOOD,
                    condition_at_return=Asset.Condition.GOOD,
                    assigned_by=admin,
                    returned_by=admin,
                    status=AssetAssignment.Status.RETURNED,
                    remarks='Returned in good working condition with remote control and VGA/HDMI cables upon semester conclusion.',
                )
                self.stdout.write(self.style.SUCCESS(
                    f"  [History] Created completed turnover record for '{avail_asset.asset_code}' by {prof_garcia.full_name}"
                ))
        else:
            self.stdout.write("  Historical turnover record already exists.")

        self.stdout.write(self.style.SUCCESS('Successfully seeded Phase 3 Assignment & Accountability data!'))
