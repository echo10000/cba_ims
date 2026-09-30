from django.urls import path
from . import views

app_name = 'disposals'

urlpatterns = [
    # List views
    path('', views.DisposalPendingListView.as_view(), name='pending_list'),
    path('history/', views.DisposalHistoryListView.as_view(), name='history_list'),

    # Disposal request
    path('request/', views.DisposalRequestView.as_view(), name='request_create'),
    path('request/<str:asset_code>/', views.DisposalRequestView.as_view(), name='request_create_specific'),

    # Detail
    path('<int:pk>/', views.DisposalDetailView.as_view(), name='disposal_detail'),

    # Workflow actions
    path('<int:pk>/approve/', views.DisposalApproveView.as_view(), name='disposal_approve'),
    path('<int:pk>/reject/', views.DisposalRejectView.as_view(), name='disposal_reject'),
    path('<int:pk>/cancel/', views.DisposalCancelView.as_view(), name='disposal_cancel'),
    path('<int:pk>/complete/', views.DisposalCompleteView.as_view(), name='disposal_complete'),

    # Printable
    path('<int:pk>/print/', views.DisposalPrintView.as_view(), name='disposal_print'),
]
