from django.urls import path
from . import views

app_name = 'borrowing'

urlpatterns = [
    # Queues and Lists
    path('', views.BorrowingRequestListView.as_view(), name='request_list'),
    path('requests/', views.BorrowingRequestListView.as_view(), name='request_list_alt'),
    path('active/', views.ActiveBorrowingListView.as_view(), name='active_list'),
    path('history/', views.BorrowingHistoryListView.as_view(), name='history_list'),

    # Faculty Portal
    path('my-borrowings/', views.MyBorrowingsView.as_view(), name='my_borrowings'),

    # Request Creation
    path('request/', views.BorrowingRequestCreateView.as_view(), name='request_create'),
    path('request/<str:asset_code>/', views.BorrowingRequestCreateView.as_view(), name='request_create_specific'),

    # Detail & Lifecycle Actions
    path('<int:pk>/', views.BorrowingDetailView.as_view(), name='borrowing_detail'),
    path('<int:pk>/approve/', views.BorrowingApproveView.as_view(), name='borrowing_approve'),
    path('<int:pk>/reject/', views.BorrowingRejectView.as_view(), name='borrowing_reject'),
    path('<int:pk>/cancel/', views.BorrowingCancelView.as_view(), name='borrowing_cancel'),
    path('<int:pk>/release/', views.BorrowingReleaseView.as_view(), name='borrowing_release'),
    path('<int:pk>/return/', views.BorrowingReturnView.as_view(), name='borrowing_return'),

    # QR and Direct Shortcut
    path('assets/<str:asset_code>/return/', views.AssetReturnBorrowingView.as_view(), name='asset_return_borrowing'),
]
