from django.test import TestCase, Client
from django.urls import reverse
from django.core.exceptions import ValidationError
from django.db.models import ProtectedError
from django.utils import timezone
from datetime import timedelta

from apps.accounts.models import User
from apps.organizations.models import Department, Location, Employee
from apps.inventory.models import Brand
from apps.audit.models import AuditLog
from apps.supplies.models import SupplyCategory, Supply, SupplyTransaction, generate_supply_code
from apps.supplies import services


class SupplyBaseTestCase(TestCase):
    """Base setup for supplies testing with users, orgs, and initial data."""

    def setUp(self):
        # 1. Departments & Locations
        self.dept_acct = Department.objects.create(name='Accountancy', code='ACCT')
        self.dept_ba = Department.objects.create(name='Business Administration', code='BA')
        self.loc_office = Location.objects.create(name='Faculty Office', department=self.dept_acct)

        # 2. Employees & Users
        self.admin_user = User.objects.create_user(
            username='admin_test',
            email='admin@cba.edu',
            password='testpassword123',
            role=User.Role.ADMIN
        )
        self.dean_user = User.objects.create_user(
            username='dean_test',
            email='dean@cba.edu',
            password='testpassword123',
            role=User.Role.DEAN
        )
        self.chair_user = User.objects.create_user(
            username='chair_test',
            email='chair@cba.edu',
            password='testpassword123',
            role=User.Role.DEPT_CHAIR
        )
        self.chair_emp = Employee.objects.create(
            user=self.chair_user,
            employee_id='EMP-CHAIR',
            first_name='Chair',
            last_name='Person',
            department=self.dept_acct,
            position='Department Chair'
        )

        self.faculty_user = User.objects.create_user(
            username='faculty_test',
            email='faculty@cba.edu',
            password='testpassword123',
            role=User.Role.FACULTY
        )
        self.faculty_emp = Employee.objects.create(
            user=self.faculty_user,
            employee_id='EMP-FACULTY',
            first_name='Maria',
            last_name='Santos',
            department=self.dept_acct,
            position='Faculty Member'
        )

        # 3. Supply Categories & Brands
        self.cat_paper = SupplyCategory.objects.create(name='Paper Products', code='PAPER')
        self.cat_print = SupplyCategory.objects.create(name='Printer Consumables', code='PRINT')
        self.brand_pilot = Brand.objects.create(name='Pilot', is_active=True)

        # 4. Standard Supply
        self.paper = Supply.objects.create(
            item_name='Bond Paper A4',
            category=self.cat_paper,
            brand=self.brand_pilot,
            unit=Supply.Unit.REAM,
            reorder_level=10,
            created_by=self.admin_user
        )


