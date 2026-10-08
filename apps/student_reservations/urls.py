from django.urls import path
from . import views

app_name = 'student_reservations'

urlpatterns = [
    # Public student screens
    path('', views.StudentCatalogView.as_view(), name='catalog'),
    path('catalog/', views.StudentCatalogView.as_view(), name='catalog_alias'),
    path('check-availability/', views.CheckAvailabilityView.as_view(), name='check_availability'),
    path('request/', views.PublicReservationSubmitView.as_view(), name='public_request'),
    path('confirmed/<str:token>/', views.PublicReservationConfirmationView.as_view(), name='public_confirmation'),
    path('lookup/', views.PublicReservationLookupView.as_view(), name='public_lookup_search'),
    path('lookup/<str:token>/', views.PublicReservationLookupView.as_view(), name='public_lookup'),

    # Custodian office queue
    path('manage/', views.CustodianReservationListView.as_view(), name='custodian_list'),
    path('manage/<int:pk>/', views.CustodianReservationDetailView.as_view(), name='custodian_detail'),
]
