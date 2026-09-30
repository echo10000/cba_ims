from django import forms
from django.utils import timezone
from apps.inventory.models import Asset
from apps.organizations.models import Department, Location
from .models import AssetTransfer


class AssetTransferRequestForm(forms.ModelForm):
    asset = forms.ModelChoiceField(
        queryset=Asset.objects.filter(
            status__in=[Asset.Status.AVAILABLE, Asset.Status.ASSIGNED]
        ).select_related('department', 'current_location', 'category'),
        widget=forms.Select(attrs={'class': 'form-select'}),
        help_text='Only assets currently AVAILABLE or ASSIGNED may be transferred.'
    )
    to_department = forms.ModelChoiceField(
        queryset=Department.objects.filter(is_active=True),
        widget=forms.Select(attrs={'class': 'form-select', 'id': 'id_to_department'}),
        help_text='Target destination department.'
    )
    to_location = forms.ModelChoiceField(
        queryset=Location.objects.filter(is_active=True).select_related('department'),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select', 'id': 'id_to_location'}),
        help_text='Specific destination room/office (optional).'
    )

    class Meta:
        model = AssetTransfer
        fields = ['asset', 'to_department', 'to_location', 'transfer_date', 'reason', 'remarks']
        widgets = {
            'transfer_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'reason': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g. Office Relocation, Faculty Room Reassignment, Lab Expansion'
            }),
            'remarks': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 2,
                'placeholder': 'Carrier details, physical inspection on dispatch, accessories...'
            }),
        }

    def __init__(self, *args, **kwargs):
        preselected_asset = kwargs.pop('asset', None)
        super().__init__(*args, **kwargs)

        if not self.initial.get('transfer_date'):
            self.fields['transfer_date'].initial = timezone.now().date()

        self.fields['asset'].label_from_instance = lambda obj: (
            f"[{obj.asset_code}] {obj.item_name} ({obj.department.code}) - {obj.get_status_display()}"
        )
        self.fields['to_department'].label_from_instance = lambda d: f"{d.name} ({d.code})"
        self.fields['to_location'].label_from_instance = lambda loc: (
            f"{loc.name} - {loc.building or 'Main'}{f', Rm {loc.room_number}' if loc.room_number else ''} ({loc.department.code if loc.department else 'Common'})"
        )

        if preselected_asset:
            self.fields['asset'].queryset = Asset.objects.filter(pk=preselected_asset.pk)
            self.fields['asset'].initial = preselected_asset
            self.preselected_asset = preselected_asset
        else:
            self.preselected_asset = None

    def clean(self):
        cleaned_data = super().clean()
        asset = cleaned_data.get('asset') or self.preselected_asset
        to_department = cleaned_data.get('to_department')
        to_location = cleaned_data.get('to_location')

        if asset and to_department:
            # Prevent identical origin and destination
            if asset.department_id == to_department.pk and asset.current_location_id == (to_location.pk if to_location else None):
                self.add_error(
                    'to_location',
                    "Destination department and location must differ from the asset's current location."
                )

            # Prevent selecting a location belonging to another department
            if to_location and to_location.department_id and to_location.department_id != to_department.pk:
                self.add_error(
                    'to_location',
                    f"Selected location '{to_location.name}' belongs to {to_location.department.name}, not {to_department.name}."
                )

        return cleaned_data


class TransferActionForm(forms.Form):
    """Generic action form for approval, rejection, completion, or cancellation."""
    remarks = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 3,
            'placeholder': 'Add notes, inspection details, or justification...'
        })
    )
