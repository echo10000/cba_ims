from decimal import Decimal
from django import forms
from django.utils import timezone
from apps.inventory.models import Asset
from .models import AssetMaintenance


class MaintenanceReportForm(forms.ModelForm):
    """
    Form for filing an initial equipment maintenance/damage report.
    Scopes selectable assets based on user authorization:
    - Faculty: strictly restricted to equipment currently assigned to or borrowed by them.
    - Admin / Dean / Chair: authorized to select from durable assets.
    """
    class Meta:
        model = AssetMaintenance
        fields = ['asset', 'issue_title', 'issue_description', 'remarks']
        widgets = {
            'asset': forms.Select(attrs={'class': 'form-select'}),
            'issue_title': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g. Printer roller paper jam, laptop screen flickering...'
            }),
            'issue_description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 4,
                'placeholder': 'Describe what happened, error codes observed, or visible damage...'
            }),
            'remarks': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 2,
                'placeholder': 'Optional operational notes, location where item is kept, etc.'
            }),
        }

    def __init__(self, *args, user=None, initial_asset=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

        if user and getattr(user, 'role', '') == 'FACULTY':
            # Scoped to assets assigned to or borrowed by this faculty member
            self.fields['asset'].queryset = Asset.objects.filter(
                models.Q(assignments__employee__user=user, assignments__status='ACTIVE') |
                models.Q(borrowings__borrower__user=user, borrowings__status__in=['RELEASED', 'OVERDUE'])
            ).distinct().order_by('asset_code')
        elif user and getattr(user, 'role', '') == 'DEPT_CHAIR':
            chair_dept = getattr(getattr(user, 'employee_profile', None), 'department', None)
            if chair_dept:
                self.fields['asset'].queryset = Asset.objects.filter(department=chair_dept).order_by('asset_code')
            else:
                self.fields['asset'].queryset = Asset.objects.none()
        else:
            self.fields['asset'].queryset = Asset.objects.all().order_by('asset_code')

        if initial_asset:
            self.fields['asset'].initial = initial_asset
            self.fields['asset'].queryset = Asset.objects.filter(pk=initial_asset.pk)
            self.fields['asset'].widget.attrs['readonly'] = True


from django.db import models  # used in Q query above


class MaintenanceAssessmentForm(forms.Form):
    """Admin form for recording technical diagnosis and operational severity."""
    severity = forms.ChoiceField(
        choices=AssetMaintenance.Severity.choices,
        widget=forms.Select(attrs={'class': 'form-select'}),
        help_text='Assess operational severity to prioritize servicing.'
    )
    diagnosis = forms.CharField(
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 3,
            'placeholder': 'Technical root cause or inspection finding (e.g. blown capacitor, worn mechanical belt, malware)...'
        }),
        help_text='Detailed diagnostic finding.'
    )
    recommended_action = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 2,
            'placeholder': 'Proposed repair plan (e.g. send to authorized center, replace RAM module)...'
        }),
        help_text='Recommended technical action.'
    )
    remarks = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 2,
            'placeholder': 'Optional assessment remarks...'
        })
    )


class MaintenanceStartRepairForm(forms.Form):
    """Admin form for putting an assessed asset into active repair."""
    service_provider = forms.CharField(
        max_length=200,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'e.g. In-house IT, Epson Authorized Service Center, Columbia Technologies...'
        }),
        help_text='Facility, shop, or department handling the servicing.'
    )
    technician = forms.CharField(
        max_length=200,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Servicing technician name or contact info...'
        })
    )
    repair_started_at = forms.DateTimeField(
        required=False,
        initial=timezone.now,
        widget=forms.DateTimeInput(attrs={
            'class': 'form-control',
            'type': 'datetime-local'
        }),
        help_text='Dispatch or intake timestamp.'
    )
    remarks = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 2,
            'placeholder': 'Optional dispatch notes (e.g. sent with power cable and carrying case)...'
        })
    )


class MaintenanceCompleteRepairForm(forms.Form):
    """Admin form for completing maintenance and restoring equipment to service."""
    final_condition = forms.ChoiceField(
        choices=Asset.Condition.choices,
        initial=Asset.Condition.GOOD,
        widget=forms.Select(attrs={'class': 'form-select'}),
        help_text='Evaluated physical condition after repair testing.'
    )
    repair_completed_at = forms.DateTimeField(
        required=False,
        initial=timezone.now,
        widget=forms.DateTimeInput(attrs={
            'class': 'form-control',
            'type': 'datetime-local'
        }),
        help_text='Completion and testing timestamp.'
    )
    action_taken = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 3,
            'placeholder': 'Specific repairs conducted (e.g. cleaned printhead, soldered power lead, replaced roller kit)...'
        }),
        help_text='Summary of maintenance actions performed.'
    )
    parts_replaced = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 2,
            'placeholder': 'List of replaced components or parts...'
        }),
        help_text='Spare parts or modules used.'
    )
    repair_cost = forms.DecimalField(
        max_digits=12,
        decimal_places=2,
        required=False,
        min_value=Decimal('0.00'),
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'step': '0.01',
            'placeholder': '0.00'
        }),
        help_text='Total maintenance expense incurred in PHP.'
    )
    remarks = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 2,
            'placeholder': 'Final turnover or testing notes...'
        })
    )


class MaintenanceCancelForm(forms.Form):
    """Form for cancelling an open maintenance report."""
    cancellation_reason = forms.CharField(
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 3,
            'placeholder': 'State why this maintenance case is being cancelled (e.g. false alarm, issue resolved by user, duplicate case)...'
        }),
        help_text='Mandatory explanation for cancellation.'
    )


class MaintenanceForReplacementForm(forms.Form):
    """Admin confirmation form when repair is unviable and asset is marked for replacement."""
    remarks = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 3,
            'placeholder': 'Document the reason why continued repair is unviable and why replacement is recommended...'
        }),
        help_text='Recommendation rationale.'
    )
