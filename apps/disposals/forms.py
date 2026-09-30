from django import forms
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout, Fieldset, Submit, HTML, Div, Field

from apps.inventory.models import Asset
from .models import AssetDisposal


class DisposalRequestForm(forms.Form):
    """Form for initiating a disposal request."""
    asset = forms.ModelChoiceField(
        queryset=Asset.objects.none(),
        widget=forms.Select(attrs={'class': 'form-select'}),
        help_text='Select the asset to dispose'
    )
    reason = forms.CharField(
        widget=forms.Textarea(attrs={'rows': 3, 'class': 'form-control'}),
        help_text='Justify why this asset should be removed from active inventory'
    )
    condition_at_disposal = forms.ChoiceField(
        choices=Asset.Condition.choices,
        widget=forms.Select(attrs={'class': 'form-select'}),
        help_text='Current physical condition of the asset'
    )
    remarks = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'rows': 2, 'class': 'form-control'}),
        help_text='Additional notes (optional)'
    )

    def __init__(self, *args, user=None, asset_instance=None, maintenance_ref=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.maintenance_ref = maintenance_ref

        # Populate asset choices — only non-disposed, eligible assets
        eligible_statuses = [
            Asset.Status.AVAILABLE,
            Asset.Status.ASSIGNED,
            Asset.Status.DAMAGED,
        ]
        qs = Asset.objects.filter(status__in=eligible_statuses).select_related(
            'category', 'department'
        ).order_by('asset_code')

        self.fields['asset'].queryset = qs
        self.fields['asset'].label_from_instance = lambda obj: f"{obj.asset_code} — {obj.item_name}"

        if asset_instance:
            self.fields['asset'].initial = asset_instance.pk
            self.fields['asset'].widget = forms.HiddenInput()
            self.fields['condition_at_disposal'].initial = asset_instance.condition

        self.helper = FormHelper()
        self.helper.form_method = 'post'
        self.helper.layout = Layout(
            Fieldset(
                'Disposal Request',
                'asset',
                'condition_at_disposal',
                'reason',
                'remarks',
            ),
            Div(
                Submit('submit', 'Submit Disposal Request', css_class='btn btn-danger'),
                HTML(' <a href="{% url \'disposals:pending_list\' %}" class="btn btn-secondary">Cancel</a>'),
                css_class='form-actions mt-3'
            )
        )


class DisposalApproveForm(forms.Form):
    """Form for approving a disposal request."""
    review_remarks = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'rows': 3, 'class': 'form-control'}),
        label='Approval Notes',
        help_text='Optional notes on the approval decision'
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_method = 'post'
        self.helper.layout = Layout(
            'review_remarks',
            Div(
                Submit('submit', 'Approve Disposal', css_class='btn btn-success'),
                HTML(' <a href="{{ disposal.get_absolute_url }}" class="btn btn-secondary">Cancel</a>'),
                css_class='form-actions mt-3'
            )
        )


class DisposalRejectForm(forms.Form):
    """Form for rejecting a disposal request."""
    review_remarks = forms.CharField(
        widget=forms.Textarea(attrs={'rows': 3, 'class': 'form-control'}),
        label='Rejection Reason',
        help_text='Explain why this disposal request is being rejected'
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_method = 'post'
        self.helper.layout = Layout(
            'review_remarks',
            Div(
                Submit('submit', 'Reject Request', css_class='btn btn-danger'),
                HTML(' <a href="{{ disposal.get_absolute_url }}" class="btn btn-secondary">Cancel</a>'),
                css_class='form-actions mt-3'
            )
        )


class DisposalCancelForm(forms.Form):
    """Form for cancelling a disposal request."""
    cancellation_reason = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'rows': 3, 'class': 'form-control'}),
        label='Cancellation Reason',
        help_text='Reason for cancelling this disposal request (optional)'
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_method = 'post'
        self.helper.layout = Layout(
            'cancellation_reason',
            Div(
                Submit('submit', 'Cancel Disposal', css_class='btn btn-warning'),
                HTML(' <a href="{{ disposal.get_absolute_url }}" class="btn btn-secondary">Back</a>'),
                css_class='form-actions mt-3'
            )
        )


class DisposalCompleteForm(forms.Form):
    """Form for recording the physical disposal execution."""
    disposal_method = forms.ChoiceField(
        choices=[('', '— Select method —')] + list(AssetDisposal.DisposalMethod.choices),
        widget=forms.Select(attrs={'class': 'form-select'}),
        help_text='How the asset was physically disposed'
    )
    disposal_date = forms.DateField(
        widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
        help_text='Date when physical disposal was executed'
    )
    recipient_or_destination = forms.CharField(
        required=False,
        max_length=300,
        widget=forms.TextInput(attrs={'class': 'form-control'}),
        label='Recipient / Destination',
        help_text='Buyer, recipient, or disposal destination (if applicable)'
    )
    reference_number = forms.CharField(
        required=False,
        max_length=200,
        widget=forms.TextInput(attrs={'class': 'form-control'}),
        label='Reference Number',
        help_text='Internal document or reference number (if applicable)'
    )
    proceeds_amount = forms.DecimalField(
        required=False,
        min_value=0,
        decimal_places=2,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0'}),
        label='Proceeds (₱)',
        help_text='Informational proceeds amount from sale/auction in PHP (optional)'
    )
    remarks = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'rows': 2, 'class': 'form-control'}),
        help_text='Additional notes on the disposal execution'
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from django.utils import timezone
        self.fields['disposal_date'].initial = timezone.now().date()

        self.helper = FormHelper()
        self.helper.form_method = 'post'
        self.helper.layout = Layout(
            Fieldset(
                'Physical Disposal Execution',
                'disposal_method',
                'disposal_date',
                'recipient_or_destination',
                'reference_number',
                'proceeds_amount',
                'remarks',
            ),
            Div(
                Submit('submit', 'Confirm Disposal — Mark Asset as DISPOSED', css_class='btn btn-danger'),
                HTML(' <a href="{{ disposal.get_absolute_url }}" class="btn btn-secondary">Cancel</a>'),
                css_class='form-actions mt-3'
            )
        )
