from django.core.management.base import BaseCommand, CommandError
from django.core.management import call_command
from django.utils import timezone
from datetime import timedelta

from apps.accounts.models import User
from apps.organizations.models import Department, Location, Employee
from apps.inventory.models import Asset, AssetVerification
from apps.audit.utils import log_action


class Command(BaseCommand):
    help = 'Seed realistic physical inventory verification records for CBA IMS Phase 6'

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
        self.stdout.write(self.style.NOTICE('Seeding CBA IMS Phase 6 QR Asset Tracking & Physical Verifications...'))

        # Ensure prerequisite data exists
        if not Department.objects.exists():
            call_command('seed_phase1')
        if not Asset.objects.exists():
            call_command('seed_phase2')

        admin = User.objects.filter(role=User.Role.ADMIN).first()
        if not admin:
            admin = User.objects.create_superuser('admin', 'admin@cba.edu', 'admin123')
            admin.role = User.Role.ADMIN
            admin.save()

        dept_ba = Department.objects.filter(code='BA').first()
        dept_acct = Department.objects.filter(code='ACCT').first()
        dept_it = Department.objects.filter(code='IT').first() or dept_ba

        loc_dean = Location.objects.filter(name__icontains="Dean's Office").first()
        loc_storage = Location.objects.filter(name__icontains='Storage').first()
        loc_acct_off = Location.objects.filter(name__icontains='Accountancy Department').first()
        loc_fac_rm = Location.objects.filter(name__icontains='Faculty Room').first()

        created_count = 0

        # ----------------------------------------------------------------------
        # 1. Exact Match (VERIFIED): First IT/Computer Asset
        # ----------------------------------------------------------------------
        laptop = Asset.objects.filter(category__code__in=['IT', 'COMP']).first() or Asset.objects.first()
        if laptop:
            v1_exists = AssetVerification.objects.filter(
                asset=laptop,
                remarks__icontains='Annual physical inventory audit: verified intact'
            ).exists()
            if not v1_exists:
                v1 = AssetVerification.objects.create(
                    asset=laptop,
                    verified_by=admin,
                    verified_at=timezone.now() - timedelta(days=5),
                    expected_department=laptop.department,
                    expected_location=laptop.current_location,
                    expected_condition=laptop.condition,
                    observed_department=laptop.department,
                    observed_location=laptop.current_location,
                    observed_condition=laptop.condition,
                    result=AssetVerification.VerificationResult.VERIFIED,
                    remarks='Annual physical inventory audit: verified intact, QR label scanned, serial number match.'
                )
                log_action(
                    user=admin,
                    action='ASSET_VERIFIED',
                    instance=laptop,
                    changes={
                        'result': v1.result,
                        'observed_department': str(v1.observed_department),
                        'observed_location': str(v1.observed_location),
                        'observed_condition': v1.observed_condition,
                    }
                )
                created_count += 1
                self.stdout.write(self.style.SUCCESS(f"  [+] Created VERIFIED record for {laptop.asset_code}"))

        # ----------------------------------------------------------------------
        # 2. Location Mismatch: Office Equipment / Printer
        # ----------------------------------------------------------------------
        printer = Asset.objects.filter(category__code='OE').first()
        if not printer and Asset.objects.count() > 1:
            printer = Asset.objects.exclude(pk=getattr(laptop, 'pk', None)).first()

        if printer and dept_acct:
            v2_exists = AssetVerification.objects.filter(
                asset=printer,
                remarks__icontains='Observed in Accountancy Office during audit walk'
            ).exists()
            if not v2_exists:
                obs_loc = loc_acct_off or loc_fac_rm or printer.current_location
                v2 = AssetVerification.objects.create(
                    asset=printer,
                    verified_by=admin,
                    verified_at=timezone.now() - timedelta(days=2),
                    expected_department=printer.department,
                    expected_location=printer.current_location,
                    expected_condition=printer.condition,
                    observed_department=dept_acct,
                    observed_location=obs_loc,
                    observed_condition=printer.condition,
                    result=AssetVerification.VerificationResult.LOCATION_MISMATCH,
                    remarks='Observed in Accountancy Office during audit walk. Canonical asset location remains unchanged. Formal transfer required.'
                )
                log_action(
                    user=admin,
                    action='ASSET_VERIFIED',
                    instance=printer,
                    changes={
                        'result': v2.result,
                        'observed_department': str(v2.observed_department),
                        'observed_location': str(v2.observed_location),
                        'observed_condition': v2.observed_condition,
                    }
                )
                created_count += 1
                self.stdout.write(self.style.WARNING(f"  [!] Created LOCATION_MISMATCH record for {printer.asset_code}"))

        # ----------------------------------------------------------------------
        # 3. Condition Mismatch: Furniture / AV Asset
        # ----------------------------------------------------------------------
        third_asset = Asset.objects.exclude(
            pk__in=[a.pk for a in [laptop, printer] if a]
        ).first()

        if third_asset:
            v3_exists = AssetVerification.objects.filter(
                asset=third_asset,
                remarks__icontains='Physical wear observed during annual check'
            ).exists()
            if not v3_exists:
                obs_cond = Asset.Condition.POOR if third_asset.condition != Asset.Condition.POOR else Asset.Condition.FAIR
                v3 = AssetVerification.objects.create(
                    asset=third_asset,
                    verified_by=admin,
                    verified_at=timezone.now() - timedelta(days=1),
                    expected_department=third_asset.department,
                    expected_location=third_asset.current_location,
                    expected_condition=third_asset.condition,
                    observed_department=third_asset.department,
                    observed_location=third_asset.current_location,
                    observed_condition=obs_cond,
                    result=AssetVerification.VerificationResult.CONDITION_MISMATCH,
                    remarks='Physical wear observed during annual check; condition degraded from database record.'
                )
                log_action(
                    user=admin,
                    action='ASSET_VERIFIED',
                    instance=third_asset,
                    changes={
                        'result': v3.result,
                        'observed_department': str(v3.observed_department),
                        'observed_location': str(v3.observed_location),
                        'observed_condition': v3.observed_condition,
                    }
                )
                created_count += 1
                self.stdout.write(self.style.WARNING(f"  [!] Created CONDITION_MISMATCH record for {third_asset.asset_code}"))

        self.stdout.write(self.style.SUCCESS(
            f"Successfully finished Phase 6 seeding: {created_count} verification records created."
        ))
