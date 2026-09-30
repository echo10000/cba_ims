from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse_lazy
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.views.generic import ListView, CreateView, UpdateView, DetailView, View
from django.db.models import Q
from .models import Department, Location, Employee
from .forms import DepartmentForm, LocationForm, EmployeeForm

class AdminRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    def test_func(self):
        return self.request.user.is_authenticated and getattr(self.request.user, 'is_admin', False)

# Department Views
class DepartmentListView(LoginRequiredMixin, ListView):
    model = Department
    template_name = 'organizations/department_list.html'
    context_object_name = 'departments'
    paginate_by = 20
    
    def get_queryset(self):
        queryset = super().get_queryset()
        q = self.request.GET.get('q')
        status = self.request.GET.get('status')
        if q:
            queryset = queryset.filter(Q(name__icontains=q) | Q(code__icontains=q))
        if status == 'active':
            queryset = queryset.filter(is_active=True)
        elif status == 'inactive':
            queryset = queryset.filter(is_active=False)
        return queryset

class DepartmentCreateView(AdminRequiredMixin, CreateView):
    model = Department
    form_class = DepartmentForm
    template_name = 'organizations/department_form.html'
    success_url = reverse_lazy('organizations:department_list')
    
    def form_valid(self, form):
        messages.success(self.request, "Department created successfully.")
        return super().form_valid(form)

class DepartmentUpdateView(AdminRequiredMixin, UpdateView):
    model = Department
    form_class = DepartmentForm
    template_name = 'organizations/department_form.html'
    success_url = reverse_lazy('organizations:department_list')
    
    def form_valid(self, form):
        messages.success(self.request, "Department updated successfully.")
        return super().form_valid(form)

class DepartmentToggleActiveView(AdminRequiredMixin, View):
    def post(self, request, pk):
        department = get_object_or_404(Department, pk=pk)
        department.is_active = not department.is_active
        department.save()
        status = "activated" if department.is_active else "deactivated"
        messages.success(request, f"Department {status} successfully.")
        return redirect('organizations:department_list')

# Location Views
class LocationListView(LoginRequiredMixin, ListView):
    model = Location
    template_name = 'organizations/location_list.html'
    context_object_name = 'locations'
    paginate_by = 20
    
    def get_queryset(self):
        queryset = super().get_queryset()
        q = self.request.GET.get('q')
        status = self.request.GET.get('status')
        if q:
            queryset = queryset.filter(
                Q(name__icontains=q) | 
                Q(building__icontains=q) | 
                Q(room_number__icontains=q)
            )
        if status == 'active':
            queryset = queryset.filter(is_active=True)
        elif status == 'inactive':
            queryset = queryset.filter(is_active=False)
        return queryset

class LocationCreateView(AdminRequiredMixin, CreateView):
    model = Location
    form_class = LocationForm
    template_name = 'organizations/location_form.html'
    success_url = reverse_lazy('organizations:location_list')
    
    def form_valid(self, form):
        messages.success(self.request, "Location created successfully.")
        return super().form_valid(form)

class LocationUpdateView(AdminRequiredMixin, UpdateView):
    model = Location
    form_class = LocationForm
    template_name = 'organizations/location_form.html'
    success_url = reverse_lazy('organizations:location_list')
    
    def form_valid(self, form):
        messages.success(self.request, "Location updated successfully.")
        return super().form_valid(form)

class LocationToggleActiveView(AdminRequiredMixin, View):
    def post(self, request, pk):
        location = get_object_or_404(Location, pk=pk)
        location.is_active = not location.is_active
        location.save()
        status = "activated" if location.is_active else "deactivated"
        messages.success(request, f"Location {status} successfully.")
        return redirect('organizations:location_list')

