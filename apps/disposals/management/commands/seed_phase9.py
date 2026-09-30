from decimal import Decimal
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from datetime import timedelta, date
from django.conf import settings

from apps.accounts.models import User
from apps.organizations.models import Department, Location
from apps.inventory.models import Asset, AssetCategory, Brand
from apps.maintenance.models import AssetMaintenance
from apps.disposals.models import AssetDisposal


class Command(BaseCommand):
    help = 'Seeds Phase 9 test scenarios for Asset Disposal, Retirement, and Archiving (idempotent)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--force-demo-data',
            action='store_true',
            help='Required to run seed commands outside of DEBUG mode. THIS CREATES DEMO ACCOUNTS WITH KNOWN PASSWORDS.',
        )

    def handle(self, *args, **options):
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

        self.stdout.write("Starting Phase 9 Disposal Seed Data...")

        # 1. Fetch prerequisite users
        admin_user = User.objects.filter(role=User.Role.ADMIN).first()
        if not admin_user:
            admin_user = User.objects.create_superuser(
                username='admin',
                email='admin@cba.edu.ph',
                first_name='System',
                last_name='Administrator',
                role=User.Role.ADMIN
            )
            admin_user.set_password('admin123')
            admin_user.save()

        dean_user = User.objects.filter(role=User.Role.DEAN).first()

        # Prerequisite category, department, location
        cat_it = AssetCategory.objects.filter(code='IT').first()
        if not cat_it:
            cat_it = AssetCategory.objects.create(name='Information Technology', code='IT')

        cat_oe = AssetCategory.objects.filter(code='OE').first()
        if not cat_oe:
            cat_oe = AssetCategory.objects.create(name='Office Equipment', code='OE')

        dept_cba = Department.objects.first()
        if not dept_cba:
            dept_cba = Department.objects.create(name='Business Administration', code='BA')

        loc_storage = Location.objects.filter(name__icontains='Storage').first()
        if not loc_storage:
            loc_storage = Location.objects.create(name='CBA Central Storage', department=dept_cba)

        brand_dell = Brand.objects.filter(name__icontains='Dell').first()
        if not brand_dell:
            brand_dell = Brand.objects.create(name='Dell')

        brand_epson = Brand.objects.filter(name__icontains='Epson').first()
        if not brand_epson:
            brand_epson = Brand.objects.create(name='Epson')

        now = timezone.now()

        # =========================================================================
        # SCENARIO 1: PENDING Disposal (Originating from Phase 8 FOR_REPLACEMENT)
        # =========================================================================
        asset_1, created = Asset.objects.get_or_create(
            property_number='NORSU-CBA-DSP-001',
            defaults={
                'item_name': 'Dell OptiPlex 3050 MT (Severe Motherboard Corrosion)',
                'category': cat_it,
                'brand': brand_dell,
                'model': 'OptiPlex 3050',
                'serial_number': 'DSP-SN-3050-01',
                'acquisition_cost': Decimal('38500.00'),
                'acquisition_date': date(2019, 3, 15),
                'department': dept_cba,
                'current_location': loc_storage,
                'condition': Asset.Condition.UNSERVICEABLE,
                'status': Asset.Status.DAMAGED,
                'created_by': admin_user,
            }
        )
        if not created and asset_1.status == Asset.Status.AVAILABLE:
            asset_1.status = Asset.Status.DAMAGED
            asset_1.condition = Asset.Condition.UNSERVICEABLE
            asset_1.save(update_fields=['status', 'condition'])

        maint_1, _ = AssetMaintenance.objects.get_or_create(
            case_number='MNT-2026-DSP01',
            defaults={
                'asset': asset_1,
                'issue_title': 'Total motherboard short-circuit and component burn',
                'issue_description': 'Internal power surge melted capacitors and charred the mainboard during storm.',
                'reported_by': admin_user,
                'reported_at': now - timedelta(days=12),
                'status': AssetMaintenance.Status.FOR_REPLACEMENT,
                'severity': AssetMaintenance.Severity.CRITICAL,
                'diagnosis': 'Component-level thermal destruction. Replacement motherboard cost exceeds current depreciated value.',
                'final_condition': Asset.Condition.UNSERVICEABLE,
                'repair_completed_at': now - timedelta(days=10),
                'remarks': 'Recommended for condemnation and formal disposal.',
            }
        )

        dsp_1, dsp_1_created = AssetDisposal.objects.get_or_create(
            disposal_number='DSP-2026-00001',
            defaults={
                'asset': asset_1,
                'requested_by': admin_user,
                'requested_at': now - timedelta(days=5),
                'reason': 'Motherboard destroyed by electrical surge. Evaluated beyond economical repair under maintenance case MNT-2026-DSP01.',
                'recommended_by': admin_user,
                'maintenance_reference': maint_1,
                'condition_at_disposal': Asset.Condition.UNSERVICEABLE,
                'status': AssetDisposal.Status.PENDING,
            }
        )
        self.stdout.write(f"  [Scenario 1] Pending Disposal: {dsp_1.disposal_number} ({asset_1.asset_code})")

        # =========================================================================
        # SCENARIO 2: APPROVED Disposal (Awaiting Physical Execution)
        # =========================================================================
        asset_2, created = Asset.objects.get_or_create(
            property_number='NORSU-CBA-DSP-002',
            defaults={
                'item_name': 'Epson EB-X41 Multimedia Projector (Optical Engine Degradation)',
                'category': cat_oe,
                'brand': brand_epson,
                'model': 'EB-X41',
                'serial_number': 'DSP-SN-X41-02',
                'acquisition_cost': Decimal('28900.00'),
                'acquisition_date': date(2018, 7, 20),
                'department': dept_cba,
                'current_location': loc_storage,
                'condition': Asset.Condition.UNSERVICEABLE,
                'status': Asset.Status.DAMAGED,
                'created_by': admin_user,
            }
        )
        if not created and asset_2.status == Asset.Status.AVAILABLE:
            asset_2.status = Asset.Status.DAMAGED
            asset_2.condition = Asset.Condition.UNSERVICEABLE
            asset_2.save(update_fields=['status', 'condition'])

        dsp_2, _ = AssetDisposal.objects.get_or_create(
            disposal_number='DSP-2026-00002',
            defaults={
                'asset': asset_2,
                'requested_by': admin_user,
                'requested_at': now - timedelta(days=14),
                'reason': 'Optical prism burnt out, lamp house deformed. Outdated analog resolution.',
                'recommended_by': admin_user,
                'condition_at_disposal': Asset.Condition.UNSERVICEABLE,
                'status': AssetDisposal.Status.APPROVED,
                'reviewed_by': admin_user,
                'reviewed_at': now - timedelta(days=10),
                'review_remarks': 'Approved for physical scrapping and electronic component recycling.',
            }
        )
        self.stdout.write(f"  [Scenario 2] Approved Disposal: {dsp_2.disposal_number} ({asset_2.asset_code})")

        # =========================================================================
        # SCENARIO 3: COMPLETED Disposal (Scrap / Recycled -> Asset.status = DISPOSED)
        # =========================================================================
        asset_3, created = Asset.objects.get_or_create(
            property_number='NORSU-CBA-DSP-003',
            defaults={
                'item_name': 'HP LaserJet Pro M402dn (Irreparable Gear Train & Drum)',
                'category': cat_oe,
                'model': 'M402dn',
                'serial_number': 'DSP-SN-M402-03',
                'acquisition_cost': Decimal('19500.00'),
                'acquisition_date': date(2017, 1, 10),
                'department': dept_cba,
                'current_location': loc_storage,
                'condition': Asset.Condition.UNSERVICEABLE,
                'status': Asset.Status.DISPOSED,
                'created_by': admin_user,
            }
        )
        # Ensure asset is DISPOSED
        if asset_3.status != Asset.Status.DISPOSED:
            asset_3.status = Asset.Status.DISPOSED
            asset_3.save(update_fields=['status'])

        dsp_3, _ = AssetDisposal.objects.get_or_create(
            disposal_number='DSP-2026-00003',
            defaults={
                'asset': asset_3,
                'requested_by': admin_user,
                'requested_at': now - timedelta(days=30),
                'reason': 'Gear transmission completely broken, fuser unit seized. Unit obsolete.',
                'recommended_by': admin_user,
                'condition_at_disposal': Asset.Condition.UNSERVICEABLE,
                'status': AssetDisposal.Status.COMPLETED,
                'reviewed_by': admin_user,
                'reviewed_at': now - timedelta(days=25),
                'review_remarks': 'Disposal approved via accredited e-waste scrap recycler.',
                'disposal_method': AssetDisposal.DisposalMethod.SCRAP,
                'disposal_date': (now - timedelta(days=20)).date(),
                'processed_by': admin_user,
                'recipient_or_destination': 'Negros Oriental Certified E-Waste Recycler Inc.',
                'reference_number': 'SCRAP-2026-NORSU-041',
                'proceeds_amount': Decimal('450.00'),
                'remarks': 'Metal chassis and power supply salvaged for electronic scrap.',
                'completed_at': now - timedelta(days=20),
            }
        )
        self.stdout.write(f"  [Scenario 3] Completed Disposal: {dsp_3.disposal_number} ({asset_3.asset_code} -> DISPOSED)")

        # =========================================================================
        # SCENARIO 4: REJECTED Disposal (Asset remains DAMAGED / Active)
        # =========================================================================
        asset_4, created = Asset.objects.get_or_create(
            property_number='NORSU-CBA-DSP-004',
            defaults={
                'item_name': 'Lenovo ThinkPad T480 (Cracked Screen)',
                'category': cat_it,
                'model': 'T480',
                'serial_number': 'DSP-SN-T480-04',
                'acquisition_cost': Decimal('52000.00'),
                'acquisition_date': date(2021, 5, 20),
                'department': dept_cba,
                'current_location': loc_storage,
                'condition': Asset.Condition.POOR,
                'status': Asset.Status.DAMAGED,
                'created_by': admin_user,
            }
        )

        dsp_4, _ = AssetDisposal.objects.get_or_create(
            disposal_number='DSP-2026-00004',
            defaults={
                'asset': asset_4,
                'requested_by': admin_user,
                'requested_at': now - timedelta(days=18),
                'reason': 'Laptop LCD panel cracked. Requester suggested disposal.',
                'recommended_by': admin_user,
                'condition_at_disposal': Asset.Condition.POOR,
                'status': AssetDisposal.Status.REJECTED,
                'reviewed_by': admin_user,
                'reviewed_at': now - timedelta(days=15),
                'review_remarks': 'Rejected: Core i7 8th Gen motherboard and SSD are still high value. Recommend LCD panel replacement rather than retirement.',
            }
        )
        self.stdout.write(f"  [Scenario 4] Rejected Disposal: {dsp_4.disposal_number} ({asset_4.asset_code})")

        # =========================================================================
        # SCENARIO 5: CANCELLED Disposal (Administrative Withdrawal)
        # =========================================================================
        asset_5, created = Asset.objects.get_or_create(
            property_number='NORSU-CBA-DSP-005',
            defaults={
                'item_name': 'Sony VPL-DX221 Classroom Projector',
                'category': cat_oe,
                'model': 'VPL-DX221',
                'serial_number': 'DSP-SN-DX221-05',
                'acquisition_cost': Decimal('24000.00'),
                'acquisition_date': date(2019, 10, 5),
                'department': dept_cba,
                'current_location': loc_storage,
                'condition': Asset.Condition.FAIR,
                'status': Asset.Status.AVAILABLE,
                'created_by': admin_user,
            }
        )

        dsp_5, _ = AssetDisposal.objects.get_or_create(
            disposal_number='DSP-2026-00005',
            defaults={
                'asset': asset_5,
                'requested_by': admin_user,
                'requested_at': now - timedelta(days=8),
                'reason': 'Prematurely requested for disposal due to blown thermal fuse.',
                'recommended_by': admin_user,
                'condition_at_disposal': Asset.Condition.FAIR,
                'status': AssetDisposal.Status.CANCELLED,
                'reviewed_by': admin_user,
                'reviewed_at': now - timedelta(days=6),
                'review_remarks': 'Cancellation: In-house technician replaced fuse successfully; unit tested fully operational.',
            }
        )
        self.stdout.write(f"  [Scenario 5] Cancelled Disposal: {dsp_5.disposal_number} ({asset_5.asset_code})")

        self.stdout.write(self.style.SUCCESS("Successfully seeded Phase 9 disposal scenarios!"))
