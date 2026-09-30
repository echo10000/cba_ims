from django import forms
from .models import Department, Location, Employee

class BootstrapFormMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            if not isinstance(field.widget, (forms.CheckboxInput, forms.RadioSelect)):
                field.widget.attrs['class'] = 'form-control'

class DepartmentForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Department
        fields = ['name', 'code', 'description', 'head', 'is_active']
        widgets = {
            'description': forms.Textarea(attrs={'rows': 3}),
        }

class LocationForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Location
        fields = ['name', 'building', 'floor', 'room_number', 'department', 'description', 'is_active']
        widgets = {
            'description': forms.Textarea(attrs={'rows': 3}),
        }

class EmployeeForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Employee
        fields = ['user', 'employee_id', 'first_name', 'last_name', 'position', 'contact_number', 'email', 'department', 'location', 'is_active']
