from django import forms
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm as BasePasswordChangeForm
from django.contrib.auth import get_user_model
from django.db import transaction
from apps.organizations.models import Department, Location, Employee

User = get_user_model()


class LoginForm(AuthenticationForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.update({'class': 'form-control'})


class UserCreateForm(forms.ModelForm):
    password1 = forms.CharField(label='Password', widget=forms.PasswordInput(attrs={'class': 'form-control'}))
    password2 = forms.CharField(label='Password confirmation', widget=forms.PasswordInput(attrs={'class': 'form-control'}))

    # Unified Employee Profile Fields
    create_employee_profile = forms.BooleanField(
        required=False,
        initial=True,
        label="Create & Link Employee Profile",
        help_text="Automatically creates an institutional custody profile so this user can be assigned equipment or submit borrowing requests.",
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )
    employee_id = forms.CharField(
        required=False,
        max_length=50,
        label="Employee ID",
        help_text="Institutional Employee/Faculty ID (e.g., EMP-FAC-003). Leave blank to auto-generate.",
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. EMP-FAC-003'})
    )
    position = forms.CharField(
        required=False,
        max_length=200,
        label="Position / Academic Title",
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Assistant Professor'})
    )
    department = forms.ModelChoiceField(
        queryset=Department.objects.none(),
        required=False,
        label="Department",
        help_text="Assigned academic department",
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    location = forms.ModelChoiceField(
        queryset=Location.objects.none(),
        required=False,
        label="Primary Office / Location",
        help_text="Designated room or laboratory",
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    contact_number = forms.CharField(
        required=False,
        max_length=50,
        label="Contact Number",
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. +63 912 345 6789'})
    )

    class Meta:
        model = User
        fields = ('username', 'email', 'first_name', 'last_name', 'role')
        widgets = {
            'username': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
            'role': forms.Select(attrs={'class': 'form-select'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['department'].queryset = Department.objects.filter(is_active=True).order_by('name')
        self.fields['location'].queryset = Location.objects.filter(is_active=True).order_by('name')

    def clean_password2(self):
        password1 = self.cleaned_data.get("password1")
        password2 = self.cleaned_data.get("password2")
        if password1 and password2 and password1 != password2:
            raise forms.ValidationError("Passwords don't match")
        return password2

    def clean_employee_id(self):
        emp_id = self.cleaned_data.get('employee_id')
        if emp_id:
            emp_id = emp_id.strip()
            if Employee.objects.filter(employee_id__iexact=emp_id).exists():
                raise forms.ValidationError(f"An employee with ID '{emp_id}' already exists.")
        return emp_id

    def save(self, commit=True):
        with transaction.atomic():
            user = super().save(commit=False)
            user.set_password(self.cleaned_data["password1"])
            if commit:
                user.save()

                should_create = self.cleaned_data.get('create_employee_profile')
                emp_id = self.cleaned_data.get('employee_id')
                dept = self.cleaned_data.get('department')
                loc = self.cleaned_data.get('location')
                pos = (self.cleaned_data.get('position') or '').strip()
                contact = (self.cleaned_data.get('contact_number') or '').strip()

                if should_create or emp_id or dept or loc or pos or contact:
                    if not emp_id:
                        prefix = 'FAC' if user.role == User.Role.FACULTY else ('CHAIR' if user.role == User.Role.DEPT_CHAIR else user.role)
                        base_id = f"EMP-{prefix}-{user.pk:04d}"
                        emp_id = base_id
                        counter = 1
                        while Employee.objects.filter(employee_id=emp_id).exists():
                            emp_id = f"{base_id}-{counter}"
                            counter += 1

                    if not pos:
                        if user.role == User.Role.FACULTY:
                            pos = 'Faculty Member'
                        elif user.role == User.Role.DEPT_CHAIR:
                            pos = 'Department Chairperson'
                        elif user.role == User.Role.DEAN:
                            pos = 'College Dean'

                    Employee.objects.update_or_create(
                        user=user,
                        defaults={
                            'employee_id': emp_id,
                            'first_name': user.first_name,
                            'last_name': user.last_name,
                            'email': user.email,
                            'position': pos,
                            'contact_number': contact,
                            'department': dept,
                            'location': loc,
                            'is_active': user.is_active,
                        }
                    )

            return user


class UserUpdateForm(forms.ModelForm):
    # Unified Employee Profile Fields
    employee_id = forms.CharField(
        required=False,
        max_length=50,
        label="Employee ID",
        help_text="Institutional Employee/Faculty ID. Leave blank if not linked.",
        widget=forms.TextInput(attrs={'class': 'form-control'})
    )
    position = forms.CharField(
        required=False,
        max_length=200,
        label="Position / Academic Title",
        widget=forms.TextInput(attrs={'class': 'form-control'})
    )
    department = forms.ModelChoiceField(
        queryset=Department.objects.none(),
        required=False,
        label="Department",
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    location = forms.ModelChoiceField(
        queryset=Location.objects.none(),
        required=False,
        label="Primary Office / Location",
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    contact_number = forms.CharField(
        required=False,
        max_length=50,
        label="Contact Number",
        widget=forms.TextInput(attrs={'class': 'form-control'})
    )

    class Meta:
        model = User
        fields = ('username', 'email', 'first_name', 'last_name', 'role', 'is_active')
        widgets = {
            'username': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
            'role': forms.Select(attrs={'class': 'form-select'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['department'].queryset = Department.objects.filter(is_active=True).order_by('name')
        self.fields['location'].queryset = Location.objects.filter(is_active=True).order_by('name')

        if self.instance and self.instance.pk and hasattr(self.instance, 'employee_profile'):
            profile = self.instance.employee_profile
            self.fields['employee_id'].initial = profile.employee_id
            self.fields['position'].initial = profile.position
            self.fields['department'].initial = profile.department
            self.fields['location'].initial = profile.location
            self.fields['contact_number'].initial = profile.contact_number

    def clean_employee_id(self):
        emp_id = self.cleaned_data.get('employee_id')
        if emp_id:
            emp_id = emp_id.strip()
            qs = Employee.objects.filter(employee_id__iexact=emp_id)
            if self.instance and hasattr(self.instance, 'employee_profile'):
                qs = qs.exclude(pk=self.instance.employee_profile.pk)
            if qs.exists():
                raise forms.ValidationError(f"An employee with ID '{emp_id}' already exists.")
        return emp_id

    def save(self, commit=True):
        with transaction.atomic():
            user = super().save(commit=commit)
            if commit:
                emp_id = self.cleaned_data.get('employee_id')
                dept = self.cleaned_data.get('department')
                loc = self.cleaned_data.get('location')
                pos = (self.cleaned_data.get('position') or '').strip()
                contact = (self.cleaned_data.get('contact_number') or '').strip()

                if hasattr(user, 'employee_profile'):
                    profile = user.employee_profile
                    if emp_id:
                        profile.employee_id = emp_id
                    profile.first_name = user.first_name
                    profile.last_name = user.last_name
                    profile.email = user.email
                    profile.position = pos
                    profile.department = dept
                    profile.location = loc
                    profile.contact_number = contact
                    profile.is_active = user.is_active
                    profile.save()
                elif emp_id or dept or loc or pos or contact:
                    if not emp_id:
                        prefix = 'FAC' if user.role == User.Role.FACULTY else ('CHAIR' if user.role == User.Role.DEPT_CHAIR else user.role)
                        base_id = f"EMP-{prefix}-{user.pk:04d}"
                        emp_id = base_id
                        counter = 1
                        while Employee.objects.filter(employee_id=emp_id).exists():
                            emp_id = f"{base_id}-{counter}"
                            counter += 1
                    Employee.objects.create(
                        user=user,
                        employee_id=emp_id,
                        first_name=user.first_name,
                        last_name=user.last_name,
                        email=user.email,
                        position=pos,
                        contact_number=contact,
                        department=dept,
                        location=loc,
                        is_active=user.is_active,
                    )

            return user


class PasswordChangeForm(BasePasswordChangeForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.update({'class': 'form-control'})
