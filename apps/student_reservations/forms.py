import re
from datetime import timedelta
from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone
from apps.inventory.models import Asset, AssetCategory
from .models import StudentReservation


class PublicStudentReservationForm(forms.ModelForm):
    """
    Public reservation form for students.
    Students do not require accounts or passwords.
    Applies strict server-side validation and input sanitation.
    """
    class Meta:
        model = StudentReservation
        fields = [
            'student_id',
            'student_name',
            'course_year_section',
            'email',
            'contact_number',
            'category',
            'equipment_type',
            'requested_pickup',
            'requested_return',
            'purpose',
            'room_venue',
        ]
        widgets = {
            'requested_pickup': forms.DateTimeInput(attrs={'type': 'datetime-local'}),
            'requested_return': forms.DateTimeInput(attrs={'type': 'datetime-local'}),
            'purpose': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Only expose active, reservable categories in the public catalog
        self.fields['category'].queryset = AssetCategory.objects.filter(
            is_active=True,
            is_reservable=True
        )

    def clean_student_id(self):
        val = self.cleaned_data.get('student_id', '').strip()
        if not val:
            raise ValidationError("Student ID number is required.")
        # Common university student ID pattern: e.g. 2023-12345 or alphanumeric with hyphens
        if not re.match(r'^[A-Za-z0-9\-]{4,30}$', val):
            raise ValidationError("Please enter a valid Student ID format (e.g. 2023-12345).")
        return val

    def clean_student_name(self):
        val = self.cleaned_data.get('student_name', '').strip()
        if len(val) < 2:
            raise ValidationError("Please enter your full legal name.")
        if not re.match(r"^[A-Za-z\s\.\,\'\-]+$", val):
            raise ValidationError("Student name contains invalid characters.")
        return val

    def clean_course_year_section(self):
        val = self.cleaned_data.get('course_year_section', '').strip()
        if not val or len(val) < 2:
            raise ValidationError("Course, year, and section are required (e.g. BSBA 3-A).")
        return val

    def clean_contact_number(self):
        val = self.cleaned_data.get('contact_number', '').strip()
        # Allows formats like 09171234567, +639171234567, 0917-123-4567
        cleaned_phone = re.sub(r'[\s\-\(\)]', '', val)
        if not re.match(r'^\+?[0-9]{7,15}$', cleaned_phone):
            raise ValidationError("Please enter a valid mobile or phone number (e.g. 09171234567).")
        return val

    def clean(self):
        cleaned_data = super().clean()
        pickup = cleaned_data.get('requested_pickup')
        ret = cleaned_data.get('requested_return')
        category = cleaned_data.get('category')

        if pickup and ret:
            if pickup >= ret:
                self.add_error('requested_return', "Requested return time must be strictly after the pickup time.")

            now = timezone.now()
            # Allow up to 10 minutes clock skew in the past for immediate walk-in reservations
            if pickup < now - timedelta(minutes=10):
                self.add_error('requested_pickup', "Requested pickup time cannot be in the past.")

            # Reasonable borrowing duration limit (e.g. max 48 hours for student reservations)
            if (ret - pickup) > timedelta(hours=48):
                self.add_error('requested_return', "Single student reservations cannot exceed 48 consecutive hours.")

        if category:
            if not getattr(category, 'is_reservable', True) or not getattr(category, 'is_active', True):
                self.add_error('category', f"Category '{category.name}' is not currently available for reservations.")

        return cleaned_data


class CustodianApprovalForm(forms.Form):
    """
    Form for Custodian to allocate an asset and approve a student reservation.
    """
    asset = forms.ModelChoiceField(
        queryset=Asset.objects.none(),
        required=True,
        help_text="Select an available physical asset to allocate."
    )
    grace_period_minutes = forms.IntegerField(
        initial=15,
        min_value=5,
        max_value=120,
        required=True,
        help_text="Pickup grace period in minutes (default 15)."
    )
    remarks = forms.CharField(
        widget=forms.Textarea(attrs={'rows': 2}),
        required=False
    )

    def __init__(self, reservation, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from .services import get_available_assets_for_category
        available = get_available_assets_for_category(
            category=reservation.category,
            requested_pickup=reservation.requested_pickup,
            requested_return=reservation.requested_return,
            equipment_type=reservation.equipment_type,
            exclude_student_reservation_id=reservation.pk
        )
        pks = [a.pk for a in available]
        self.fields['asset'].queryset = Asset.objects.filter(pk__in=pks)


class CustodianRejectionForm(forms.Form):
    rejection_reason = forms.CharField(
        widget=forms.Textarea(attrs={'rows': 3}),
        required=True,
        help_text="Explanation for rejecting the reservation."
    )


class CustodianReleaseForm(forms.Form):
    condition_at_release = forms.ChoiceField(
        choices=Asset.Condition.choices,
        required=True,
        help_text="Physical condition snapshot upon equipment release."
    )
    id_deposited = forms.BooleanField(
        required=True,
        initial=True,
        label="Student School ID Verified and Deposited at CBA Office"
    )
    remarks = forms.CharField(
        widget=forms.Textarea(attrs={'rows': 2}),
        required=False
    )


class CustodianOfficeReturnForm(forms.Form):
    condition_at_return = forms.ChoiceField(
        choices=Asset.Condition.choices,
        required=True,
        help_text="Inspected physical condition upon return."
    )
    return_remarks = forms.CharField(
        widget=forms.Textarea(attrs={'rows': 2}),
        required=False
    )
    id_collected_now = forms.BooleanField(
        required=False,
        initial=True,
        label="Deposited School ID Handed Back to Student"
    )


class CustodianGuardReturnForm(forms.Form):
    guard_returned_at = forms.DateTimeField(
        widget=forms.DateTimeInput(attrs={'type': 'datetime-local'}),
        required=True,
        help_text="Actual documented handover datetime to security guard."
    )
    guard_handover_details = forms.CharField(
        max_length=255,
        required=True,
        help_text="Guard name, guard post, or logbook entry number."
    )
    remarks = forms.CharField(
        widget=forms.Textarea(attrs={'rows': 2}),
        required=False
    )

    def clean_guard_returned_at(self):
        val = self.cleaned_data.get('guard_returned_at')
        if val and val > timezone.now():
            raise ValidationError("Handover time to security guard cannot be in the future.")
        return val


class CustodianGuardInspectionForm(forms.Form):
    condition_at_return = forms.ChoiceField(
        choices=Asset.Condition.choices,
        required=True,
        help_text="Inspected physical condition of guard-returned equipment."
    )
    inspection_remarks = forms.CharField(
        widget=forms.Textarea(attrs={'rows': 2}),
        required=False,
        help_text="Inspection notes (e.g. cables, completeness, lamp hours)."
    )
    id_collected_now = forms.BooleanField(
        required=False,
        initial=False,
        label="Deposited School ID Handed Back to Student (if student is present)"
    )


class CustodianIDCollectionForm(forms.Form):
    remarks = forms.CharField(
        max_length=255,
        required=False,
        help_text="Remarks regarding school ID return (e.g. verified student signature)."
    )
