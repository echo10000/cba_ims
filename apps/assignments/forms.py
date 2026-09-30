from django import forms
from django.utils import timezone
from apps.inventory.models import Asset
from apps.organizations.models import Employee
from .models import AssetAssignment


class AssetAssignmentForm(forms.ModelForm):
    asset = forms.ModelChoiceField(
        queryset=Asset.objects.filter(status=Asset.Status.AVAILABLE).select_related('category', 'brand'),
        widget=forms.Select(attrs={'class': 'form-select'}),
        help_text='Only assets currently marked as AVAILABLE may be selected.'
    )
    employee = forms.ModelChoiceField(
        queryset=Employee.objects.filter(is_active=True).select_related('department'),
        widget=forms.Select(attrs={'class': 'form-select'}),
        help_text='Select active faculty member or staff recipient.'
    )

    class Meta:
        model = AssetAssignment
        fields = ['asset', 'employee', 'assigned_date', 'expected_return_date', 'purpose', 'remarks']
        widgets = {
            'assigned_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'expected_return_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'purpose': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g. Classroom Instruction, Department Office Work, Research'
            }),
            'remarks': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 2,
                'placeholder': 'Accessories included (charger, bag, cables), turnover remarks...'
            }),
        }

    def __init__(self, *args, **kwargs):
        preselected_asset = kwargs.pop('asset', None)
        super().__init__(*args, **kwargs)

        if not self.initial.get('assigned_date'):
            self.fields['assigned_date'].initial = timezone.now().date()

        # Format label choices for better usability
        self.fields['asset'].label_from_instance = lambda obj: (
            f"[{obj.asset_code}] {obj.item_name} ({obj.category.code}) - {obj.get_condition_display()}"
        )
        self.fields['employee'].label_from_instance = lambda emp: (
            f"{emp.full_name} ({emp.department.code if emp.department else 'No Dept'}) - {emp.position or 'Staff'}"
        )

        if preselected_asset:
            # If a specific asset is preselected, ensure it is in the queryset even if its status is being queried
            self.fields['asset'].queryset = Asset.objects.filter(pk=preselected_asset.pk)
            self.fields['asset'].initial = preselected_asset


class AssetReturnForm(forms.Form):
    returned_date = forms.DateField(
        initial=timezone.now,
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
        help_text='Date equipment was received and verified.'
    )
    condition_at_return = forms.ChoiceField(
        choices=Asset.Condition.choices,
        widget=forms.Select(attrs={'class': 'form-select'}),
        help_text='Physical inspection condition upon return.'
    )
    remarks = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 3,
            'placeholder': 'Inspection notes (e.g. Returned with all original accessories, scratches on lid...)'
        })
    )
