from django.urls import path
from . import views

app_name = 'reports'

urlpatterns = [
    # Central Reports Dashboard
    path('', views.ReportsDashboardView.as_view(), name='reports_dashboard'),

    # Consolidated Executive Workbook Export
    path('executive-summary/xlsx/', views.ExecutiveSummaryXLSXExportView.as_view(), name='executive_summary_xlsx'),

    # 1. Asset Inventory Reports
    path('assets/', views.AssetInventoryReportView.as_view(), name='asset_inventory'),
    path('assets/by-department/', views.AssetByDepartmentReportView.as_view(), name='asset_by_department'),
    path('assets/by-location/', views.AssetByLocationReportView.as_view(), name='asset_by_location'),

    # 2. Faculty Accountability Reports
    path('accountability/', views.AccountabilityReportView.as_view(), name='accountability_active'),
    path('accountability/history/', views.AccountabilityHistoryReportView.as_view(), name='accountability_history'),
    path('accountability/employee/<int:pk>/', views.EmployeeAccountabilityReportView.as_view(), name='accountability_employee'),

    # 3. Movement & Transfers Report
    path('transfers/', views.TransferReportView.as_view(), name='transfers'),

    # 4. Equipment Borrowing Reports
    path('borrowing/', views.BorrowingReportView.as_view(), name='borrowing'),

    # 5. Maintenance & Repair Reports
    path('maintenance/', views.MaintenanceReportView.as_view(), name='maintenance'),
    path('maintenance/replacement-candidates/', views.ReplacementCandidatesReportView.as_view(), name='maintenance_replacements'),
    path('maintenance/cost-summary/', views.MaintenanceCostSummaryReportView.as_view(), name='maintenance_cost_summary'),

    # 6. Physical Verification Reports
    path('verification/', views.VerificationReportView.as_view(), name='verification'),
    path('verification/mismatches/', views.VerificationMismatchesReportView.as_view(), name='verification_mismatches'),
    path('verification/never-verified/', views.NeverVerifiedReportView.as_view(), name='verification_never_verified'),

    # 7. Consumable Supplies Reports
    path('supplies/', views.SupplyStockReportView.as_view(), name='supplies_stock'),
    path('supplies/low-stock/', views.SupplyStockReportView.as_view(), {'low_stock': True}, name='supplies_low_stock'),
    path('supplies/transactions/', views.SupplyTransactionsReportView.as_view(), name='supplies_transactions'),
    path('supplies/by-department/', views.SupplyDepartmentUsageReportView.as_view(), name='supplies_by_department'),

    # 8. Property Disposal Reports
    path('disposals/', views.DisposalReportView.as_view(), name='disposals'),

    # 9. System Activity & Audit Trail (Admin only)
    path('audit/', views.AuditLogReportView.as_view(), name='audit_log'),
]
