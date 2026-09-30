from django.urls import path
from . import views

app_name = 'assignments'

urlpatterns = [
    # Assignment Lists
    path('', views.CurrentAssignmentListView.as_view(), name='current_list'),
    path('history/', views.AssignmentHistoryListView.as_view(), name='history_list'),

    # Actions: Assign & Return
    path('assign/', views.AssetAssignView.as_view(), name='assign_create'),
    path('assign/<str:asset_code>/', views.AssetAssignView.as_view(), name='assign_asset_specific'),
    path('<int:pk>/return/', views.AssetReturnView.as_view(), name='asset_return'),

    # Faculty & Staff Accountability Profile
    path('my-accountability/', views.MyAccountabilityView.as_view(), name='my_accountability'),
    path('employees/<int:employee_id>/print/', views.PrintableAccountabilityView.as_view(), name='print_accountability'),
]
