from django import forms
from django.utils import timezone
from datetime import timedelta
from apps.inventory.models import Asset
from apps.organizations.models import Employee
from .models import AssetBorrowing
from . import services


class BorrowingRequestForm(forms.ModelForm):
    borrower = forms.ModelChoiceField(
        queryset=Employee.objects.filter(is_active=True).select_related('department'),
        required=False,
        label='Borrower / Responsible Person',
        widget=forms.Select(attrs={'class': 'form-select'})
    )

    class Meta:
        model = AssetBorrowing
        fields = ['asset', 'borrower', 'requested_start', 'requested_return', 'purpose', 'remarks']
        widgets = {
            'asset': forms.Select(attrs={'class': 'form-select'}),
            'requested_start': forms.DateTimeInput(
                attrs={'class': 'form-control', 'type': 'datetime-local'},
                format='%Y-%m-%dT%H:%M'
            ),
            'requested_return': forms.DateTimeInput(
                attrs={'class': 'form-control', 'type': 'datetime-local'},
                format='%Y-%m-%dT%H:%M'
            ),
            'purpose': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g. Guest lecture presentation, faculty research seminar...'
            }),
            'remarks': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 2,
                'placeholder': 'Optional details, venue, or special handling notes...'
            }),
        }

    def __init__(self, *args, user=None, initial_asset=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

        # Filter borrowable assets: available, not assigned, no pending transfers
        asset_qs = Asset.objects.filter(
            status=Asset.Status.AVAILABLE
        ).exclude(
            assignments__status='ACTIVE'
        ).exclude(
            transfers__status__in=['PENDING', 'APPROVED']
        ).select_related('category', 'brand', 'department', 'current_location').order_by('asset_code')

        # If an asset was specified via URL, ensure it is available in queryset
        if initial_asset:
            asset_qs = (asset_qs | Asset.objects.filter(pk=initial_asset.pk)).distinct()
            self.fields['asset'].initial = initial_asset

        self.fields['asset'].queryset = asset_qs
        self.fields['asset'].label_from_instance = lambda obj: (
            f"{obj.asset_code} - {obj.item_name} ({obj.department.code}"
            f"{' • ' + obj.current_location.name if obj.current_location else ''})"
        )

        is_admin = getattr(user, 'is_admin', False) or getattr(user, 'role', '') == 'ADMIN'
        if not is_admin:
            # Faculty cannot choose another borrower identity
            if 'borrower' in self.fields:
                self.fields.pop('borrower')
        else:
            self.fields['borrower'].required = True
            if user and hasattr(user, 'employee_profile'):
                self.fields['borrower'].initial = user.employee_profile

    def clean(self):
        cleaned_data = super().clean()
        asset = cleaned_data.get('asset')
        requested_start = cleaned_data.get('requested_start')
        requested_return = cleaned_data.get('requested_return')

        # Determine effective borrower
        is_admin = getattr(self.user, 'is_admin', False) or getattr(self.user, 'role', '') == 'ADMIN'
        if is_admin:
            borrower = cleaned_data.get('borrower')
        else:
            borrower = getattr(self.user, 'employee_profile', None)

        if not borrower:
            self.add_error(None, "A linked employee profile is required to request equipment.")

        if requested_start and requested_return:
            if requested_start >= requested_return:
                self.add_error('requested_return', "Expected return time must be strictly after the start time.")

            # Validate start is not substantially in past
            now_buffer = timezone.now() - timedelta(minutes=15)
            if requested_start < now_buffer:
                self.add_error('requested_start', "Reservation start time cannot be in the past.")

            # Check reservation conflicts
            if asset:
                conflicts = services.check_reservation_conflict(asset, requested_start, requested_return)
                if self.instance and self.instance.pk:
                    conflicts = conflicts.exclude(pk=self.instance.pk)
                if conflicts.exists():
                    c = conflicts.first()
                    self.add_error(
                        'asset',
                        f"Asset '{asset.asset_code}' is already reserved/loaned to {c.borrower.full_name} "
                        f"from {c.requested_start:%Y-%m-%d %H:%M} to {c.requested_return:%Y-%m-%d %H:%M}."
                    )

        cleaned_data['borrower'] = borrower
        return cleaned_data


class BorrowingRejectionForm(forms.Form):
    rejection_reason = forms.CharField(
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 3,
            'placeholder': 'State the administrative reason for declining this request...',
            'required': True
        }),
        label='Reason for Rejection',
        help_text='This explanation will be permanently recorded in the borrowing log.'
    )


class BorrowingReleaseForm(forms.Form):
    condition_at_release = forms.ChoiceField(
        choices=Asset.Condition.choices,
        widget=forms.Select(attrs={'class': 'form-select'}),
        label='Physical Condition at Release',
        help_text='Verify condition before physical turnover to the borrower.'
    )
    remarks = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 2,
            'placeholder': 'Optional release remarks, accessories included (e.g. HDMI cable, power adapter)...'
        }),
        label='Release Notes / Inclusions'
    )

    def __init__(self, *args, initial_condition=None, **kwargs):
        super().__init__(*args, **kwargs)
        if initial_condition:
            self.fields['condition_at_release'].initial = initial_condition


class BorrowingReturnForm(forms.Form):
    condition_at_return = forms.ChoiceField(
        choices=Asset.Condition.choices,
        widget=forms.Select(attrs={'class': 'form-select'}),
        label='Inspected Condition upon Return',
        help_text='Inspect equipment carefully for damages, missing components, or wear.'
    )
    return_remarks = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 3,
            'placeholder': 'Record return findings, accessories accounted for, or any damage observations...'
        }),
        label='Return Inspection Notes'
    )

    def __init__(self, *args, initial_condition=None, **kwargs):
        super().__init__(*args, **kwargs)
        if initial_condition:
            self.fields['condition_at_return'].initial = initial_condition