class SupplyModelTests(SupplyBaseTestCase):
    """Tests for Supply, SupplyCategory, and SupplyTransaction model behaviors."""

    def test_supply_code_generation_format(self):
        """Supply code must adhere to CBA-SUP-{CAT}-{NUMBER:05d}."""
        self.assertTrue(self.paper.supply_code.startswith('CBA-SUP-PAPER-'))
        num_part = self.paper.supply_code.split('-')[-1]
        self.assertEqual(len(num_part), 5)
        self.assertTrue(num_part.isdigit())

    def test_supply_code_uniqueness_and_increment(self):
        """Successive supplies in same category increment counter."""
        paper2 = Supply.objects.create(
            item_name='Bond Paper Legal',
            category=self.cat_paper,
            unit=Supply.Unit.REAM,
            created_by=self.admin_user
        )
        self.assertNotEqual(self.paper.supply_code, paper2.supply_code)
        num1 = int(self.paper.supply_code.split('-')[-1])
        num2 = int(paper2.supply_code.split('-')[-1])
        self.assertEqual(num2, num1 + 1)

    def test_supply_code_stability_on_update(self):
        """Saving an existing supply must not alter its supply_code."""
        original_code = self.paper.supply_code
        self.paper.item_name = 'Bond Paper A4 Premium'
        self.paper.save()
        self.paper.refresh_from_db()
        self.assertEqual(self.paper.supply_code, original_code)

    def test_category_code_uppercase_normalization(self):
        """Category codes must automatically be converted to uppercase."""
        cat = SupplyCategory.objects.create(name='Writing Tools', code='write')
        self.assertEqual(cat.code, 'WRITE')

    def test_supply_transaction_immutability_on_save(self):
        """Modifying an existing SupplyTransaction record must raise PermissionError."""
        tx = services.stock_in(self.paper, quantity=20, processed_by=self.admin_user)
        tx.quantity = 50
        with self.assertRaises(PermissionError):
            tx.save()

    def test_supply_transaction_immutability_on_delete(self):
        """Calling delete() on a SupplyTransaction must raise PermissionError."""
        tx = services.stock_in(self.paper, quantity=20, processed_by=self.admin_user)
        with self.assertRaises(PermissionError):
            tx.delete()

    def test_foreign_key_protection_category(self):
        """Cannot delete SupplyCategory if supplies reference it."""
        with self.assertRaises(ProtectedError):
            self.cat_paper.delete()

    def test_foreign_key_protection_supply(self):
        """Cannot delete Supply if transactions reference it."""
        services.stock_in(self.paper, quantity=10, processed_by=self.admin_user)
        with self.assertRaises(ProtectedError):
            self.paper.delete()

    def test_signed_quantity_and_direction_properties(self):
        """Verifies signed_quantity, is_incoming, and is_outgoing properties."""
        tx_in = services.stock_in(self.paper, quantity=15, processed_by=self.admin_user)
        self.assertEqual(tx_in.signed_quantity, 15)
        self.assertTrue(tx_in.is_incoming)
        self.assertFalse(tx_in.is_outgoing)

        tx_out = services.stock_out(self.paper, quantity=5, processed_by=self.admin_user, department=self.dept_acct)
        self.assertEqual(tx_out.signed_quantity, -5)
        self.assertFalse(tx_out.is_incoming)
        self.assertTrue(tx_out.is_outgoing)


class SupplyStockCalculationTests(SupplyBaseTestCase):
    """Tests for authoritative on-hand stock calculations and status derivations."""

    def test_initial_stock_is_zero(self):
        """New supply has 0 stock balance and OUT_OF_STOCK status."""
        self.assertEqual(self.paper.current_stock, 0)
        self.assertEqual(self.paper.stock_status, 'OUT_OF_STOCK')
        self.assertTrue(self.paper.is_low_stock)

    def test_stock_in_increases_balance(self):
        """Stock in increases current_stock."""
        services.stock_in(self.paper, quantity=25, processed_by=self.admin_user)
        self.assertEqual(self.paper.current_stock, 25)
        # reorder_level is 10, so 25 is IN_STOCK
        self.assertEqual(self.paper.stock_status, 'IN_STOCK')
        self.assertFalse(self.paper.is_low_stock)

    def test_stock_out_decreases_balance(self):
        """Stock out deducts from current_stock."""
        services.stock_in(self.paper, quantity=20, processed_by=self.admin_user)
        services.stock_out(self.paper, quantity=8, processed_by=self.admin_user, department=self.dept_acct)
        self.assertEqual(self.paper.current_stock, 12)

    def test_adjustments_modify_balance(self):
        """ADJUSTMENT_IN adds to balance, ADJUSTMENT_OUT deducts from balance."""
        services.stock_in(self.paper, quantity=10, processed_by=self.admin_user)
        services.adjust_stock(
            self.paper,
            SupplyTransaction.TransactionType.ADJUSTMENT_IN,
            quantity=5,
            processed_by=self.admin_user,
            reason='Found uncounted stock'
        )
        self.assertEqual(self.paper.current_stock, 15)

        services.adjust_stock(
            self.paper,
            SupplyTransaction.TransactionType.ADJUSTMENT_OUT,
            quantity=3,
            processed_by=self.admin_user,
            reason='Damaged reams discarded'
        )
        self.assertEqual(self.paper.current_stock, 12)

    def test_complex_transaction_sequence(self):
        """
        Stock In 100 -> Stock Out 25 -> Adjustment In 5 -> Adjustment Out 3 -> Stock Out 12
        Net = 100 - 25 + 5 - 3 - 12 = 65.
        """
        services.stock_in(self.paper, quantity=100, processed_by=self.admin_user)
        services.stock_out(self.paper, quantity=25, processed_by=self.admin_user, department=self.dept_acct)
        services.adjust_stock(self.paper, SupplyTransaction.TransactionType.ADJUSTMENT_IN, quantity=5, processed_by=self.admin_user, reason='Surplus')
        services.adjust_stock(self.paper, SupplyTransaction.TransactionType.ADJUSTMENT_OUT, quantity=3, processed_by=self.admin_user, reason='Defective')
        services.stock_out(self.paper, quantity=12, processed_by=self.admin_user, department=self.dept_ba)

        self.assertEqual(self.paper.current_stock, 65)

    def test_stock_status_thresholds(self):
        """Verify OUT_OF_STOCK, LOW_STOCK, and IN_STOCK boundaries."""
        # reorder_level = 10
        self.assertEqual(services.get_stock_status(0, 10), 'OUT_OF_STOCK')
        self.assertEqual(services.get_stock_status(-1, 10), 'OUT_OF_STOCK')
        self.assertEqual(services.get_stock_status(1, 10), 'LOW_STOCK')
        self.assertEqual(services.get_stock_status(10, 10), 'LOW_STOCK')
        self.assertEqual(services.get_stock_status(11, 10), 'IN_STOCK')

    def test_annotated_queryset_matches_property(self):
        """services.get_annotated_supplies_queryset calculates exact same stock as model property."""
        services.stock_in(self.paper, quantity=50, processed_by=self.admin_user)
        services.stock_out(self.paper, quantity=18, processed_by=self.admin_user, department=self.dept_acct)

        annotated = services.get_annotated_supplies_queryset().get(pk=self.paper.pk)
        self.assertEqual(annotated.calculated_stock, self.paper.current_stock)
        self.assertEqual(annotated.calculated_stock, 32)


