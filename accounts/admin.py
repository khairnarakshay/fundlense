from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from accounts.models import *
@admin.register(User)
class CustomUserAdmin(UserAdmin):
  # Columns to display in the user list table
  list_display = (
      'username',
      'email',
      'mobile',
      'is_email_verified',
      'is_staff',
  )

  # Filters on the right sidebar
  list_filter = ('is_staff', 'is_superuser', 'is_active', 'is_email_verified')

  # Fields searchable in the dashboard
  search_fields = (
      'username',
      'first_name',
      'middle_name',
      'last_name',
      'email',
      'mobile',
      'pan',
  )

  # Form layout (combines default fields with your custom fields)
  fieldsets = UserAdmin.fieldsets + (
      (
          ('Additional Info'),
          {
              'fields': (
                  'middle_name',
                  'mobile',
                  'is_email_verified',
                  'pan',
                  'roles',
              )
          },
      ),
      (
          ('Audit Metadata'),
          {'fields': ('created', 'created_by', 'updated', 'updated_by')},
      ),
  )

  # Keeps system-generated dates read-only on the change page
  readonly_fields = ('created', 'updated')

# Register your models here.
@admin.register(OTP)
class OTPAdmin(admin.ModelAdmin):
  list_display = (
      'user',
      'otp_type',
      'otp_limit',
      'failed_count',
      'resend_count',
      'is_verified',
      'expires_at',
      'created',
      'updated',
  )
  list_filter = ('otp_type', 'is_verified', 'created')
  search_fields = ('user__email', 'user__username', 'otp')  # Adjust based on your user model fields
  readonly_fields = ('created', 'updated')