from django.test import TestCase, Client
from django.urls import reverse
from apps.accounts.models import User
from .models import AuditLog
from .utils import log_action


class AuditLogTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin = User.objects.create_user(
            username='admin_audit',
            password='Password123!',
            role=User.Role.ADMIN
        )
        self.faculty = User.objects.create_user(
            username='faculty_audit',
            password='Password123!',
            role=User.Role.FACULTY
        )

    def test_log_action_utility(self):
        log_action(
            user=self.admin,
            action='CREATED',
            instance=self.faculty,
            changes={'role': ['None', 'FACULTY']}
        )
        self.assertEqual(AuditLog.objects.count(), 1)
        log = AuditLog.objects.first()
        self.assertEqual(log.user, self.admin)
        self.assertEqual(log.action, 'CREATED')
        self.assertEqual(log.model_name, 'User')
        self.assertIn('role', log.changes)

    def test_audit_log_immutability_prevent_update(self):
        log = AuditLog.objects.create(
            user=self.admin,
            action='TEST_ACTION',
            model_name='TestModel',
            object_repr='Test representation'
        )
        with self.assertRaises(PermissionError):
            log.action = 'MODIFIED_ACTION'
            log.save()

    def test_audit_log_immutability_prevent_delete(self):
        log = AuditLog.objects.create(
            user=self.admin,
            action='TEST_ACTION',
            model_name='TestModel',
            object_repr='Test representation'
        )
        with self.assertRaises(PermissionError):
            log.delete()

    def test_audit_log_list_view_permissions(self):
        AuditLog.objects.create(
            user=self.admin,
            action='LOGIN',
            model_name='User',
            object_repr='admin_audit logged in'
        )

        # Faculty denied
        self.client.login(username='faculty_audit', password='Password123!')
        response = self.client.get(reverse('audit:audit_log_list'))
        self.assertEqual(response.status_code, 403)

        # Admin allowed
        self.client.login(username='admin_audit', password='Password123!')
        response = self.client.get(reverse('audit:audit_log_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'System Audit Logs')
        self.assertContains(response, 'LOGIN')
