from datetime import timedelta
from django.views import View
from django.views.generic import ListView, DetailView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse, HttpResponseBadRequest, HttpResponseForbidden, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone
from django.contrib import messages

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
# PUBLIC STUDENT VIEWS — NO LOGIN REQUIRED
# ==============================================================================

class StudentCatalogView(View):
    """
    Public equipment catalog screen for students.
    Displays reservable categories, tracked physical asset counts, sample models,
    and interactive schedule-based availability checker.
    """
    def get(self, request, *args, **kwargs):
        categories = services.get_reservable_categories()

        # Build category summary cards
        catalog_cards = []
        for cat in categories:
            assets = services.get_reservable_assets(category=cat)
            total_count = assets.count()
            
            # Find distinct model names
            models_list = list(assets.exclude(model='').values_list('model', flat=True).distinct()[:3])
            models_preview = ", ".join(models_list) if models_list else f"{total_count} tracked units"

            # Check if any asset has an uploaded image
            asset_with_img = assets.filter(asset_image__isnull=False).exclude(asset_image='').first()
            sample_image_url = asset_with_img.asset_image.url if asset_with_img and asset_with_img.asset_image else None

            # Choose an appropriate icon
            cat_name_lower = cat.name.lower()
            if 'projector' in cat_name_lower or 'av' in cat.code.lower() or 'audio-visual' in cat_name_lower:
                icon = 'bi bi-projector'
            elif 'speaker' in cat_name_lower or 'sound' in cat_name_lower or 'audio' in cat_name_lower:
                icon = 'bi bi-speaker'
            elif 'laptop' in cat_name_lower or 'it' in cat.code.lower() or 'computer' in cat_name_lower:
                icon = 'bi bi-laptop'
            else:
                icon = 'bi bi-box-seam'

            catalog_cards.append({
                'category': cat,
                'total_units': total_count,
                'models_preview': models_preview,
                'sample_image_url': sample_image_url,
                'icon': icon,
            })

        # Default schedule for availability checker (today 1:00 PM - 5:00 PM or next round hour)
        now = timezone.localtime()
        default_pickup = (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
        default_return = default_pickup + timedelta(hours=3)

        default_pickup_str = default_pickup.strftime('%Y-%m-%dT%H:%M')
        default_return_str = default_return.strftime('%Y-%m-%dT%H:%M')

        # Initial availability data for default timeslot
        availability_data = []
        for cat in categories:
            avail_assets = services.get_available_assets_for_category(cat, default_pickup, default_return)
            tot_assets = services.get_reservable_assets(category=cat)
            models_list = list(tot_assets.exclude(model='').values_list('model', flat=True).distinct()[:2])
            sample_models = ", ".join(models_list) if models_list else "Standard CBA Inventory Items"

            availability_data.append({
                'category': cat,
                'total_count': tot_assets.count(),
                'available_count': len(avail_assets),
                'sample_models': sample_models,
            })

        context = {
            'categories': categories,
            'catalog_cards': catalog_cards,
            'default_pickup': default_pickup_str,
            'default_return': default_return_str,
            'pickup_display': default_pickup.strftime('%b %d, %Y %I:%M %p'),
            'return_display': default_return.strftime('%b %d, %Y %I:%M %p'),
            'pickup_raw': default_pickup_str,
            'return_raw': default_return_str,
            'duration_hours': 3,
            'availability_data': availability_data,
        }
        return render(request, 'student_reservations/catalog.html', context)


class CheckAvailabilityView(View):
    """
    HTMX endpoint for dynamic schedule-based availability checking.
    Calculates available units for each reservable category within [pickup, return].
    """
    def get(self, request, *args, **kwargs):
        pickup_str = request.GET.get('pickup', '').strip()
        return_str = request.GET.get('return', '').strip()

        if not pickup_str or not return_str:
            return render(request, 'student_reservations/partials/_availability_result.html', {
                'error': "Please enter both pickup and return date and time."
            })

        try:
            current_tz = timezone.get_current_timezone()
            pickup = timezone.datetime.fromisoformat(pickup_str)
            return_dt = timezone.datetime.fromisoformat(return_str)

            if timezone.is_naive(pickup):
                pickup = timezone.make_aware(pickup, current_tz)
            if timezone.is_naive(return_dt):
                return_dt = timezone.make_aware(return_dt, current_tz)
        except (ValueError, TypeError):
            return render(request, 'student_reservations/partials/_availability_result.html', {
                'error': "Invalid date and time format. Please select valid dates."
            })

        now = timezone.now()
        if pickup < now - timedelta(minutes=15):
            return render(request, 'student_reservations/partials/_availability_result.html', {
                'error': "Requested pickup time cannot be in the past."
            })

        if pickup >= return_dt:
            return render(request, 'student_reservations/partials/_availability_result.html', {
                'error': "Requested return time must be strictly after pickup time."
            })

        categories = services.get_reservable_categories()
        availability_data = []
        for cat in categories:
            avail_assets = services.get_available_assets_for_category(cat, pickup, return_dt)
            tot_assets = services.get_reservable_assets(category=cat)
            models_list = list(tot_assets.exclude(model='').values_list('model', flat=True).distinct()[:2])
            sample_models = ", ".join(models_list) if models_list else "Standard CBA Inventory Items"

            availability_data.append({
                'category': cat,
                'total_count': tot_assets.count(),
                'available_count': len(avail_assets),
                'sample_models': sample_models,
            })

        duration_hours = round((return_dt - pickup).total_seconds() / 3600, 1)

        context = {
            'error': None,
            'pickup_display': pickup.strftime('%b %d, %Y %I:%M %p'),
            'return_display': return_dt.strftime('%b %d, %Y %I:%M %p'),
            'pickup_raw': pickup_str,
            'return_raw': return_str,
            'duration_hours': duration_hours,
            'availability_data': availability_data,
        }
        return render(request, 'student_reservations/partials/_availability_result.html', context)


class PublicReservationSubmitView(View):
    """
    Public student reservation submission view and endpoint.
    GET: Renders mobile-friendly reservation form with optional prefilled category/dates.
    POST: Validates form, checks rate limiting, calls submit_reservation, and redirects to confirmation.
    Also maintains JSON API responses for programmatic requests.
    """
    def get(self, request, *args, **kwargs):
        initial_data = {}
        category_id = request.GET.get('category')
        if category_id:
            try:
                cat = AssetCategory.objects.get(pk=category_id, is_active=True, is_reservable=True)
                initial_data['category'] = cat
            except AssetCategory.DoesNotExist:
                pass

        pickup = request.GET.get('pickup')
        if pickup:
            initial_data['requested_pickup'] = pickup

        ret = request.GET.get('return')
        if ret:
            initial_data['requested_return'] = ret

        form = PublicStudentReservationForm(initial=initial_data)
        return render(request, 'student_reservations/reservation_form.html', {'form': form})

    def post(self, request, *args, **kwargs):
        is_json_request = (
            request.content_type == 'application/json' or
            request.headers.get('accept') == 'application/json' or
            request.headers.get('x-requested-with') == 'XMLHttpRequest'
        )

        form = PublicStudentReservationForm(request.POST)
        if not form.is_valid():
            if is_json_request:
                return JsonResponse({
                    'success': False,
                    'errors': form.errors.get_json_data()
                }, status=400)
            return render(request, 'student_reservations/reservation_form.html', {'form': form})

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

            if is_json_request:
                return JsonResponse({
                    'success': True,
                    'reservation_id': reservation.pk,
                    'lookup_token': reservation.lookup_token,
                    'status': reservation.status,
                    'message': "Reservation submitted successfully. Please save your lookup token to track status."
                }, status=201)

            messages.success(
                request,
                "Your reservation request was submitted successfully! Please save your tracking token."
            )
            return redirect('student_reservations:public_confirmation', token=reservation.lookup_token)

        except ValidationError as e:
            if is_json_request:
                return JsonResponse({
                    'success': False,
                    'errors': e.message_dict if hasattr(e, 'message_dict') else {'__all__': [str(e)]}
                }, status=400)

            if hasattr(e, 'message_dict'):
                for field, error_list in e.message_dict.items():
                    for err in error_list:
                        form.add_error(field if field in form.fields else None, err)
            else:
                form.add_error(None, str(e.message if hasattr(e, 'message') else e))

            return render(request, 'student_reservations/reservation_form.html', {'form': form})


class PublicReservationConfirmationView(View):
    """
    Public confirmation screen rendered immediately after a successful reservation submission.
    Displays the secure tracking token with one-click copy, summary particulars, and institutional checklist.
    """
    def get(self, request, token, *args, **kwargs):
        try:
            reservation = services.get_reservation_by_token(token)
        except ValidationError:
            messages.error(request, "Reservation not found.")
            return redirect('student_reservations:public_lookup_search')

        return render(request, 'student_reservations/confirmation.html', {
            'reservation': reservation,
        })


class PublicReservationLookupView(View):
    """
    Public endpoint and interface for tracking reservation status via secure lookup token.
    Student ID is NEVER used as a lookup key to protect student privacy.
    Masks student contact information in response.
    Supports both HTML web pages and JSON API consumers.
    """
    def get(self, request, token=None, *args, **kwargs):
        is_json_request = (
            request.headers.get('accept') == 'application/json' or
            request.GET.get('format') == 'json'
        )

        lookup_token = token or request.GET.get('token', '').strip()

        # If no token provided in URL or GET params:
        if not lookup_token:
            if is_json_request:
                return JsonResponse({'success': False, 'error': 'Lookup token is required.'}, status=400)
            return render(request, 'student_reservations/lookup.html', {
                'reservation': None,
                'token': '',
                'error': None,
            })

        # Token was supplied: retrieve reservation
        try:
            reservation = services.get_reservation_by_token(lookup_token)
        except ValidationError as e:
            if is_json_request:
                return JsonResponse({'success': False, 'error': str(e)}, status=404)
            return render(request, 'student_reservations/lookup.html', {
                'reservation': None,
                'token': lookup_token,
                'error': str(e),
            })

        masked_email, masked_phone = mask_contact_info(reservation.email, reservation.contact_number)

        # JSON response handling
        if is_json_request:
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

        # HTML response handling
        context = {
            'reservation': reservation,
            'masked_email': masked_email,
            'masked_phone': masked_phone,
            'token': lookup_token,
            'error': None,
        }

        # If HTMX request, render only the status card partial
        if request.headers.get('HX-Request'):
            return render(request, 'student_reservations/partials/_status_card.html', context)

        return render(request, 'student_reservations/lookup.html', context)


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
