from django.urls import path
from . import views

app_name = 'student_reservations'

urlpatterns = [
    # Public endpoints
    path('request/', views.PublicReservationSubmitView.as_view(), name='public_request'),
    path('lookup/<str:token>/', views.PublicReservationLookupView.as_view(), name='public_lookup'),

    # Custodian office queue
    path('manage/', views.CustodianReservationListView.as_view(), name='custodian_list'),
    path('manage/<int:pk>/', views.CustodianReservationDetailView.as_view(), name='custodian_detail'),
]
