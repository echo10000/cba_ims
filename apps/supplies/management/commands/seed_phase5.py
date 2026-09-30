from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from datetime import timedelta

from apps.accounts.models import User
from apps.organizations.models import Department, Location, Employee
from apps.inventory.models import Brand
from apps.supplies.models import SupplyCategory, Supply, SupplyTransaction
from apps.supplies import services as supply_services


class Command(BaseCommand):
    help = 'Seeds Phase 5 Consumable Supplies and Stock Transaction data (Idempotent)'

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
        self.stdout.write(self.style.NOTICE("Seeding CBA IMS Phase 5 Consumable Supplies & Transactions..."))

        admin_user = User.objects.filter(role=User.Role.ADMIN).first()
        if not admin_user:
            self.stdout.write(self.style.ERROR("Admin user not found. Please run seed_phase1 first."))
            return

        dept_acct = Department.objects.filter(code='ACCT').first()
        dept_ba = Department.objects.filter(code='BA').first()
        emp_maria = Employee.objects.filter(first_name='Maria', last_name='Santos').first()
        emp_garcia = Employee.objects.filter(first_name='Jose', last_name='Garcia').first()

        # 1. Supply Categories
        categories_data = [
            {'code': 'PAPER', 'name': 'Paper Products', 'description': 'Bond paper, cardstock, envelopes, notepads'},
            {'code': 'PRINT', 'name': 'Printer Consumables', 'description': 'Ink bottles, toner cartridges, print ribbons'},
            {'code': 'WRITE', 'name': 'Writing Materials', 'description': 'Ballpens, whiteboard markers, highlighters, pencils'},
            {'code': 'OFFICE', 'name': 'Office Supplies', 'description': 'Folders, staple wires, paperclips, fasteners, tape'},
            {'code': 'CLEAN', 'name': 'Cleaning Materials', 'description': 'Disinfectants, microfiber cloths, trash bags'},
        ]
        categories = {}
        for c in categories_data:
            cat, created = SupplyCategory.objects.get_or_create(
                code=c['code'],
                defaults={'name': c['name'], 'description': c['description'], 'is_active': True}
            )
            categories[c['code']] = cat
            if created:
                self.stdout.write(f"  Created category: {cat.name}")

        # 2. Brands
        brands_data = ['PaperOne', 'Pilot', 'Faber-Castell', 'HBW', 'Epson']
        brands = {}
        for b_name in brands_data:
            brand, created = Brand.objects.get_or_create(name=b_name, defaults={'is_active': True})
            brands[b_name] = brand

        # 3. Supplies
        supplies_data = [
            {
                'name': 'Bond Paper A4 (70gsm)',
                'category': categories['PAPER'],
                'brand': brands['PaperOne'],
                'unit': Supply.Unit.REAM,
                'reorder_level': 10,
                'description': 'Standard multi-purpose copy paper 500 sheets/ream'
            },
            {
                'name': 'Epson 003 Black Ink Bottle',
                'category': categories['PRINT'],
                'brand': brands['Epson'],
                'unit': Supply.Unit.BOTTLE,
                'reorder_level': 3,
                'description': '65ml original black refill ink for EcoTank printers'
            },
            {
                'name': 'Whiteboard Marker (Black)',
                'category': categories['WRITE'],
                'brand': brands['Pilot'],
                'unit': Supply.Unit.PIECE,
                'reorder_level': 10,
                'description': 'Refillable bullet-tip whiteboard marker'
            },
            {
                'name': 'Ballpoint Pen (Black, 0.7mm)',
                'category': categories['WRITE'],
                'brand': brands['Pilot'],
                'unit': Supply.Unit.BOX,
                'reorder_level': 5,
                'description': 'Box of 12 retractable black pens'
            },
            {
                'name': 'Manila Folder (Long)',
                'category': categories['OFFICE'],
                'brand': brands['HBW'],
                'unit': Supply.Unit.PIECE,
                'reorder_level': 20,
                'description': 'Heavy tagboard file folders, legal size'
            },
            {
                'name': 'Heavy Duty Staple Wire #35',
                'category': categories['OFFICE'],
                'brand': brands['Faber-Castell'],
                'unit': Supply.Unit.BOX,
                'reorder_level': 5,
                'description': 'Standard 26/6 staple cartridges, 5000 staples/box'
            },
        ]

        supplies = {}
        for s_data in supplies_data:
            supply = Supply.objects.filter(item_name=s_data['name']).first()
            if not supply:
                supply = Supply(
                    item_name=s_data['name'],
                    category=s_data['category'],
                    brand=s_data['brand'],
                    unit=s_data['unit'],
                    reorder_level=s_data['reorder_level'],
                    description=s_data['description'],
                    created_by=admin_user,
                    is_active=True
                )
                supply.save()
                self.stdout.write(f"  Created supply: {supply.supply_code} - {supply.item_name}")
            supplies[s_data['name']] = supply

        # 4. Transactions (Idempotent by reference number)
        # Bond Paper: Initial In 50, Out 8 -> Balance 42
        paper = supplies['Bond Paper A4 (70gsm)']
        if not SupplyTransaction.objects.filter(reference_number='DR-2026-00101').exists():
            supply_services.stock_in(
                supply=paper,
                quantity=50,
                processed_by=admin_user,
                transaction_date=timezone.now().date() - timedelta(days=14),
                reference_number='DR-2026-00101',
                remarks='Initial semester delivery from Central Procurement'
            )
            self.stdout.write("  Bond Paper: Stock In 50 posted.")

        if not SupplyTransaction.objects.filter(reference_number='ISS-2026-00015').exists():
            supply_services.stock_out(
                supply=paper,
                quantity=8,
                processed_by=admin_user,
                department=dept_acct,
                employee=emp_maria,
                purpose='Midterm examination printing and departmental memos',
                transaction_date=timezone.now().date() - timedelta(days=5),
                reference_number='ISS-2026-00015'
            )
            self.stdout.write("  Bond Paper: Stock Out 8 to Accountancy posted.")

        # Ink Bottle: In 10, Out 8 -> Balance 2 (LOW STOCK, Reorder=3)
        ink = supplies['Epson 003 Black Ink Bottle']
        if not SupplyTransaction.objects.filter(reference_number='DR-2026-00102').exists():
            supply_services.stock_in(
                supply=ink,
                quantity=10,
                processed_by=admin_user,
                transaction_date=timezone.now().date() - timedelta(days=20),
                reference_number='DR-2026-00102',
                remarks='Faculty computer lab replenishment'
            )

        if not SupplyTransaction.objects.filter(reference_number='ISS-2026-00021').exists():
            supply_services.stock_out(
                supply=ink,
                quantity=8,
                processed_by=admin_user,
                department=dept_ba,
                employee=emp_garcia,
                purpose='Dean and Department Chair office printer supply',
                transaction_date=timezone.now().date() - timedelta(days=3),
                reference_number='ISS-2026-00021'
            )
            self.stdout.write("  Ink Bottle: Stock Out 8 (Status: Low Stock).")

        # Whiteboard Marker: In 30, Out 20, Adj Out 2 -> Balance 8 (LOW STOCK, Reorder=10)
        marker = supplies['Whiteboard Marker (Black)']
        if not SupplyTransaction.objects.filter(reference_number='DR-2026-00103').exists():
            supply_services.stock_in(
                supply=marker,
                quantity=30,
                processed_by=admin_user,
                transaction_date=timezone.now().date() - timedelta(days=30),
                reference_number='DR-2026-00103'
            )

        if not SupplyTransaction.objects.filter(reference_number='ISS-2026-00022').exists():
            supply_services.stock_out(
                supply=marker,
                quantity=20,
                processed_by=admin_user,
                department=dept_acct,
                purpose='Classroom lecture allocation',
                transaction_date=timezone.now().date() - timedelta(days=10),
                reference_number='ISS-2026-00022'
            )

        if not SupplyTransaction.objects.filter(reference_number='ADJ-2026-00001').exists():
            supply_services.adjust_stock(
                supply=marker,
                adjustment_type=SupplyTransaction.TransactionType.ADJUSTMENT_OUT,
                quantity=2,
                processed_by=admin_user,
                reason='Dried markers found defective during faculty turnover',
                transaction_date=timezone.now().date() - timedelta(days=2),
                reference_number='ADJ-2026-00001'
            )
            self.stdout.write("  Marker: Adjustment Out 2 posted (Defective).")

        # Staple Wire: In 5, Out 5 -> Balance 0 (OUT OF STOCK, Reorder=5)
        staple = supplies['Heavy Duty Staple Wire #35']
        if not SupplyTransaction.objects.filter(reference_number='DR-2026-00104').exists():
            supply_services.stock_in(
                supply=staple,
                quantity=5,
                processed_by=admin_user,
                transaction_date=timezone.now().date() - timedelta(days=40),
                reference_number='DR-2026-00104'
            )

        if not SupplyTransaction.objects.filter(reference_number='ISS-2026-00030').exists():
            supply_services.stock_out(
                supply=staple,
                quantity=5,
                processed_by=admin_user,
                department=dept_ba,
                purpose='Accreditation binder preparation',
                transaction_date=timezone.now().date() - timedelta(days=1),
                reference_number='ISS-2026-00030'
            )
            self.stdout.write("  Staple Wire: Depleted to 0 (Status: Out of Stock).")

        self.stdout.write(self.style.SUCCESS("Successfully seeded Phase 5 Consumable Supplies and Stock Transactions!"))
