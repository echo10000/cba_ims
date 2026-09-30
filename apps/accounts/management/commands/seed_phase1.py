from django.core.management.base import BaseCommand, CommandError
from apps.accounts.models import User
from apps.organizations.models import Department, Location, Employee
from apps.inventory.models import AssetCategory, Brand
from apps.audit.utils import log_action


class Command(BaseCommand):
    help = 'Seed initial development data for CBA IMS Phase 1'

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
        self.stdout.write(self.style.NOTICE('Seeding CBA IMS Phase 1 data...'))

        # 1. Departments
        depts_data = [
            ('Department of Accountancy', 'ACCT', 'Handles BS Accountancy and related courses'),
            ('Department of Business Administration', 'BA', 'Handles General Business and Operations'),
            ('Department of Hospitality Management', 'HM', 'Handles Hospitality and Tourism programs'),
            ('Department of Marketing & Finance', 'MF', 'Handles Financial Management and Marketing'),
        ]
        departments = {}
        for name, code, desc in depts_data:
            dept, created = Department.objects.get_or_create(
                code=code,
                defaults={'name': name, 'description': desc, 'is_active': True}
            )
            departments[code] = dept
            if created:
                self.stdout.write(f'  Created Department: {name} ({code})')

        # 2. Locations
        locs_data = [
            ("Dean's Office", 'CBA Main Building', '1st Floor', '101', departments['BA']),
            ("General Faculty Room", 'CBA Main Building', '2nd Floor', '205', departments['BA']),
            ("Accountancy Department Office", 'CBA Annex', '3rd Floor', '302', departments['ACCT']),
            ("CBA Computer Laboratory", 'IT Wing', '2nd Floor', '201', departments['BA']),
            ("Hospitality Training Center", 'CBA Annex', '1st Floor', '105', departments['HM']),
            ("Property & Supply Storage Room", 'Main Building', 'Basement', 'B-04', departments['BA']),
        ]
        locations = {}
        for name, bldg, floor, room, dept in locs_data:
            loc, created = Location.objects.get_or_create(
                name=name,
                defaults={
                    'building': bldg,
                    'floor': floor,
                    'room_number': room,
                    'department': dept,
                    'is_active': True
                }
            )
            locations[name] = loc
            if created:
                self.stdout.write(f'  Created Location: {name}')

        # 3. Asset Categories
        categories_data = [
            ('Information Technology', 'IT', 'Computers, laptops, monitors, projectors, switches'),
            ('Office Equipment', 'OE', 'Printers, scanners, shredders, laminators'),
            ('Furniture & Fixtures', 'FN', 'Desks, office chairs, conference tables, file cabinets'),
            ('Audio-Visual Equipment', 'AV', 'Microphones, speakers, amplifiers, displays'),
            ('Appliances', 'AP', 'Air conditioners, water dispensers, refrigerators'),
        ]
        categories = {}
        for name, code, desc in categories_data:
            cat, created = AssetCategory.objects.get_or_create(
                code=code,
                defaults={'name': name, 'description': desc, 'is_active': True}
            )
            categories[code] = cat
            if created:
                self.stdout.write(f'  Created Category: {name} ({code})')

        # 4. Brands
        brands_data = ['Dell', 'HP', 'Lenovo', 'Samsung', 'Epson', 'Canon', 'Apple', 'Carrier']
        brands = {}
        for b_name in brands_data:
            brand, created = Brand.objects.get_or_create(
                name=b_name,
                defaults={'is_active': True}
            )
            brands[b_name] = brand
            if created:
                self.stdout.write(f'  Created Brand: {b_name}')

        # 5. Users & Employee Profiles
        users_data = [
            ('admin', 'admin@cba.edu', 'admin123', 'Property', 'Custodian', User.Role.ADMIN, 'EMP-CUST-001', 'Property Custodian', departments['BA'], locations['Property & Supply Storage Room'], True),
            ('dean_cruz', 'dean.cruz@cba.edu', 'dean123', 'Robert', 'Cruz', User.Role.DEAN, 'EMP-DEAN-001', 'College Dean', departments['BA'], locations["Dean's Office"], False),
            ('chair_santos', 'elena.santos@cba.edu', 'chair123', 'Elena', 'Santos', User.Role.DEPT_CHAIR, 'EMP-ACCT-001', 'Department Chairperson', departments['ACCT'], locations['Accountancy Department Office'], False),
            ('prof_maria', 'maria.santos@cba.edu', 'faculty123', 'Maria', 'Santos', User.Role.FACULTY, 'EMP-FAC-001', 'Assistant Professor', departments['ACCT'], locations['General Faculty Room'], False),
            ('prof_garcia', 'jose.garcia@cba.edu', 'faculty123', 'Jose', 'Garcia', User.Role.FACULTY, 'EMP-FAC-002', 'Associate Professor', departments['BA'], locations['General Faculty Room'], False),
        ]

        for username, email, pwd, first, last, role, emp_id, pos, dept, loc, is_staff in users_data:
            user, created = User.objects.get_or_create(
                username=username,
                defaults={
                    'email': email,
                    'first_name': first,
                    'last_name': last,
                    'role': role,
                    'is_staff': is_staff or role == User.Role.ADMIN,
                    'is_superuser': role == User.Role.ADMIN,
                }
            )
            if created:
                user.set_password(pwd)
                user.save()
                self.stdout.write(f'  Created User: {username} (Role: {role})')

            emp, emp_created = Employee.objects.get_or_create(
                employee_id=emp_id,
                defaults={
                    'user': user,
                    'first_name': first,
                    'last_name': last,
                    'email': email,
                    'position': pos,
                    'department': dept,
                    'location': loc,
                    'is_active': True,
                }
            )
            if emp_created:
                self.stdout.write(f'  Created Employee profile: {emp}')

            # Log audit event
            log_action(user, 'SEEDED', emp)

        # Set Department heads
        dept_acct = departments['ACCT']
        chair_emp = Employee.objects.filter(employee_id='EMP-ACCT-001').first()
        if chair_emp:
            dept_acct.head = chair_emp
            dept_acct.save(update_fields=['head'])

        self.stdout.write(self.style.SUCCESS('Successfully seeded Phase 1 data!'))
        self.stdout.write(self.style.NOTICE(
            "\nDefault login credentials:\n"
            "  Admin:        admin / admin123\n"
            "  Dean:         dean_cruz / dean123\n"
            "  Dept Chair:   chair_santos / chair123\n"
            "  Faculty:      prof_maria / faculty123\n"
        ))
