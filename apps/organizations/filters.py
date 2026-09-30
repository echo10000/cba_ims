import django_filters
from .models import Employee, Department

class EmployeeFilter(django_filters.FilterSet):
    department = django_filters.ModelChoiceFilter(queryset=Department.objects.all())
    is_active = django_filters.BooleanFilter()
    
    class Meta:
        model = Employee
        fields = ['department', 'is_active']
