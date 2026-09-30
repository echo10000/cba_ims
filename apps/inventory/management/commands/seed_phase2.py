from django.core.management.base import BaseCommand, CommandError
from decimal import Decimal
from datetime import date
from apps.accounts.models import User
from apps.organizations.models import Department, Location
from apps.inventory.models import AssetCategory, Brand, Asset
from apps.audit.utils import log_action


class Command(BaseCommand):
    help = 'Seed realistic durable assets for CBA IMS Phase 2'

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
        self.stdout.write(self.style.NOTICE('Seeding CBA IMS Phase 2 Asset Inventory...'))

        admin = User.objects.filter(role=User.Role.ADMIN).first()
        if not admin:
            admin = User.objects.create_superuser('admin', 'admin@cba.edu', 'admin123')
            admin.role = User.Role.ADMIN
            admin.save()

        # Ensure brands
        brand_names = ['Lenovo', 'Dell', 'Epson', 'Samsung', 'Acer', 'Carrier', 'Brother', 'HP']
        brands = {}
        for b in brand_names:
            brand_obj, _ = Brand.objects.get_or_create(name=b, defaults={'is_active': True})
            brands[b] = brand_obj

        # Ensure categories
        cats_data = [
            ('Information Technology', 'IT', 'Computers, laptops, monitors, projectors, switches'),
            ('Office Equipment', 'OE', 'Printers, scanners, shredders, laminators'),
            ('Furniture & Fixtures', 'FN', 'Desks, office chairs, conference tables, file cabinets'),
            ('Audio-Visual Equipment', 'AV', 'Microphones, speakers, amplifiers, displays'),
            ('Appliances', 'AP', 'Air conditioners, water dispensers, refrigerators'),
        ]
        categories = {}
        for name, code, desc in cats_data:
            cat_obj, _ = AssetCategory.objects.get_or_create(code=code, defaults={'name': name, 'description': desc, 'is_active': True})
            categories[code] = cat_obj

        # Ensure departments
        dept_ba, _ = Department.objects.get_or_create(code='BA', defaults={'name': 'Department of Business Administration', 'is_active': True})
        dept_acct, _ = Department.objects.get_or_create(code='ACCT', defaults={'name': 'Department of Accountancy', 'is_active': True})
        dept_hm, _ = Department.objects.get_or_create(code='HM', defaults={'name': 'Department of Hospitality Management', 'is_active': True})

        # Ensure locations
        loc_dean, _ = Location.objects.get_or_create(name="Dean's Office", defaults={'department': dept_ba, 'building': 'CBA Main', 'room_number': '101', 'is_active': True})
        loc_lab, _ = Location.objects.get_or_create(name="CBA Computer Laboratory", defaults={'department': dept_ba, 'building': 'IT Wing', 'room_number': '201', 'is_active': True})
        loc_acct_off, _ = Location.objects.get_or_create(name="Accountancy Department Office", defaults={'department': dept_acct, 'building': 'CBA Annex', 'room_number': '302', 'is_active': True})
        loc_fac_rm, _ = Location.objects.get_or_create(name="General Faculty Room", defaults={'department': dept_ba, 'building': 'CBA Main', 'room_number': '205', 'is_active': True})

        sample_assets = [
            {
                'item_name': 'Lenovo ThinkPad L14 Gen 3 Laptop',
                'category': categories['IT'],
                'brand': brands['Lenovo'],
                'model': '21C1S00K00',
                'serial_number': 'PF43A892',
                'property_number': 'NORSU-CBA-2026-00101',
                'department': dept_acct,
                'current_location': loc_acct_off,
                'condition': Asset.Condition.GOOD,
                'status': Asset.Status.AVAILABLE,
                'acquisition_date': date(2025, 6, 15),
                'acquisition_cost': Decimal('54500.00'),
                'supplier': 'MicroGenesis Business Systems',
                'description': '14-inch FHD, Intel Core i5-1235U, 16GB DDR4, 512GB NVMe SSD, Windows 11 Pro',
                'remarks': 'Issued for department chair administrative tasks.',
            },
            {
                'item_name': 'Epson EcoTank L3210 All-in-One Printer',
                'category': categories['OE'],
                'brand': brands['Epson'],
                'model': 'C11CJ68501',
                'serial_number': 'X87K992144',
                'property_number': 'NORSU-CBA-2026-00102',
                'department': dept_ba,
                'current_location': loc_dean,
                'condition': Asset.Condition.NEW,
                'status': Asset.Status.AVAILABLE,
                'acquisition_date': date(2025, 8, 20),
                'acquisition_cost': Decimal('9890.00'),
                'supplier': 'Silicon Valley Computer Group',
                'description': 'Multifunction colour ink tank printer with flatbed scanner and copier.',
                'remarks': 'Assigned to Dean office document processing.',
            },
            {
                'item_name': 'Acer Veriton X2680G Desktop Computer',
                'category': categories['IT'],
                'brand': brands['Acer'],
                'model': 'VX2680G-I5',
                'serial_number': 'DTVZ0SP00122',
                'property_number': 'NORSU-CBA-2026-00103',
                'department': dept_ba,
                'current_location': loc_lab,
                'condition': Asset.Condition.GOOD,
                'status': Asset.Status.AVAILABLE,
                'acquisition_date': date(2025, 4, 10),
                'acquisition_cost': Decimal('42800.00'),
                'supplier': 'Octagon Computer Superstore',
                'description': 'Small Form Factor desktop, Intel Core i5-11400, 16GB RAM, 512GB SSD.',
                'remarks': 'Workstation #01 in CBA Computer Lab.',
            },
            {
                'item_name': 'Samsung 27" Essential S3 Curved Monitor',
                'category': categories['IT'],
                'brand': brands['Samsung'],
                'model': 'LS27C360EAEXXP',
                'serial_number': '0E6Y3NDXA01449',
                'property_number': 'NORSU-CBA-2026-00104',
                'department': dept_ba,
                'current_location': loc_lab,
                'condition': Asset.Condition.GOOD,
                'status': Asset.Status.AVAILABLE,
                'acquisition_date': date(2025, 4, 10),
                'acquisition_cost': Decimal('8990.00'),
                'supplier': 'Octagon Computer Superstore',
                'description': '1800R curved VA panel, Full HD 1080p, 75Hz refresh rate with Eye Saver mode.',
                'remarks': 'Paired with Computer Lab Workstation #01.',
            },
            {
                'item_name': 'Epson EB-E01 XGA 3LCD Projector',
                'category': categories['AV'],
                'brand': brands['Epson'],
                'model': 'H971A',
                'serial_number': 'X6YF140089',
                'property_number': 'NORSU-CBA-2026-00105',
                'department': dept_ba,
                'current_location': loc_dean,
                'condition': Asset.Condition.GOOD,
                'status': Asset.Status.AVAILABLE,
                'acquisition_date': date(2025, 7, 5),
                'acquisition_cost': Decimal('23950.00'),
                'supplier': 'Columbia Technologies Inc.',
                'description': '3,300 lumens brightness, XGA 1024x768 resolution, HDMI/VGA inputs.',
                'remarks': 'Available for college assembly and presentation use.',
            },
            {
                'item_name': 'Ergonomic High-Back Executive Mesh Chair',
                'category': categories['FN'],
                'brand': None,
                'model': 'ErgoMax-H8',
                'serial_number': '',
                'property_number': 'NORSU-CBA-2026-00106',
                'department': dept_acct,
                'current_location': loc_acct_off,
                'condition': Asset.Condition.GOOD,
                'status': Asset.Status.AVAILABLE,
                'acquisition_date': date(2025, 3, 12),
                'acquisition_cost': Decimal('7500.00'),
                'supplier': 'Mandaue Foam Industries',
                'description': 'Breathable mesh back with adjustable lumbar support, 3D armrests, and nylon casters.',
                'remarks': 'Chair assigned to Accountancy Chair Office.',
            },
            {
                'item_name': 'Modular Executive Faculty Table with Pedestal',
                'category': categories['FN'],
                'brand': None,
                'model': 'MOD-DSK-140',
                'serial_number': '',
                'property_number': 'NORSU-CBA-2026-00107',
                'department': dept_ba,
                'current_location': loc_fac_rm,
                'condition': Asset.Condition.GOOD,
                'status': Asset.Status.AVAILABLE,
                'acquisition_date': date(2025, 2, 28),
                'acquisition_cost': Decimal('14200.00'),
                'supplier': 'Mandaue Foam Industries',
                'description': '1400x700mm melamine laminated table top, steel powder-coated legs, mobile 3-drawer pedestal.',
                'remarks': 'Located at Faculty Station #03.',
            },
            {
                'item_name': 'Carrier 2.0HP Split-Type Inverter Air Conditioner',
                'category': categories['AP'],
                'brand': brands['Carrier'],
                'model': 'FP-53CSVS018-303',
                'serial_number': 'CR25098114',
                'property_number': 'NORSU-CBA-2026-00108',
                'department': dept_ba,
                'current_location': loc_dean,
                'condition': Asset.Condition.GOOD,
                'status': Asset.Status.AVAILABLE,
                'acquisition_date': date(2025, 1, 15),
                'acquisition_cost': Decimal('48900.00'),
                'supplier': 'Abenson Commercial Corp',
                'description': '2.0 HP cooling capacity, inverter technology, R32 refrigerant.',
                'remarks': 'Mounted in Dean Office conference corner.',
            },
        ]

        count = 0
        for data in sample_assets:
            prop_num = data.get('property_number')
            asset, created = Asset.objects.get_or_create(
                property_number=prop_num,
                defaults={
                    **data,
                    'created_by': admin,
                }
            )
            if created:
                count += 1
                self.stdout.write(f"  Created Asset: {asset.asset_code} - {asset.item_name} (Prop #: {asset.property_number})")
                log_action(admin, 'ASSET_CREATED', asset, changes={'seed': True})
            else:
                self.stdout.write(f"  Existing Asset: {asset.asset_code} - {asset.item_name}")

        self.stdout.write(self.style.SUCCESS(f"Phase 2 seed completed: {count} new assets created!"))
