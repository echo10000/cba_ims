from django.core.management.base import BaseCommand, CommandError
from django.core.management import call_command
from django.utils import timezone
from datetime import date, timedelta

from apps.accounts.models import User
from apps.organizations.models import Department, Location, Employee
from apps.inventory.models import Asset
from apps.transfers.models import AssetTransfer
from apps.transfers import services


class Command(BaseCommand):
    help = 'Seed realistic asset transfer and movement history for CBA IMS Phase 4'

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
        self.stdout.write(self.style.NOTICE('Seeding CBA IMS Phase 4 Asset Transfers & Movement History...'))

        # Ensure Phase 1, Phase 2, and Phase 3 data exist
        if not Department.objects.exists():
            call_command('seed_phase1')
        if not Asset.objects.exists():
            call_command('seed_phase2')
        if not Employee.objects.filter(assignments__isnull=False).exists():
            call_command('seed_phase3')

        admin = User.objects.filter(role=User.Role.ADMIN).first()
        if not admin:
            admin = User.objects.create_superuser('admin', 'admin@cba.edu', 'admin123')
            admin.role = User.Role.ADMIN
            admin.save()

        dept_ba = Department.objects.filter(code='BA').first()
        dept_acct = Department.objects.filter(code='ACCT').first()

        loc_storage = Location.objects.filter(name__icontains='Storage').first()
        loc_dean = Location.objects.filter(name__icontains="Dean's Office").first()
        loc_acct_off = Location.objects.filter(name__icontains='Accountancy Department').first()
        loc_fac_rm = Location.objects.filter(name__icontains='Faculty Room').first()
        loc_lab = Location.objects.filter(name__icontains='Laboratory').first()

        # 1. Historical Completed Movement 1: Storage -> Dean's Office
        printer = Asset.objects.filter(category__code='OE').first()
        if printer and loc_storage and loc_dean:
            transfer1_exists = AssetTransfer.objects.filter(
                asset=printer,
                reason='Initial office deployment for college administration.'
            ).exists()

            if not transfer1_exists:
                # Direct historical creation preserving record
                t1 = AssetTransfer.objects.create(
                    asset=printer,
                    from_department=dept_ba,
                    from_location=loc_storage,
                    to_department=dept_ba,
                    to_location=loc_dean,
                    transfer_date=timezone.now().date() - timedelta(days=60),
                    reason='Initial office deployment for college administration.',
                    remarks='Dispatched with complete cables, installation CD, and cartridge pack.',
                    requested_by=admin,
                    approved_by=admin,
                    processed_by=admin,
                    status=AssetTransfer.Status.COMPLETED,
                    approved_at=timezone.now() - timedelta(days=59),
                    completed_at=timezone.now() - timedelta(days=58),
                )
                self.stdout.write(self.style.SUCCESS(
                    f"  [History] Seeded completed transfer for '{printer.asset_code}' ({t1.from_location.name} -> {t1.to_location.name})"
                ))
            else:
                self.stdout.write("  Transfer 1 already exists.")

        # 2. Historical Completed Movement 2: Dean's Office -> Accountancy Office
        laptop = Asset.objects.filter(category__code='IT', assignments__status='ACTIVE').first()
        if laptop and loc_dean and loc_acct_off:
            transfer2_exists = AssetTransfer.objects.filter(
                asset=laptop,
                reason='Departmental equipment redistribution for instructional computing.'
            ).exists()

            if not transfer2_exists:
                t2 = AssetTransfer.objects.create(
                    asset=laptop,
                    from_department=dept_ba,
                    from_location=loc_dean,
                    to_department=dept_acct,
                    to_location=loc_acct_off,
                    transfer_date=timezone.now().date() - timedelta(days=30),
                    reason='Departmental equipment redistribution for instructional computing.',
                    remarks='Transferred by courier; verified physical condition good upon turnover.',
                    requested_by=admin,
                    approved_by=admin,
                    processed_by=admin,
                    status=AssetTransfer.Status.COMPLETED,
                    approved_at=timezone.now() - timedelta(days=29),
                    completed_at=timezone.now() - timedelta(days=28),
                )
                self.stdout.write(self.style.SUCCESS(
                    f"  [History] Seeded completed transfer for '{laptop.asset_code}' ({t2.from_location.name} -> {t2.to_location.name})"
                ))
            else:
                self.stdout.write("  Transfer 2 already exists.")

        # 3. Active Pending Transfer Request: Lab -> Faculty Room
        available_asset = Asset.objects.filter(
            status=Asset.Status.AVAILABLE,
            transfers__status__in=[AssetTransfer.Status.PENDING, AssetTransfer.Status.APPROVED]
        ).first()

        if not available_asset:
            target_asset = Asset.objects.filter(
                status=Asset.Status.AVAILABLE
            ).exclude(
                current_location=loc_fac_rm
            ).first()

            if target_asset and loc_fac_rm and dept_ba:
                try:
                    t3 = services.request_transfer(
                        asset=target_asset,
                        to_department=dept_ba,
                        to_location=loc_fac_rm,
                        requested_by=admin,
                        transfer_date=timezone.now().date(),
                        reason='Faculty workstation hardware upgrade.',
                        remarks='Pending physical room preparation in Faculty Room 205.'
                    )
                    self.stdout.write(self.style.SUCCESS(
                        f"  [Pending] Created active transfer request for '{target_asset.asset_code}' to {loc_fac_rm.name}"
                    ))
                except Exception as e:
                    self.stdout.write(f"  Transfer request skipped: {e}")
        else:
            self.stdout.write("  Active pending transfer already exists.")

        self.stdout.write(self.style.SUCCESS('Successfully seeded Phase 4 Asset Transfer data!'))
