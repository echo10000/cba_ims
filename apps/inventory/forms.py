from django import forms
from .models import AssetCategory, Brand, Asset
from apps.organizations.models import Department, Location


class AssetCategoryForm(forms.ModelForm):
    class Meta:
        model = AssetCategory
        fields = ['name', 'code', 'description', 'is_active']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Information Technology'}),
            'code': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. IT'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Category scope and details...'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


class BrandForm(forms.ModelForm):
    class Meta:
        model = Brand
        fields = ['name', 'is_active']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Lenovo, Dell, Epson'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


class AssetForm(forms.ModelForm):
    class Meta:
        model = Asset
        fields = [
            # Basic Information
            'item_name', 'category', 'brand', 'model', 'description',
            # Identification
            'property_number', 'serial_number',
            # Location
            'department', 'current_location',
            # Acquisition
            'acquisition_date', 'acquisition_cost', 'supplier',
            # Condition & Status
            'condition', 'status', 'remarks',
            # Media
            'asset_image',
        ]
        widgets = {
            'item_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g. ThinkPad L14 Gen 3 Laptop, Epson L3210 Printer'
            }),
            'category': forms.Select(attrs={'class': 'form-select'}),
            'brand': forms.Select(attrs={'class': 'form-select'}),
            'model': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. 21C1S00K00'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Technical specifications, color, accessories...'}),
            
            'property_number': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g. NORSU-CBA-2026-00482 (Leave blank if none)'
            }),
            'serial_number': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Manufacturer serial number (Leave blank if none)'
            }),
            
            'department': forms.Select(attrs={'class': 'form-select'}),
            'current_location': forms.Select(attrs={'class': 'form-select'}),
            
            'acquisition_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'acquisition_cost': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01',
                'min': '0',
                'placeholder': '0.00'
            }),
            'supplier': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Supplier or Vendor Company'}),
            
            'condition': forms.Select(attrs={'class': 'form-select'}),
            'status': forms.Select(attrs={'class': 'form-select'}),
            'remarks': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'Additional operational remarks...'}),
            
            'asset_image': forms.FileInput(attrs={
                'class': 'form-control',
                'accept': 'image/*',
                'capture': 'environment'  # Enables mobile phone rear camera capture
            }),
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        
        # Populate active foreign keys
        self.fields['category'].queryset = AssetCategory.objects.filter(is_active=True)
        self.fields['brand'].queryset = Brand.objects.filter(is_active=True)
        self.fields['department'].queryset = Department.objects.filter(is_active=True)
        self.fields['current_location'].queryset = Location.objects.filter(is_active=True)

        # On create, default status to AVAILABLE
        if not self.instance.pk:
            self.fields['status'].initial = Asset.Status.AVAILABLE
            self.fields['condition'].initial = Asset.Condition.NEW

        # If user is Department Chair, restrict department selection to their assigned department
        if user and getattr(user, 'role', '') == 'DEPT_CHAIR':
            if hasattr(user, 'employee_profile') and user.employee_profile.department:
                chair_dept = user.employee_profile.department
                self.fields['department'].queryset = Department.objects.filter(pk=chair_dept.pk)
                self.fields['department'].initial = chair_dept

    def clean_acquisition_cost(self):
        cost = self.cleaned_data.get('acquisition_cost')
        if cost is not None and cost < 0:
            raise forms.ValidationError("Acquisition cost cannot be negative.")
        return cost

    def clean_property_number(self):
        prop_num = self.cleaned_data.get('property_number')
        if prop_num:
            prop_num = prop_num.strip()
            qs = Asset.objects.filter(property_number__iexact=prop_num)
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise forms.ValidationError(f"An asset with property number '{prop_num}' already exists.")
        return prop_num


class AssetVerificationForm(forms.Form):
    """Form for physical inventory verification entry."""
    observed_department = forms.ModelChoiceField(
        queryset=Department.objects.filter(is_active=True),
        widget=forms.Select(attrs={'class': 'form-select'}),
        label='Physically Observed Department'
    )
    observed_location = forms.ModelChoiceField(
        queryset=Location.objects.filter(is_active=True),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'}),
        label='Physically Observed Location (Room / Office)'
    )
    observed_condition = forms.ChoiceField(
        choices=Asset.Condition.choices,
        widget=forms.Select(attrs={'class': 'form-select'}),
        label='Observed Physical Condition'
    )
    remarks = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 3,
            'placeholder': 'Discrepancy observations, physical tag status, condition notes...'
        }),
        label='Verification Remarks / Notes'
    )

    def __init__(self, *args, initial_asset=None, **kwargs):
        super().__init__(*args, **kwargs)
        if initial_asset:
            # Prefill observed values with current expected values as convenient default
            if not self.is_bound:
                self.fields['observed_department'].initial = initial_asset.department
                self.fields['observed_location'].initial = initial_asset.current_location
                self.fields['observed_condition'].initial = initial_asset.condition


class AssetCodeLookupForm(forms.Form):
    """Manual fallback form for looking up an asset by its code."""
    asset_code = forms.CharField(
        max_length=50,
        widget=forms.TextInput(attrs={
            'class': 'form-control form-control-lg font-monospace text-uppercase text-center',
            'placeholder': 'e.g. CBA-IT-00001',
            'autocomplete': 'off',
            'autofocus': 'autofocus',
        }),
        label='Enter Asset Code'
    )

    def clean_asset_code(self):
        code = self.cleaned_data.get('asset_code', '').strip().upper()
        if not code:
            raise forms.ValidationError("Please enter a valid asset code.")
        return code