class NegativeStockAndConcurrencyTests(SupplyBaseTestCase):
    """Tests preventing negative inventory, over-issuance, and invalid parameters."""

    def test_over_issuance_rejected(self):
        """Cannot issue more stock than currently on hand."""
        services.stock_in(self.paper, quantity=10, processed_by=self.admin_user)
        with self.assertRaises(ValidationError) as ctx:
            services.stock_out(self.paper, quantity=15, processed_by=self.admin_user, department=self.dept_acct)
        self.assertIn("Insufficient stock", str(ctx.exception))
        # Ensure stock remained unchanged
        self.assertEqual(self.paper.current_stock, 10)

    def test_stock_out_from_zero_stock_rejected(self):
        """Cannot issue stock when on-hand quantity is 0."""
        self.assertEqual(self.paper.current_stock, 0)
        with self.assertRaises(ValidationError) as ctx:
            services.stock_out(self.paper, quantity=1, processed_by=self.admin_user, department=self.dept_acct)
        self.assertIn("Insufficient stock", str(ctx.exception))

    def test_adjustment_out_exceeding_stock_rejected(self):
        """Adjustment out cannot exceed on-hand balance."""
        services.stock_in(self.paper, quantity=5, processed_by=self.admin_user)
        with self.assertRaises(ValidationError) as ctx:
            services.adjust_stock(
                self.paper,
                SupplyTransaction.TransactionType.ADJUSTMENT_OUT,
                quantity=6,
                processed_by=self.admin_user,
                reason='Loss'
            )
        self.assertIn("Only 5 Ream are currently available", str(ctx.exception))

    def test_zero_or_negative_quantities_rejected(self):
        """Quantities must be strictly greater than zero."""
        with self.assertRaises(ValidationError):
            services.stock_in(self.paper, quantity=0, processed_by=self.admin_user)
        with self.assertRaises(ValidationError):
            services.stock_in(self.paper, quantity=-5, processed_by=self.admin_user)
        with self.assertRaises(ValidationError):
            services.stock_out(self.paper, quantity=0, processed_by=self.admin_user)
        with self.assertRaises(ValidationError):
            services.adjust_stock(
                self.paper,
                SupplyTransaction.TransactionType.ADJUSTMENT_IN,
                quantity=-2,
                processed_by=self.admin_user,
                reason='Test'
            )

    def test_inactive_supply_operations_rejected(self):
        """Cannot perform stock operations on inactive supplies."""
        self.paper.is_active = False
        self.paper.save()

        with self.assertRaises(ValidationError):
            services.stock_in(self.paper, quantity=10, processed_by=self.admin_user)
        with self.assertRaises(ValidationError):
            services.stock_out(self.paper, quantity=5, processed_by=self.admin_user)
        with self.assertRaises(ValidationError):
            services.adjust_stock(
                self.paper,
                SupplyTransaction.TransactionType.ADJUSTMENT_IN,
                quantity=5,
                processed_by=self.admin_user,
                reason='Surplus'
            )

    def test_adjustment_requires_reason(self):
        """Inventory adjustment requires a non-empty reason."""
        services.stock_in(self.paper, quantity=10, processed_by=self.admin_user)
        with self.assertRaises(ValidationError):
            services.adjust_stock(
                self.paper,
                SupplyTransaction.TransactionType.ADJUSTMENT_IN,
                quantity=2,
                processed_by=self.admin_user,
                reason=''
            )
        with self.assertRaises(ValidationError):
            services.adjust_stock(
                self.paper,
                SupplyTransaction.TransactionType.ADJUSTMENT_IN,
                quantity=2,
                processed_by=self.admin_user,
                reason='   '
            )


