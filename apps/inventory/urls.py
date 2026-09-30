from django.urls import path
from . import views

app_name = 'inventory'

urlpatterns = [
    # Asset Management
    path('', views.AssetListView.as_view(), name='asset_list'),
    path('scan/', views.ScanAssetView.as_view(), name='asset_scan'),
    path('qr-labels/', views.BulkQRLabelPrintView.as_view(), name='qr_labels_bulk'),
    path('physical-verification/', views.PhysicalVerificationListView.as_view(), name='physical_verification_list'),
    path('assets/add/', views.AssetCreateView.as_view(), name='asset_create'),
    path('assets/<str:asset_code>/', views.AssetDetailView.as_view(), name='asset_detail'),
    path('assets/<str:asset_code>/edit/', views.AssetUpdateView.as_view(), name='asset_edit'),
    path('assets/<str:asset_code>/delete/', views.AssetDeleteView.as_view(), name='asset_delete'),
    path('assets/<str:asset_code>/verify/', views.AssetVerifyView.as_view(), name='asset_verify'),
    path('assets/<str:asset_code>/qr-label/', views.AssetQRLabelView.as_view(), name='asset_qr_label'),
    path('assets/<str:asset_code>/qr-image/', views.QRAssetImageView.as_view(), name='asset_qr_image'),
    path('assets/<str:asset_code>/qr-lookup/', views.QRAssetLookupView.as_view(), name='qr_asset_lookup'),

    # Category Management
    path('categories/', views.CategoryListView.as_view(), name='category_list'),
    path('categories/create/', views.CategoryCreateView.as_view(), name='category_create'),
    path('categories/<int:pk>/edit/', views.CategoryUpdateView.as_view(), name='category_edit'),

    # Brand Management
    path('brands/', views.BrandListView.as_view(), name='brand_list'),
    path('brands/create/', views.BrandCreateView.as_view(), name='brand_create'),
    path('brands/<int:pk>/edit/', views.BrandUpdateView.as_view(), name='brand_edit'),
]
