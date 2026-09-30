from django.urls import path
from . import views

app_name = 'transfers'

urlpatterns = [
    # Transfer Lists
    path('', views.PendingTransferListView.as_view(), name='pending_list'),
    path('history/', views.TransferHistoryListView.as_view(), name='history_list'),

    # Request Workflows
    path('request/', views.TransferRequestView.as_view(), name='transfer_request'),
    path('request/<str:asset_code>/', views.TransferRequestView.as_view(), name='transfer_request_specific'),

    # Transfer Details
    path('<int:pk>/', views.TransferDetailView.as_view(), name='transfer_detail'),

    # Actions (Admin only)
    path('<int:pk>/approve/', views.TransferApproveView.as_view(), name='transfer_approve'),
    path('<int:pk>/reject/', views.TransferRejectView.as_view(), name='transfer_reject'),
    path('<int:pk>/complete/', views.TransferCompleteView.as_view(), name='transfer_complete'),
    path('<int:pk>/cancel/', views.TransferCancelView.as_view(), name='transfer_cancel'),
]