class SupplyServiceAndAuditTests(SupplyBaseTestCase):
    """Tests for audit trail creation across all supply service operations."""

    def test_stock_in_service_audit_trail(self):
        """Stock in operation logs SUPPLY_STOCK_IN audit entry."""
        tx = services.stock_in(
            self.paper,
            quantity=30,
            processed_by=self.admin_user,
            reference_number='DR-999',
            remarks='Audit test receipt'
        )
        self.assertIsNotNone(tx.pk)
        log = AuditLog.objects.filter(action='SUPPLY_STOCK_IN').first()
        self.assertIsNotNone(log)
        self.assertEqual(log.user, self.admin_user)
        self.assertEqual(log.changes.get('quantity'), 30)
        self.assertEqual(log.changes.get('new_balance'), 30)

    def test_stock_out_service_audit_trail(self):
        """Stock out operation logs SUPPLY_STOCK_OUT audit entry."""
        services.stock_in(self.paper, quantity=20, processed_by=self.admin_user)
        tx = services.stock_out(
            self.paper,
            quantity=6,
            processed_by=self.admin_user,
            department=self.dept_acct,
            employee=self.faculty_emp,
            reference_number='ISS-100',
            purpose='Exam sheets'
        )
        self.assertIsNotNone(tx.pk)
        log = AuditLog.objects.filter(action='SUPPLY_STOCK_OUT').first()
        self.assertIsNotNone(log)
        self.assertEqual(log.changes.get('quantity'), 6)
        self.assertEqual(log.changes.get('department'), 'Accountancy')
        self.assertEqual(log.changes.get('recipient'), self.faculty_emp.full_name)
        self.assertEqual(log.changes.get('new_balance'), 14)

    def test_adjust_stock_service_audit_trail(self):
        """Stock adjustment logs correct action and changes."""
        services.stock_in(self.paper, quantity=10, processed_by=self.admin_user)
        services.adjust_stock(
            self.paper,
            SupplyTransaction.TransactionType.ADJUSTMENT_IN,
            quantity=4,
            processed_by=self.admin_user,
            reason='Found in storage box'
        )
        log_in = AuditLog.objects.filter(action='SUPPLY_ADJUSTMENT_IN').first()
        self.assertIsNotNone(log_in)
        self.assertEqual(log_in.changes.get('reason'), 'Found in storage box')
        self.assertEqual(log_in.changes.get('new_balance'), 14)

    def test_create_and_update_supply_services(self):
        """create_supply and update_supply services create records and emit audit logs."""
        new_sup = services.create_supply(
            item_name='Gel Pen Blue',
            category=self.cat_paper,
            unit=Supply.Unit.BOX,
            reorder_level=5,
            created_by=self.admin_user
        )
        self.assertTrue(new_sup.supply_code.startswith('CBA-SUP-PAPER-'))
        self.assertTrue(AuditLog.objects.filter(action='SUPPLY_CREATED').exists())\

        services.update_supply(new_sup, updated_by=self.admin_user, reorder_level=8)
        new_sup.refresh_from_db()
        self.assertEqual(new_sup.reorder_level, 8)
        self.assertTrue(AuditLog.objects.filter(action='SUPPLY_UPDATED').exists())


