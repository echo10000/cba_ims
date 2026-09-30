from django.urls import path
from . import views

app_name = 'supplies'

urlpatterns = [
    # Supply Catalog & Lists
    path('', views.SupplyListView.as_view(), name='supply_list'),
    path('low-stock/', views.LowStockListView.as_view(), name='low_stock_list'),
    path('transactions/', views.SupplyTransactionListView.as_view(), name='transaction_list'),

    # Stock Operations (Admin only)
    path('stock-in/', views.StockInView.as_view(), name='stock_in'),
    path('stock-in/<str:supply_code>/', views.StockInView.as_view(), name='stock_in_specific'),
    path('stock-out/', views.StockOutView.as_view(), name='stock_out'),
    path('stock-out/<str:supply_code>/', views.StockOutView.as_view(), name='stock_out_specific'),
    path('adjust/', views.StockAdjustmentView.as_view(), name='stock_adjust'),
    path('adjust/<str:supply_code>/', views.StockAdjustmentView.as_view(), name='stock_adjust_specific'),

    # Supply Item CRUD (Admin only)
    path('create/', views.SupplyCreateView.as_view(), name='supply_create'),
    path('<str:supply_code>/', views.SupplyDetailView.as_view(), name='supply_detail'),
    path('<str:supply_code>/edit/', views.SupplyUpdateView.as_view(), name='supply_edit'),
    path('<str:supply_code>/toggle/', views.SupplyToggleActiveView.as_view(), name='supply_toggle'),
    path('<str:supply_code>/delete/', views.SupplyDeleteView.as_view(), name='supply_delete'),
]
