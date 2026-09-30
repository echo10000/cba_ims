from django.db import models
from django.conf import settings
import uuid

class Department(models.Model):
    name = models.CharField(max_length=200, unique=True)
    code = models.CharField(max_length=20, unique=True, help_text='Short code e.g. BA, ACCT, HM')
    description = models.TextField(blank=True)
    head = models.ForeignKey('Employee', on_delete=models.SET_NULL, null=True, blank=True, related_name='headed_departments')
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['name']
    
    def __str__(self):
        return self.name

class Location(models.Model):
    name = models.CharField(max_length=200)
    building = models.CharField(max_length=200, blank=True)
    floor = models.CharField(max_length=50, blank=True)
    room_number = models.CharField(max_length=50, blank=True)
    department = models.ForeignKey(Department, on_delete=models.SET_NULL, null=True, blank=True, related_name='locations')
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['name']
        unique_together = ['building', 'room_number']  # only if both are non-empty
    
    def __str__(self):
        parts = [self.name]
        if self.building:
            parts.append(f'({self.building}')
            if self.room_number:
                parts.append(f'Rm {self.room_number})')
            else:
                parts.append(')')
        return ' '.join(parts)

class Employee(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='employee_profile')
    employee_id = models.CharField(max_length=50, unique=True, help_text='Employee/Faculty ID number')
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    position = models.CharField(max_length=200, blank=True)
    contact_number = models.CharField(max_length=50, blank=True)
    email = models.EmailField(blank=True)
    department = models.ForeignKey(Department, on_delete=models.SET_NULL, null=True, blank=True, related_name='employees')
    location = models.ForeignKey(Location, on_delete=models.SET_NULL, null=True, blank=True, related_name='employees', help_text='Primary office/room')
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['last_name', 'first_name']
    
    def __str__(self):
        return f'{self.last_name}, {self.first_name}'
    
    @property
    def full_name(self):
        return f'{self.first_name} {self.last_name}'

    def get_full_name(self):
        return self.full_name
