from django.contrib.auth.models import AbstractUser
from django.db import models

class User(AbstractUser):
    class Role(models.TextChoices):
        ADMIN = 'ADMIN', 'System Administrator'
        DEAN = 'DEAN', 'Dean'
        DEPT_CHAIR = 'DEPT_CHAIR', 'Department Chair'
        FACULTY = 'FACULTY', 'Faculty / Staff'
    
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.FACULTY)
    
    class Meta:
        ordering = ['last_name', 'first_name']
    
    def __str__(self):
        return self.get_full_name() or self.username
    
    @property
    def is_admin(self):
        return self.role == self.Role.ADMIN or self.is_superuser
    
    @property
    def is_dean(self):
        return self.role == self.Role.DEAN
    
    @property
    def is_dept_chair(self):
        return self.role == self.Role.DEPT_CHAIR
    
    @property
    def is_faculty(self):
        return self.role == self.Role.FACULTY