# Employee Views
class EmployeeListView(LoginRequiredMixin, ListView):
    model = Employee
    template_name = 'organizations/employee_list.html'
    context_object_name = 'employees'
    paginate_by = 20
    
    def get_queryset(self):
        queryset = super().get_queryset()
        q = self.request.GET.get('q')
        status = self.request.GET.get('status')
        
        if q:
            queryset = queryset.filter(
                Q(first_name__icontains=q) | 
                Q(last_name__icontains=q) | 
                Q(employee_id__icontains=q) |
                Q(email__icontains=q)
            )
            
        if status == 'active':
            queryset = queryset.filter(is_active=True)
        elif status == 'inactive':
            queryset = queryset.filter(is_active=False)
            
        # Role-based viewing logic
        user = self.request.user
        if getattr(user, 'is_admin', False) or getattr(user, 'role', '') == 'DEAN':
            pass
        elif getattr(user, 'role', '') == 'DEPT_CHAIR':
            if hasattr(user, 'employee_profile') and user.employee_profile.department:
                queryset = queryset.filter(department=user.employee_profile.department)
            else:
                queryset = queryset.none()
        else:
            if hasattr(user, 'employee_profile'):
                queryset = queryset.filter(pk=user.employee_profile.pk)
            else:
                queryset = queryset.none()
                
        return queryset

class EmployeeCreateView(AdminRequiredMixin, CreateView):
    model = Employee
    form_class = EmployeeForm
    template_name = 'organizations/employee_form.html'
    success_url = reverse_lazy('organizations:employee_list')
    
    def form_valid(self, form):
        messages.success(self.request, "Employee created successfully.")
        return super().form_valid(form)

class EmployeeUpdateView(AdminRequiredMixin, UpdateView):
    model = Employee
    form_class = EmployeeForm
    template_name = 'organizations/employee_form.html'
    success_url = reverse_lazy('organizations:employee_list')
    
    def form_valid(self, form):
        messages.success(self.request, "Employee updated successfully.")
        return super().form_valid(form)

class EmployeeDetailView(LoginRequiredMixin, DetailView):
    model = Employee
    template_name = 'organizations/employee_detail.html'
    context_object_name = 'employee'

    def get_object(self, queryset=None):
        emp = super().get_object(queryset)
        user = self.request.user
        
        # Admin and Dean can view any accountability profile
        if getattr(user, 'is_admin', False) or getattr(user, 'role', '') == 'DEAN':
            return emp

        # Department Chair: restricted to their department
        if getattr(user, 'role', '') == 'DEPT_CHAIR':
            chair_dept = getattr(getattr(user, 'employee_profile', None), 'department', None)
            if chair_dept and emp.department == chair_dept:
                return emp
            raise PermissionDenied("You can only view accountability profiles within your department.")

        # Faculty: strictly restricted to their own profile
        if getattr(user, 'role', '') == 'FACULTY':
            if hasattr(user, 'employee_profile') and user.employee_profile.pk == emp.pk:
                return emp
            raise PermissionDenied("You can only view your own accountability profile.")

        raise PermissionDenied("Access denied.")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        emp = self.object
        context['active_assignments'] = emp.assignments.filter(
            status='ACTIVE'
        ).select_related('asset', 'asset__category', 'asset__brand', 'asset__current_location')
        context['assignment_history'] = emp.assignments.filter(
            status='RETURNED'
        ).select_related('asset', 'asset__category', 'assigned_by', 'returned_by').order_by('-returned_date', '-created_at')
        context['recent_supply_issuances'] = emp.supply_issuances.select_related(
            'supply', 'supply__category', 'supply__brand', 'processed_by'
        ).order_by('-transaction_date', '-created_at')[:15]
        return context

class EmployeeToggleActiveView(AdminRequiredMixin, View):
    def post(self, request, pk):
        employee = get_object_or_404(Employee, pk=pk)
        employee.is_active = not employee.is_active
        employee.save()
        status = "activated" if employee.is_active else "deactivated"
        messages.success(request, f"Employee {status} successfully.")
        return redirect('organizations:employee_list')
