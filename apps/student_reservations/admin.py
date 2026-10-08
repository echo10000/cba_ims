from django.contrib import admin
from .models import StudentReservation


@admin.register(StudentReservation)
class StudentReservationAdmin(admin.ModelAdmin):
    list_display = [
        'id',
        'student_id',
        'student_name',
        'category',
        'asset',
        'requested_pickup',
        'requested_return',
        'status',
        'id_deposit_verified',
        'created_at',
    ]
    list_filter = [
        'status',
        'category',
        'id_deposit_verified',
        'requested_pickup',
    ]
    search_fields = [
        'student_id',
        'student_name',
        'lookup_token',
        'asset__asset_code',
        'asset__item_name',
    ]
    readonly_fields = [
        'lookup_token',
        'created_at',
        'updated_at',
    ]
