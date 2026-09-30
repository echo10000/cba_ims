from django.urls import path
from . import views

app_name = 'maintenance'

urlpatterns = [
    # Queues & Lists
    path('', views.MaintenanceCaseListView.as_view(), name='case_list'),
    path('history/', views.MaintenanceHistoryListView.as_view(), name='history_list'),
    path('my-reports/', views.MyMaintenanceListView.as_view(), name='my_reports'),

    # Reporting / Filing
    path('report/', views.MaintenanceReportCreateView.as_view(), name='report_create'),
    path('report/<str:asset_code>/', views.MaintenanceReportCreateView.as_view(), name='report_create_specific'),

    # Case Details
    path('<int:pk>/', views.MaintenanceDetailView.as_view(), name='maintenance_detail'),

    # Workflow Actions
    path('<int:pk>/assess/', views.MaintenanceAssessView.as_view(), name='maintenance_assess'),
    path('<int:pk>/start-repair/', views.MaintenanceStartRepairView.as_view(), name='maintenance_start_repair'),
    path('<int:pk>/complete/', views.MaintenanceCompleteRepairView.as_view(), name='maintenance_complete'),
    path('<int:pk>/for-replacement/', views.MaintenanceForReplacementView.as_view(), name='maintenance_for_replacement'),
    path('<int:pk>/cancel/', views.MaintenanceCancelView.as_view(), name='maintenance_cancel'),
]
