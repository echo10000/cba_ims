from datetime import timedelta
from decimal import Decimal
from django.core.management.base import BaseCommand, CommandError
from django.core.management import call_command
from django.utils import timezone
from django.conf import settings

from apps.accounts.models import User
from apps.organizations.models import Department, Location, Employee
from apps.inventory.models import Asset, AssetCategory, Brand
from apps.maintenance.models import AssetMaintenance
from apps.maintenance import services


class Command(BaseCommand):
    help = 'Seed realistic equipment maintenance, defect reports, and repair records for CBA IMS Phase 8'

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

        self.stdout.write(self.style.NOTICE('Seeding CBA IMS Phase 8 Asset Maintenance & Repair Records...'))

        # Ensure Phase 1, Phase 2, Phase 3, and Phase 7 data exist
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

        faculty = User.objects.filter(role=User.Role.FACULTY).first() or admin
        dept_ba = Department.objects.filter(code='BA').first() or Department.objects.first()
        loc_storage = Location.objects.filter(name__icontains='Storage').first() or Location.objects.first()

        cat_it = AssetCategory.objects.filter(code='IT').first()
        if not cat_it:
            cat_it = AssetCategory.objects.create(
                code='IT',
                name='IT Equipment & Workstations',
                description='Desktops, laptops, monitors, network gear, and printers.'
            )

        cat_fur = AssetCategory.objects.filter(code='FUR').first()
        if not cat_fur:
            cat_fur = AssetCategory.objects.create(
                code='FUR',
                name='Office & Classroom Furniture',
                description='Chairs, desks, conference tables, and filing cabinets.'
            )

        brand_hp = Brand.objects.filter(name__icontains='HP').first()
        if not brand_hp:
            brand_hp = Brand.objects.create(name='HP')

        brand_dell = Brand.objects.filter(name__icontains='Dell').first()
        if not brand_dell:
            brand_dell = Brand.objects.create(name='Dell')

        brand_epson = Brand.objects.filter(name__icontains='Epson').first()
        if not brand_epson:
            brand_epson = Brand.objects.create(name='Epson')

        def get_or_create_asset(item_name, cat, brand, model, prop_num, cost, condition, status, desc):
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
                    condition=condition,
                    status=status,
                    acquisition_date=timezone.now().date() - timedelta(days=200),
                    acquisition_cost=Decimal(str(cost)),
                    supplier='CBA Institutional Suppliers',
                    description=desc,
                    remarks='Designated equipment item.',
                    created_by=admin
                )
            return asset

        # Assets for seeding maintenance cases
        asset_printer = get_or_create_asset(
            'HP LaserJet Pro MFP 4103fdw',
            cat_it, brand_hp, '4103fdw', 'NORSU-CBA-2026-MNT001',
            28500.00, Asset.Condition.FAIR, Asset.Status.AVAILABLE,
            'Multifunction monochrome network laser printer with duplex scanning.'
        )

        asset_laptop = get_or_create_asset(
            'Dell Latitude 5430 Business Laptop',
            cat_it, brand_dell, 'Latitude 5430', 'NORSU-CBA-2026-MNT002',
            54990.00, Asset.Condition.FAIR, Asset.Status.AVAILABLE,
            '14-inch Intel Core i5 laptop with 16GB RAM and 512GB SSD.'
        )

        asset_projector = get_or_create_asset(
            'Epson PowerLite L520U Laser Projector',
            cat_it, brand_epson, 'L520U', 'NORSU-CBA-2026-MNT003',
            98000.00, Asset.Condition.POOR, Asset.Status.AVAILABLE,
            '5,200 lumens high-brightness WUXGA laser multimedia projector.'
        )

        asset_monitor = get_or_create_asset(
            'Dell UltraSharp U2722D 27-inch QHD Monitor',
            cat_it, brand_dell, 'U2722D', 'NORSU-CBA-2026-MNT004',
            23500.00, Asset.Condition.GOOD, Asset.Status.AVAILABLE,
            '27-inch IPS panel QHD professional color-accurate desktop monitor.'
        )

        asset_chair = get_or_create_asset(
            'Ergonomic High-Back Executive Mesh Chair',
            cat_fur, None, 'ExecPro-X', 'NORSU-CBA-2026-MNT005',
            14500.00, Asset.Condition.POOR, Asset.Status.AVAILABLE,
            'High-back executive task chair with synchronous tilt mechanism.'
        )

        now = timezone.now()

        prof_maria = Employee.objects.filter(employee_id='EMP-FAC-001').first()
        faculty_user = (prof_maria.user if (prof_maria and prof_maria.user) else faculty) or admin

        # Assign laptop to prof_maria if not already assigned
        if prof_maria and not asset_laptop.assignments.filter(status='ACTIVE').exists():
            from apps.assignments.models import AssetAssignment
            # Mark laptop assigned to prof_maria
            AssetAssignment.objects.create(
                asset=asset_laptop,
                employee=prof_maria,
                assigned_by=admin,
                assigned_date=now.date() - timedelta(days=60),
                expected_return_date=now.date() + timedelta(days=120),
                purpose='Faculty instructional computing and grading',
                condition_at_assignment=Asset.Condition.GOOD,
                status=AssetAssignment.Status.ACTIVE
            )
            asset_laptop.status = Asset.Status.ASSIGNED
            asset_laptop.save(update_fields=['status'])

        # Case 1: REPORTED
        case1 = AssetMaintenance.objects.filter(asset=asset_printer, issue_title__icontains='Paper Jam').first()
        if not case1:
            case1 = services.report_issue(
                asset=asset_printer,
                reported_by=admin,
                issue_title='Recurring Paper Jam & Roller Feed Defect',
                issue_description='Main paper feed tray 2 repeatedly jams during multi-page print jobs. Paper is creased and roller appears worn.',
                source=AssetMaintenance.ReportSource.MANUAL_REPORT,
                remarks='Temporary workaround: single sheet feed via bypass tray 1.'
            )
            # Adjust reported date to 3 days ago
            AssetMaintenance.objects.filter(pk=case1.pk).update(reported_at=now - timedelta(days=3))
            self.stdout.write(self.style.SUCCESS(f'  Created Case 1 (REPORTED): {case1.case_number}'))
        else:
            self.stdout.write(f'  Case 1 already exists: {case1.case_number}')

        # Case 2: ASSESSED (Reported by faculty member with active assignment)
        case2 = AssetMaintenance.objects.filter(asset=asset_laptop, issue_title__icontains='Keyboard').first()
        if not case2:
            case2 = services.report_issue(
                asset=asset_laptop,
                reported_by=faculty_user,
                issue_title='Keyboard Liquid Spill & Sticky Key Syndrome',
                issue_description='Keys E, R, and Left Shift fail to register reliably following coffee splash on faculty desk.',
                source=AssetMaintenance.ReportSource.MANUAL_REPORT
            )
            case2 = services.assess_issue(
                maintenance=case2,
                assessed_by=admin,
                severity=AssetMaintenance.Severity.HIGH,
                diagnosis='Membrane liquid ingress detected on upper right quadrant. Motherboard inspection clean; isolated to top-case keyboard assembly.',
                recommended_action='Replace OEM top-case keyboard and trackpad palm-rest assembly.',
                remarks='Procurement request initiated for Dell Latitude 5430 replacement keyboard module.'
            )
            AssetMaintenance.objects.filter(pk=case2.pk).update(
                reported_at=now - timedelta(days=5),
                assessed_at=now - timedelta(days=4)
            )
            self.stdout.write(self.style.SUCCESS(f'  Created Case 2 (ASSESSED): {case2.case_number}'))
        else:
            self.stdout.write(f'  Case 2 already exists: {case2.case_number}')

        # Case 3: IN_REPAIR
        case3 = AssetMaintenance.objects.filter(asset=asset_projector, issue_title__icontains='Laser Optical').first()
        if not case3:
            case3 = services.report_issue(
                asset=asset_projector,
                reported_by=admin,
                issue_title='Laser Optical Engine Overheating & Shutdown',
                issue_description='Projector abruptly powers down with red status LED indicator after 15 minutes of lecture hall presentation.',
                source=AssetMaintenance.ReportSource.MANUAL_REPORT
            )
            case3 = services.assess_issue(
                maintenance=case3,
                assessed_by=admin,
                severity=AssetMaintenance.Severity.CRITICAL,
                diagnosis='Thermal cooling exhaust fan #2 seized due to dust accumulation. Optical diode laser sensor triggering emergency thermal cut-off.',
                recommended_action='Dispatch to certified Epson warranty partner for intake blower cleaning and brushless cooling fan replacement.'
            )
            case3 = services.start_repair(
                maintenance=case3,
                user=admin,
                service_provider='Epson Certified Regional Service Center (Dumaguete)',
                technician='Engr. Arthur Macasling',
                repair_started_at=now - timedelta(days=2),
                remarks='Under warranty repair job order #EP-2026-9912.'
            )
            AssetMaintenance.objects.filter(pk=case3.pk).update(
                reported_at=now - timedelta(days=7),
                assessed_at=now - timedelta(days=6),
                repair_started_at=now - timedelta(days=2)
            )
            self.stdout.write(self.style.SUCCESS(f'  Created Case 3 (IN_REPAIR): {case3.case_number}'))
        else:
            self.stdout.write(f'  Case 3 already exists: {case3.case_number}')

        # Case 4: COMPLETED
        case4 = AssetMaintenance.objects.filter(asset=asset_monitor, issue_title__icontains='Display Flicker').first()
        if not case4:
            case4 = services.report_issue(
                asset=asset_monitor,
                reported_by=admin,
                issue_title='Display Flicker & Power Supply Board Failure',
                issue_description='Monitor screen flickers periodically and backlight shuts off intermittently after warming up.',
                source=AssetMaintenance.ReportSource.MANUAL_REPORT
            )
            case4 = services.assess_issue(
                maintenance=case4,
                assessed_by=admin,
                severity=AssetMaintenance.Severity.MEDIUM,
                diagnosis='Swollen filter capacitors on internal AC/DC power supply board causing voltage fluctuations.',
                recommended_action='In-house power board recap and thermal stress testing.'
            )
            case4 = services.start_repair(
                maintenance=case4,
                user=admin,
                service_provider='CBA Physical Plant & Electronics Lab',
                technician='Technician Mark Villanueva',
                repair_started_at=now - timedelta(days=10)
            )
            case4 = services.complete_repair(
                maintenance=case4,
                user=admin,
                final_condition=Asset.Condition.GOOD,
                action_taken='Desoldered three bulging 1000uF 25V capacitors; installed Nichicon high-temp low-ESR capacitors. 48-hour burn-in bench test passed.',
                parts_replaced='3x Nichicon 1000uF 25V Electrolytic Capacitors (Part #UHM1E102MPD)',
                repair_cost=Decimal('450.00'),
                repair_completed_at=now - timedelta(days=1),
                remarks='Screen stability verified at full 1440p 75Hz resolution. Cleared for departmental deployment.'
            )
            AssetMaintenance.objects.filter(pk=case4.pk).update(
                reported_at=now - timedelta(days=14),
                assessed_at=now - timedelta(days=12),
                repair_started_at=now - timedelta(days=10),
                repair_completed_at=now - timedelta(days=1)
            )
            self.stdout.write(self.style.SUCCESS(f'  Created Case 4 (COMPLETED): {case4.case_number}'))
        else:
            self.stdout.write(f'  Case 4 already exists: {case4.case_number}')

        # Case 5: FOR_REPLACEMENT
        case5 = AssetMaintenance.objects.filter(asset=asset_chair, issue_title__icontains='Hydraulic Cylinder').first()
        if not case5:
            case5 = services.report_issue(
                asset=asset_chair,
                reported_by=admin,
                issue_title='Hydraulic Cylinder Failure & Sheared Base Bracket',
                issue_description='Chair suddenly sinks to lowest elevation and wobbles dangerously. Underneath steel mounting plate is cracked through.',
                source=AssetMaintenance.ReportSource.MANUAL_REPORT
            )
            case5 = services.assess_issue(
                maintenance=case5,
                assessed_by=admin,
                severity=AssetMaintenance.Severity.HIGH,
                diagnosis='Catastrophic mechanical fatigue on stamped steel tilt mechanism; pneumatic gas cylinder seal ruptured. Unsafe for human occupancy.',
                recommended_action='Repair cost exceeds residual book value. Deemed beyond economical repair.'
            )
            case5 = services.mark_for_replacement(
                maintenance=case5,
                user=admin,
                remarks='Recommended for replacement. Retained safely in building storage pending formal Phase 9 disposal evaluation.'
            )
            AssetMaintenance.objects.filter(pk=case5.pk).update(
                reported_at=now - timedelta(days=20),
                assessed_at=now - timedelta(days=18)
            )
            self.stdout.write(self.style.SUCCESS(f'  Created Case 5 (FOR_REPLACEMENT): {case5.case_number}'))
        else:
            self.stdout.write(f'  Case 5 already exists: {case5.case_number}')

        self.stdout.write(self.style.SUCCESS('Phase 8 Maintenance & Repair seeding completed successfully.'))
