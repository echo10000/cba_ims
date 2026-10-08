from django.views import View
from django.views.generic import ListView, DetailView, FormView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse, HttpResponseBadRequest, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone

from apps.inventory.models import Asset, AssetCategory
from .models import StudentReservation
from .forms import PublicStudentReservationForm
from . import services
from .security import mask_contact_info


class CustodianRequiredMixin(LoginRequiredMixin):
    """
    Enforces Administrator / Property Custodian authorization for student reservation office actions.
    Non-custodian users (Faculty, Students, Chairs, Deans) are denied access.
    """
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        is_admin = getattr(request.user, 'is_admin', False) or getattr(request.user, 'role', '') == 'ADMIN'
        if not is_admin:
            raise PermissionDenied("You do not have administrative authority to manage student equipment reservations.")
        return super().dispatch(request, *args, **kwargs)


# ==============================================================================
# PUBLIC VIEWS (STUDENTS) - NO LOGIN REQUIRED
# ==============================================================================

class PublicReservationSubmitView(View):
    """
    Public endpoint for student equipment reservation submission.
    No login required. Applies server-side validation and rate limiting.
    """
    def post(self, request, *args, **kwargs):
        form = PublicStudentReservationForm(request.POST)
        if not form.is_valid():
            return JsonResponse({
                'success': False,
                'errors': form.errors.get_json_data()
            }, status=400)

        data = form.cleaned_data
        try:
            reservation = services.submit_reservation(
                student_id=data['student_id'],
                student_name=data['student_name'],
                course_year_section=data['course_year_section'],
                email=data['email'],
                contact_number=data['contact_number'],
                category=data['category'],
                requested_pickup=data['requested_pickup'],
                requested_return=data['requested_return'],
                purpose=data['purpose'],
                room_venue=data.get('room_venue', ''),
                equipment_type=data.get('equipment_type', ''),
                remarks='',
                created_by=request.user if request.user.is_authenticated else None,
                request=request
            )
            return JsonResponse({
                'success': True,
                'reservation_id': reservation.pk,
                'lookup_token': reservation.lookup_token,
                'status': reservation.status,
                'message': "Reservation submitted successfully. Please save your lookup token to track status."
            }, status=201)
        except ValidationError as e:
            return JsonResponse({
                'success': False,
                'errors': e.message_dict if hasattr(e, 'message_dict') else {'__all__': [str(e)]}
            }, status=400)


class PublicReservationLookupView(View):
    """
    Public endpoint for tracking reservation status via secure lookup token.
    Student ID is NEVER used as a lookup key to protect student privacy.
    Masks student contact information in response.
    """
    def get(self, request, token, *args, **kwargs):
        try:
            reservation = services.get_reservation_by_token(token)
        except ValidationError as e:
            return JsonResponse({
                'success': False,
                'error': str(e)
            }, status=404)

        masked_email, masked_phone = mask_contact_info(reservation.email, reservation.contact_number)

        payload = {
            'success': True,
            'reservation_id': reservation.pk,
            'lookup_token': reservation.lookup_token,
            'status': reservation.status,
            'status_display': reservation.get_status_display(),
            'student_name': reservation.student_name,
            'course_year_section': reservation.course_year_section,
            'masked_email': masked_email,
            'masked_phone': masked_phone,
            'category_name': reservation.category.name,
            'equipment_type': reservation.equipment_type,
            'requested_pickup': reservation.requested_pickup.isoformat(),
            'requested_return': reservation.requested_return.isoformat(),
            'purpose': reservation.purpose,
            'room_venue': reservation.room_venue,
            'grace_period_minutes': reservation.grace_period_minutes,
            'pickup_deadline': reservation.pickup_deadline.isoformat() if reservation.pickup_deadline else None,
            'is_pickup_expired': reservation.is_pickup_expired,
            'is_overdue': reservation.is_overdue,
            'is_id_in_custody': reservation.is_id_in_custody,
            'allocated_asset': {
                'asset_code': reservation.asset.asset_code,
                'item_name': reservation.asset.item_name,
            } if reservation.asset else None,
            'created_at': reservation.created_at.isoformat(),
        }
        return JsonResponse(payload)


# ==============================================================================
# CUSTODIAN BACKEND VIEWS (ADMINISTRATOR ONLY)
# ==============================================================================

class CustodianReservationListView(CustodianRequiredMixin, ListView):
    """
    Office management queue of student reservations for Property Custodians.
    """
    model = StudentReservation
    context_object_name = 'reservations'
    paginate_by = 25

    def get_queryset(self):
        services.auto_expire_uncollected_reservations()
        qs = StudentReservation.objects.select_related(
            'category', 'asset', 'reviewed_by', 'released_by', 'returned_to'
        )
        status_filter = self.request.GET.get('status')
        if status_filter:
            qs = qs.filter(status=status_filter)
        return qs


class CustodianReservationDetailView(CustodianRequiredMixin, DetailView):
    """
    Detail view of a specific student reservation for Custodian inspection and actions.
    """
    model = StudentReservation
    context_object_name = 'reservation'

    def get_queryset(self):
        services.auto_expire_uncollected_reservations()
        return StudentReservation.objects.select_related(
            'category', 'asset', 'reviewed_by', 'released_by', 'returned_to',
            'guard_recorded_by', 'cba_inspected_by', 'id_returned_by'
        )
