from django import forms
from django.utils import timezone
from .models import Supply, SupplyCategory, SupplyTransaction
from apps.inventory.models import Brand
from apps.organizations.models import Department, Location, Employee


class SupplyForm(forms.ModelForm):
    class Meta:
        model = Supply
        fields = ['item_name', 'category', 'brand', 'unit', 'reorder_level', 'description', 'is_active']
        widgets = {
            'item_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Bond Paper A4 (70gsm)'}),
            'category': forms.Select(attrs={'class': 'form-select'}),
            'brand': forms.Select(attrs={'class': 'form-select'}),
            'unit': forms.Select(attrs={'class': 'form-select'}),
            'reorder_level': forms.NumberInput(attrs={'class': 'form-control', 'min': '0'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Specifications, packaging details, or usage notes'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['category'].queryset = SupplyCategory.objects.filter(is_active=True)
        self.fields['brand'].queryset = Brand.objects.filter(is_active=True)
        self.fields['brand'].required = False


class SupplyCategoryForm(forms.ModelForm):
    class Meta:
        model = SupplyCategory
        fields = ['name', 'code', 'description', 'is_active']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Paper Products'}),
            'code': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. PAPER'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


class StockInForm(forms.Form):
    supply = forms.ModelChoiceField(
        queryset=Supply.objects.filter(is_active=True),
        widget=forms.Select(attrs={'class': 'form-select'}),
        label='Supply Item'
    )
    quantity = forms.IntegerField(
        min_value=1,
        initial=1,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'e.g. 50'}),
        label='Quantity Received'
    )
    transaction_date = forms.DateField(
        initial=timezone.now,
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
        label='Date Received'
    )
    reference_number = forms.CharField(
        max_length=100,
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. DR-2026-00128 / PO-0929'}),
        label='Delivery / Reference Number'
    )
    remarks = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'Supplier, delivery remarks, batch notes'}),
        label='Remarks'
    )

    def __init__(self, *args, preselected_supply=None, **kwargs):
        super().__init__(*args, **kwargs)
        if preselected_supply:
            self.fields['supply'].initial = preselected_supply
            self.fields['supply'].widget.attrs['class'] += ' bg-light'


class StockOutForm(forms.Form):
    supply = forms.ModelChoiceField(
        queryset=Supply.objects.filter(is_active=True),
        widget=forms.Select(attrs={'class': 'form-select'}),
        label='Supply Item'
    )
    quantity = forms.IntegerField(
        min_value=1,
        initial=1,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'e.g. 5'}),
        label='Quantity to Issue'
    )
    department = forms.ModelChoiceField(
        queryset=Department.objects.filter(is_active=True),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'}),
        label='Recipient Department'
    )
    location = forms.ModelChoiceField(
        queryset=Location.objects.filter(is_active=True),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'}),
        label='Destination Room / Office'
    )
    employee = forms.ModelChoiceField(
        queryset=Employee.objects.filter(is_active=True).select_related('department'),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'}),
        label='Receiving Personnel (Optional)'
    )
    purpose = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Midterm exam printing, faculty office usage'}),
        label='Purpose / Justification'
    )
    reference_number = forms.CharField(
        max_length=100,
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. ISS-2026-0182 / REQ-0412'}),
        label='Requisition / Issuance Slip #'
    )
    transaction_date = forms.DateField(
        initial=timezone.now,
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
        label='Issuance Date'
    )
    remarks = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'Additional notes'}),
        label='Remarks'
    )

    def __init__(self, *args, preselected_supply=None, **kwargs):
        super().__init__(*args, **kwargs)
        if preselected_supply:
            self.fields['supply'].initial = preselected_supply
            self.fields['supply'].widget.attrs['class'] += ' bg-light'


class StockAdjustmentForm(forms.Form):
    supply = forms.ModelChoiceField(
        queryset=Supply.objects.filter(is_active=True),
        widget=forms.Select(attrs={'class': 'form-select'}),
        label='Supply Item'
    )
    adjustment_type = forms.ChoiceField(
        choices=[
            (SupplyTransaction.TransactionType.ADJUSTMENT_IN, 'Adjustment In (+) - Physical Count Surplus / Recovered'),
            (SupplyTransaction.TransactionType.ADJUSTMENT_OUT, 'Adjustment Out (-) - Damage / Loss / Shrinkage / Count Deficit'),
        ],
        widget=forms.Select(attrs={'class': 'form-select'}),
        label='Adjustment Type'
    )
    quantity = forms.IntegerField(
        min_value=1,
        initial=1,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Quantity to adjust'}),
        label='Adjustment Quantity'
    )
    purpose = forms.CharField(
        required=True,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Physical inventory discrepancy correction, expired toner'}),
        label='Reason for Adjustment'
    )
    reference_number = forms.CharField(
        max_length=100,
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. AUDIT-2026-Q3 / INC-009'}),
        label='Audit / Memo Reference #'
    )
    transaction_date = forms.DateField(
        initial=timezone.now,
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
        label='Adjustment Date'
    )
    remarks = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'Supporting justification'}),
        label='Remarks'
    )

    def __init__(self, *args, preselected_supply=None, **kwargs):
        super().__init__(*args, **kwargs)
        if preselected_supply:
            self.fields['supply'].initial = preselected_supply
            self.fields['supply'].widget.attrs['class'] += ' bg-light'
