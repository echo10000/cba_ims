from django.test import TestCase, Client
from django.urls import reverse
from apps.accounts.models import User
from .models import Department, Location, Employee


class OrganizationModelTests(TestCase):
    def setUp(self):
        self.dept = Department.objects.create(
            name='Accountancy',
            code='ACCT',
            description='Department of Accountancy'
        )
        self.loc = Location.objects.create(
            name='Accounting Faculty Office',
            building='CBA Building',
            floor='3rd',
            room_number='302',
            department=self.dept
        )

    def test_department_str(self):
        self.assertEqual(str(self.dept), 'Accountancy')

    def test_location_str(self):
        self.assertIn('Accounting Faculty Office', str(self.loc))
        self.assertIn('CBA Building', str(self.loc))
        self.assertIn('Rm 302', str(self.loc))

    def test_employee_creation_and_full_name(self):
        user = User.objects.create_user(
            username='msantos',
            first_name='Maria',
            last_name='Santos',
            role=User.Role.FACULTY
        )
        emp = Employee.objects.create(
            user=user,
            employee_id='EMP-2026-001',
            first_name='Maria',
            last_name='Santos',
            position='Assistant Professor',
            department=self.dept,
            location=self.loc
        )
        self.assertEqual(emp.full_name, 'Maria Santos')
        self.assertEqual(str(emp), 'Santos, Maria')


class OrganizationViewsTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin = User.objects.create_user(
            username='admin_org',
            password='Password123!',
            role=User.Role.ADMIN
        )
        self.dept = Department.objects.create(
            name='Business Administration',
            code='BA',
            description='Department of Business Administration'
        )
        self.loc = Location.objects.create(
            name='Dean Office',
            building='CBA Main',
            floor='1st',
            room_number='101',
            department=self.dept
        )
        self.emp = Employee.objects.create(
            employee_id='EMP-100',
            first_name='John',
            last_name='Doe',
            position='Dean',
            department=self.dept,
            location=self.loc
        )

    def test_department_list_and_create(self):
        self.client.login(username='admin_org', password='Password123!')
        
        # List
        response = self.client.get(reverse('organizations:department_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Business Administration')

        # Create
        create_url = reverse('organizations:department_create')
        response = self.client.post(create_url, {
            'name': 'Hospitality Management',
            'code': 'HM',
            'description': 'Hospitality Management Department',
            'is_active': True,
        })
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Department.objects.filter(code='HM').exists())

    def test_location_list_and_create(self):
        self.client.login(username='admin_org', password='Password123!')
        
        response = self.client.get(reverse('organizations:location_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Dean Office')

        create_url = reverse('organizations:location_create')
        response = self.client.post(create_url, {
            'name': 'Computer Lab 1',
            'building': 'IT Wing',
            'floor': '2nd',
            'room_number': '201',
            'department': self.dept.pk,
            'is_active': True,
        })
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Location.objects.filter(name='Computer Lab 1').exists())

    def test_employee_list_and_detail(self):
        self.client.login(username='admin_org', password='Password123!')

        response = self.client.get(reverse('organizations:employee_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'John Doe')

        detail_response = self.client.get(reverse('organizations:employee_detail', kwargs={'pk': self.emp.pk}))
        self.assertEqual(detail_response.status_code, 200)
        self.assertContains(detail_response, 'Employee Accountability: John Doe')
