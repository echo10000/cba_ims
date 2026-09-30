from django.contrib import admin
from .models import Department, Location, Employee

@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'head', 'is_active')
    search_fields = ('name', 'code')
    list_filter = ('is_active',)

@admin.register(Location)
class LocationAdmin(admin.ModelAdmin):
    list_display = ('name', 'building', 'room_number', 'department', 'is_active')
    search_fields = ('name', 'building', 'room_number')
    list_filter = ('is_active', 'department')

@admin.register(Employee)
class EmployeeAdmin(admin.ModelAdmin):
    list_display = ('employee_id', 'last_name', 'first_name', 'department', 'position', 'is_active')
    search_fields = ('employee_id', 'last_name', 'first_name', 'email')
    list_filter = ('is_active', 'department')
