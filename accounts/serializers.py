from rest_framework import serializers
from django.contrib.auth.password_validation import validate_password

from accounts.models import User
from core.choices import OTP_TYPE_CHOICES


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField(write_only=True)

class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'first_name', 'last_name', 'is_active', 'is_staff', 'date_joined']



# serializers.py



class SignupSerializer(serializers.Serializer):
    """Validate signup contact details."""

    mobile = serializers.CharField(max_length=12)
    email = serializers.EmailField()


class OTPSerializer(serializers.Serializer):
    """Validate contact details and OTP verification input."""

    mobile = serializers.CharField(max_length=12)
    email = serializers.EmailField()
    otp = serializers.RegexField(regex=r"^\d{6}$")
    otp_type = serializers.ChoiceField(choices=OTP_TYPE_CHOICES)


class SetPasswordSerializer(serializers.Serializer):
    """Validate the OTP and new password submission."""

    mobile = serializers.CharField(max_length=12)
    email = serializers.EmailField()
    otp = serializers.RegexField(regex=r"^\d{6}$")
    otp_type = serializers.ChoiceField(choices=OTP_TYPE_CHOICES)
    password = serializers.CharField(write_only=True, trim_whitespace=False)

    def validate_password(self, value):
        """Apply Django's configured password validation rules."""

        validate_password(value)
        return value


class ForgotPasswordSerializer(serializers.Serializer):
    """Validate contact details for a password-reset request."""

    mobile = serializers.CharField(max_length=12)
    email = serializers.EmailField()

class ResendOTPSerializer(serializers.Serializer):
    """Validate contact details and OTP type for resend requests."""

    mobile = serializers.CharField(max_length=12)
    email = serializers.EmailField()
    otp_type = serializers.ChoiceField(choices=OTP_TYPE_CHOICES)