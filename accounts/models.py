from datetime import datetime, timedelta ,date

from django.conf import settings

# Create your models here.
from django.db import models
from django.contrib.auth.models import AbstractUser
from core.choices import ACCOUNT_TYPE


class User(AbstractUser):
    # mobile , email ,firstname ,username is inbuild field
    middle_name = models.CharField(max_length=50, blank=True, null=True)
    mobile = models.CharField(max_length=12, verbose_name='Mobile', blank=True, null=True)
    is_email_verified = models.BooleanField(default=False, verbose_name='email verified')
    roles = models.ManyToManyField("permission.Role", related_name="users", blank=True, verbose_name="Roles")
    pan = models.CharField(max_length=12, blank=True, null=False)
    created = models.DateTimeField(auto_now_add=True, blank=True, null=True)
    created_by = models.CharField(blank=True, null=True)
    updated = models.DateTimeField(auto_now=True)
    updated_by = models.CharField(blank=True, null=True)
    @property
    def fullname(self):
        """Return user's full name (first + middle + last) or username as fallback."""
        full_name = " ".join(
            filter(None, [self.first_name, self.middle_name, self.last_name])
        ).strip()
        return full_name if full_name else self.username

# models.py

from django.conf import settings
from django.db import models

from core.choices import OTP_TYPE_CHOICES


class OTP(models.Model):
    """Store reusable OTP challenges for user authentication."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="otps")
    otp = models.CharField(max_length=128)
    otp_type = models.CharField(max_length=20, choices=OTP_TYPE_CHOICES)
    otp_limit = models.PositiveSmallIntegerField(default=10)
    failed_count = models.PositiveIntegerField(default=0)
    resend_count = models.PositiveIntegerField(default=0)
    # resend_window_started_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField()
    is_verified = models.BooleanField(default=False)
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    class Meta:
        """Enforce one OTP record per user and OTP type."""

        constraints = [
            models.UniqueConstraint(fields=["user", "otp_type"], name="unique_user_otp_type"),
        ]
        ordering = ["-updated"]

    def __str__(self):
        """Return the user and OTP type for administrative identification."""

        return f"{self.user} - {self.otp_type}"