class SupplyRBACTests(SupplyBaseTestCase):
    """Rigorous tests enforcing Role-Based Access Control policies."""

    def setUp(self):
        super().setUp()
        self.client = Client()

    def test_admin_has_full_access(self):
        """Admin can access listing, details, forms, stock operations, and low stock."""
        self.client.force_login(self.admin_user)

        # GET checks
        urls = [\
            reverse('supplies:supply_list'),
            reverse('supplies:supply_detail', kwargs={'supply_code': self.paper.supply_code}),
            reverse('supplies:supply_create'),
            reverse('supplies:supply_edit', kwargs={'supply_code': self.paper.supply_code}),
            reverse('supplies:stock_in'),
            reverse('supplies:stock_out'),
            reverse('supplies:stock_adjust'),
            reverse('supplies:transaction_list'),
            reverse('supplies:low_stock_list'),
        ]
        for url in urls:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200, f"Admin failed GET on {url}")

    def test_dean_has_read_only_access(self):
        """Dean can view catalogs, details, transactions, but is forbidden from modifying or posting stock."""
        self.client.force_login(self.dean_user)

        # Read views must succeed (200)
        read_urls = [
            reverse('supplies:supply_list'),
            reverse('supplies:supply_detail', kwargs={'supply_code': self.paper.supply_code}),
            reverse('supplies:transaction_list'),
            reverse('supplies:low_stock_list'),
        ]
        for url in read_urls:
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 200, f"Dean should have read access to {url}")

        # Mutation views must be rejected (403 Forbidden)
        write_urls = [
            reverse('supplies:supply_create'),
            reverse('supplies:supply_edit', kwargs={'supply_code': self.paper.supply_code}),
            reverse('supplies:stock_in'),
            reverse('supplies:stock_out'),
            reverse('supplies:stock_adjust'),
        ]
        for url in write_urls:
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 403, f"Dean should get 403 GET on {url}")
            resp_post = self.client.post(url, {})
            self.assertEqual(resp_post.status_code, 403, f"Dean should get 403 POST on {url}")

    def test_dept_chair_read_only_and_scoped_transactions(self):
        """
        Department Chair has read-only access to catalog and details,
        is forbidden from write operations (403), and can only see transactions
        pertaining to their own department.
        """
        self.client.force_login(self.chair_user)

        # Read views must return 200
        resp = self.client.get(reverse('supplies:supply_list'))
        self.assertEqual(resp.status_code, 200)

        # Write views must return 403
        resp = self.client.get(reverse('supplies:stock_in'))
        self.assertEqual(resp.status_code, 403)
        resp = self.client.post(reverse('supplies:stock_in'), {})
        self.assertEqual(resp.status_code, 403)

        # Setup transactions for Accountancy (Chair's dept) and BA (other dept)
        services.stock_in(self.paper, quantity=50, processed_by=self.admin_user)
        tx_acct = services.stock_out(
            self.paper, quantity=5, processed_by=self.admin_user,
            department=self.dept_acct, reference_number='ISS-ACCT-01'
        )
        tx_ba = services.stock_out(
            self.paper, quantity=5, processed_by=self.admin_user,
            department=self.dept_ba, reference_number='ISS-BA-01'
        )

        # View transaction list as Chair
        resp_tx = self.client.get(reverse('supplies:transaction_list'))
        self.assertEqual(resp_tx.status_code, 200)
        transactions_in_view = list(resp_tx.context['transactions'])
        self.assertIn(tx_acct, transactions_in_view)
        self.assertNotIn(tx_ba, transactions_in_view)

    def test_faculty_blocked_from_administrative_supplies_views(self):
        """Faculty cannot access administrative supply views and are redirected to my_accountability."""
        self.client.force_login(self.faculty_user)

        resp = self.client.get(reverse('supplies:supply_list'))
        self.assertRedirects(resp, reverse('assignments:my_accountability'))

        resp = self.client.get(reverse('supplies:stock_in'))
        self.assertEqual(resp.status_code, 403)

    def test_anonymous_user_redirected_to_login(self):
        """Unauthenticated requests redirect to login."""
        resp = self.client.get(reverse('supplies:supply_list'))
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/accounts/login/', resp.url)


class SupplyViewTests(SupplyBaseTestCase):
    """Tests for UI views, forms, search, filters, and deletion guards."""

    def setUp(self):
        super().setUp()
        self.client = Client()
        self.client.force_login(self.admin_user)

    def test_supply_list_search_and_filters(self):
        """Search query filters supplies by item name or code."""
        ink = Supply.objects.create(
            item_name='Black Ink 003',
            category=self.cat_print,
            unit=Supply.Unit.BOTTLE,
            created_by=self.admin_user
        )

        resp = self.client.get(reverse('supplies:supply_list'), {'q': 'Ink'})
        self.assertContains(resp, 'Black Ink 003')
        self.assertNotContains(resp, 'Bond Paper A4')

        resp_cat = self.client.get(reverse('supplies:supply_list'), {'category': self.cat_print.pk})
        self.assertContains(resp_cat, 'Black Ink 003')
        self.assertNotContains(resp_cat, 'Bond Paper A4')

    def test_supply_list_htmx_partial_response(self):
        """Standard GET returns full page shell; HTMX GET returns only the partial."""
        # 1. Normal GET
        resp_full = self.client.get(reverse('supplies:supply_list'))
        self.assertEqual(resp_full.status_code, 200)
        self.assertTemplateUsed(resp_full, 'supplies/supply_list.html')
        self.assertTemplateUsed(resp_full, 'supplies/partials/_supply_results.html')
        self.assertContains(resp_full, 'id="supplyFilterForm"')
        self.assertContains(resp_full, 'id="supply-results-container"')

        # 2. HTMX GET
        resp_htmx = self.client.get(
            reverse('supplies:supply_list'),
            headers={'hx-request': 'true'}
        )
        self.assertEqual(resp_htmx.status_code, 200)
        self.assertTemplateUsed(resp_htmx, 'supplies/partials/_supply_results.html')
        self.assertTemplateNotUsed(resp_htmx, 'supplies/supply_list.html')
        self.assertNotContains(resp_htmx, 'id="supplyFilterForm"')
        self.assertContains(resp_htmx, 'desktop-table')
        self.assertContains(resp_htmx, 'mobile-card-list')

    def test_supply_list_htmx_history_restore_returns_full_page(self):
        """Browser back/forward cache restore sends HX-History-Restore-Request and gets full page."""
        resp = self.client.get(
            reverse('supplies:supply_list'),
            headers={'hx-request': 'true', 'hx-history-restore-request': 'true'}
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, 'supplies/supply_list.html')
        self.assertContains(resp, 'id="supplyFilterForm"')

    def test_supply_list_htmx_search_filtering(self):
        """HTMX search filters supply catalog by query."""
        stapler = Supply.objects.create(
            item_name='Heavy Duty Stapler',
            category=self.cat_paper,
            brand=self.brand_pilot,
            unit=Supply.Unit.PIECE,
            created_by=self.admin_user
        )
        resp = self.client.get(
            reverse('supplies:supply_list'),
            {'q': 'Heavy Duty'},
            headers={'hx-request': 'true'}
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Heavy Duty Stapler')
        self.assertNotContains(resp, 'Bond Paper A4')

    def test_supply_list_htmx_filters_and_combination(self):
        """HTMX filter dropdowns (category, brand, stock_status, status) filter correctly."""
        toner = Supply.objects.create(
            item_name='HP Laser Toner',
            category=self.cat_print,
            brand=self.brand_pilot,
            unit=Supply.Unit.CARTRIDGE,
            reorder_level=5,
            is_active=True,
            created_by=self.admin_user
        )
        inactive_paper = Supply.objects.create(
            item_name='Discontinued Notebook',
            category=self.cat_paper,
            unit=Supply.Unit.PIECE,
            reorder_level=5,
            is_active=False,
            created_by=self.admin_user
        )
        # Give toner some stock so it is IN_STOCK (15 > 5)
        services.stock_in(toner, quantity=15, processed_by=self.admin_user)

        # 1. Filter by category
        resp_cat = self.client.get(
            reverse('supplies:supply_list'),
            {'category': self.cat_print.pk},
            headers={'hx-request': 'true'}
        )
        self.assertContains(resp_cat, 'HP Laser Toner')
        self.assertNotContains(resp_cat, 'Bond Paper A4')

        # 2. Filter by status (inactive)
        resp_status = self.client.get(
            reverse('supplies:supply_list'),
            {'status': 'inactive'},
            headers={'hx-request': 'true'}
        )
        self.assertContains(resp_status, 'Discontinued Notebook')
        self.assertNotContains(resp_status, 'HP Laser Toner')

        # 3. Filter by stock_status (IN_STOCK vs OUT_OF_STOCK)
        resp_stock = self.client.get(
            reverse('supplies:supply_list'),
            {'stock_status': 'IN_STOCK'},
            headers={'hx-request': 'true'}
        )
        self.assertContains(resp_stock, 'HP Laser Toner')
        self.assertNotContains(resp_stock, 'Bond Paper A4')  # initial paper has 0 stock

        # 4. Combined filters: category + brand + stock_status
        resp_combined = self.client.get(
            reverse('supplies:supply_list'),
            {
                'category': self.cat_print.pk,
                'brand': self.brand_pilot.pk,
                'stock_status': 'IN_STOCK',
            },
            headers={'hx-request': 'true'}
        )
        self.assertContains(resp_combined, 'HP Laser Toner')
        self.assertNotContains(resp_combined, 'Discontinued Notebook')
        self.assertNotContains(resp_combined, 'Bond Paper A4')

    def test_supply_list_htmx_empty_state_without_table(self):
        """When zero supplies match, renders institutional empty state and avoids table."""
        resp = self.client.get(
            reverse('supplies:supply_list'),
            {'q': 'NON_EXISTENT_SUPPLY_QUERY_XYZ'},
            headers={'hx-request': 'true'}
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'No Supplies Found')
        self.assertContains(resp, 'Clear Filters')
        self.assertNotContains(resp, '<table')
        self.assertNotContains(resp, '<thead')

    def test_supply_list_htmx_scoping_and_rbac(self):
        """Dean and Dept Chair receive 200 via HTMX; Faculty is redirected to accountability."""
        # 1. Dean
        self.client.force_login(self.dean_user)
        resp_dean = self.client.get(
            reverse('supplies:supply_list'),
            headers={'hx-request': 'true'}
        )
        self.assertEqual(resp_dean.status_code, 200)

        # 2. Dept Chair
        self.client.force_login(self.chair_user)
        resp_chair = self.client.get(
            reverse('supplies:supply_list'),
            headers={'hx-request': 'true'}
        )
        self.assertEqual(resp_chair.status_code, 200)

        # 3. Faculty (Redirected by SupplyViewAccessMixin)
        self.client.force_login(self.faculty_user)
        resp_fac = self.client.get(
            reverse('supplies:supply_list'),
            headers={'hx-request': 'true'}
        )
        self.assertRedirects(resp_fac, reverse('assignments:my_accountability'))

    def test_supply_list_htmx_pagination(self):
        """Pagination under HTMX preserves search parameters and returns scoped pages."""
        # Create 25 additional supplies to exceed paginate_by = 20
        for i in range(25):
            Supply.objects.create(
                item_name=f'Bulk Item {i:02d}',
                category=self.cat_paper,
                unit=Supply.Unit.PIECE,
                created_by=self.admin_user
            )

        resp = self.client.get(
            reverse('supplies:supply_list'),
            {'page': 1, 'category': self.cat_paper.pk},
            headers={'hx-request': 'true'}
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.context['is_paginated'])
        self.assertContains(resp, 'Page 1 of')
        self.assertContains(resp, f'category={self.cat_paper.pk}')
        self.assertContains(resp, 'hx-target="#supply-results-container"')
        self.assertContains(resp, 'hx-push-url="true"')

        # Page 2
        resp_page2 = self.client.get(
            reverse('supplies:supply_list'),
            {'page': 2, 'category': self.cat_paper.pk},
            headers={'hx-request': 'true'}
        )
        self.assertEqual(resp_page2.status_code, 200)
        self.assertEqual(resp_page2.context['page_obj'].number, 2)

    def test_stock_in_post_view(self):
        """Posting valid data to StockInView creates transaction and updates balance."""
        data = {
            'supply': self.paper.pk,
            'quantity': 40,
            'transaction_date': timezone.now().date(),
            'reference_number': 'DR-2026-VIEW',
            'remarks': 'Delivered via truck'
        }
        resp = self.client.post(reverse('supplies:stock_in'), data)
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(self.paper.current_stock, 40)

    def test_stock_out_post_view_validation(self):
        """Posting stock-out exceeding available stock shows form error."""
        services.stock_in(self.paper, quantity=10, processed_by=self.admin_user)
        data = {
            'supply': self.paper.pk,
            'quantity': 15,  # Exceeds available 10
            'transaction_date': timezone.now().date(),
            'department': self.dept_acct.pk,
            'purpose': 'Class tests'
        }
        resp = self.client.post(reverse('supplies:stock_out'), data)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Insufficient stock")
        self.assertEqual(self.paper.current_stock, 10)

    def test_stock_adjustment_post_view(self):
        """Posting valid inventory adjustment updates stock."""
        services.stock_in(self.paper, quantity=20, processed_by=self.admin_user)
        data = {
            'supply': self.paper.pk,
            'adjustment_type': SupplyTransaction.TransactionType.ADJUSTMENT_OUT,
            'quantity': 2,
            'purpose': 'Defective reams discarded',
            'transaction_date': timezone.now().date()
        }
        resp = self.client.post(reverse('supplies:stock_adjust'), data)
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(self.paper.current_stock, 18)

    def test_supply_deletion_guarded_when_transactions_exist(self):
        """Posting to SupplyDeleteView fails when transactions exist."""
        services.stock_in(self.paper, quantity=10, processed_by=self.admin_user)
        resp = self.client.post(reverse('supplies:supply_delete', kwargs={'supply_code': self.paper.supply_code}))
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(Supply.objects.filter(pk=self.paper.pk).exists())

    def test_supply_deletion_succeeds_when_no_transactions(self):
        """Supply with zero transactions can be cleanly deleted."""
        clean_sup = Supply.objects.create(
            item_name='Temporary Marker',
            category=self.cat_paper,
            unit=Supply.Unit.PIECE,
            created_by=self.admin_user
        )
        resp = self.client.post(reverse('supplies:supply_delete', kwargs={'supply_code': clean_sup.supply_code}))
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(Supply.objects.filter(pk=clean_sup.pk).exists())


class CrossAppIntegrationTests(SupplyBaseTestCase):
    """Tests cross-app integration with Dashboard, My Accountability, and Employee profiles."""

    def setUp(self):
        super().setUp()
        self.client = Client()

    def test_dashboard_low_stock_indicator(self):
        """Dashboard displays low stock indicator when supplies fall below threshold."""
        self.client.force_login(self.admin_user)

        # Initial paper is at 0 stock (reorder_level=10) -> Low Stock Count = 1
        resp = self.client.get(reverse('dashboard'))
        self.assertEqual(resp.status_code, 200)
        self.assertIn('low_stock_supplies_count', resp.context)
        self.assertEqual(resp.context['low_stock_supplies_count'], 1)
        self.assertContains(resp, "Supply Replenishment Alert")

    def test_faculty_my_accountability_shows_consumable_issuances(self):
        """My Accountability page displays consumables issued to the logged-in faculty employee."""
        self.client.force_login(self.faculty_user)

        # Issue stock to this faculty member
        services.stock_in(self.paper, quantity=50, processed_by=self.admin_user)
        services.stock_out(
            self.paper,
            quantity=3,
            processed_by=self.admin_user,
            department=self.dept_acct,
            employee=self.faculty_emp,
            purpose='Midterm test questionnaires'
        )

        resp = self.client.get(reverse('assignments:my_accountability'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Bond Paper A4')
        self.assertContains(resp, '3 Ream')
        self.assertContains(resp, 'Midterm test questionnaires')

    def test_employee_detail_shows_consumable_issuances(self):
        """Employee detail view in organizations app lists recent consumable issuances."""
        self.client.force_login(self.admin_user)

        services.stock_in(self.paper, quantity=30, processed_by=self.admin_user)
        services.stock_out(
            self.paper,
            quantity=2,
            processed_by=self.admin_user,
            department=self.dept_acct,
            employee=self.faculty_emp,
            purpose='Syllabus printing'
        )

        resp = self.client.get(reverse('organizations:employee_detail', kwargs={'pk': self.faculty_emp.pk}))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Recent Consumable Supply Issuances')
        self.assertContains(resp, 'Bond Paper A4')
        self.assertContains(resp, 'Syllabus printing')
