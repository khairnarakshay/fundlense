from django.db import transaction
from django.shortcuts import render
from django.contrib.auth import authenticate, get_user_model  # Required for authenticate()
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.views import APIView
from rest_framework.response import Response  # Required for Response()
from rest_framework import status  # Required for status HTTP codes
from rest_framework_simplejwt.tokens import RefreshToken
from django.conf import settings
from accounts.models import OTP
from accounts.serializers import *
from accounts.services.otp_services import get_valid_otp, issue_email_otp, OTP_MAX_ATTEMPTS
from core.otp_hash import verify_otp_hash
from core.response import api_response
from core.choices import OTP_TYPE_CHOICES
from core.mail_otp_templates import send_email_otp
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.views import APIView
from django.db import transaction
from django.utils import timezone
from rest_framework_simplejwt.tokens import RefreshToken
User = get_user_model()

import  logging
logger = logging.getLogger(__name__)

# Create your views here.
class SignInAPIView(APIView):
    """Authenticate credentials without requiring an existing access token."""

    permission_classes = [AllowAny]
    authentication_classes = []
    serializer_class = LoginSerializer

    def post(self, request):
        """Validate credentials and replace existing authentication cookies."""
        serializer = self.serializer_class(data=request.data)

        if not serializer.is_valid():
            return api_response(
                status.HTTP_400_BAD_REQUEST,
                "Validation failed.",
                data={"errors": serializer.errors},
            )

        username = serializer.validated_data["username"]
        password = serializer.validated_data["password"]

        user = authenticate(username=username, password=password)

        if user is None:
            return api_response(
                status.HTTP_401_UNAUTHORIZED,
                "Invalid username or password.",
            )

        if not user.is_active:
            return api_response(
                status.HTTP_403_FORBIDDEN,
                "User account is inactive.",
            )

        refresh = RefreshToken.for_user(user)
        access_token = str(refresh.access_token)
        refresh_token = str(refresh)

        response = api_response(
            status.HTTP_200_OK,
            "Login successful.",
            data=UserSerializer(user).data,
        )

        is_secure = not settings.DEBUG
        cookie_domain = getattr(settings, "AUTH_COOKIE_DOMAIN", None)

        response.set_cookie(
            key="access_token",
            value=access_token,
            httponly=True,
            secure=is_secure,
            samesite="Lax",
            domain=cookie_domain,
            path="/",
        )

        response.set_cookie(
            key="refresh_token",
            value=refresh_token,
            httponly=True,
            secure=is_secure,
            samesite="Lax",
            domain=cookie_domain,
            path="/api/token/refresh/",
        )

        return response
class SignOutAPIView(APIView):
    # Ensure only logged-in users can call this, using your custom cookie auth pipeline
    permission_classes = [IsAuthenticated]

    def post(self, request):
        response = Response(
            {
                "st": 200,
                "msg": "Logged out successfully.",
                "data": []
            },
            status=status.HTTP_200_OK
        )

        # 🔑 WIPE THE ACCESS TOKEN COOKIE
        response.delete_cookie(
            key='access_token',
            domain=settings.AUTH_COOKIE_DOMAIN, # Dynamic: None locally, .fundlense.com in prod
            path='/'
        )

        # 🔑 WIPE THE REFRESH TOKEN COOKIE
        response.delete_cookie(
            key='refresh_token',
            domain=settings.AUTH_COOKIE_DOMAIN,
            path='/api/token/refresh/' # Must match the exact path set during login!
        )

        return response

class SignupAPIView(APIView):
    """Create a user account and send an email verification OTP."""

    permission_classes = [AllowAny]

    def post(self, request):
        """Register the user before starting email verification."""

        serializer = SignupSerializer(data=request.data)

        if not serializer.is_valid():
            return api_response(
                status.HTTP_400_BAD_REQUEST,
                "Validation failed.",
                data={"errors": serializer.errors},
            )

        mobile = serializer.validated_data["mobile"].strip()
        email = serializer.validated_data["email"].strip().lower()

        if User.objects.filter(mobile=mobile).exists():
            return api_response(
                status.HTTP_409_CONFLICT,
                "An account already exists for this mobile number.",
            )

        if User.objects.filter(email__iexact=email).exists():
            return api_response(
                status.HTTP_409_CONFLICT,
                "An account already exists for this email.",
            )

        try:
            with transaction.atomic():
                user = User(
                    username="user-"+email,
                    mobile=mobile,
                    email=email,
                    is_email_verified=False,
                    is_active=True,
                )
                user.set_unusable_password()
                user.save()

                success, message = issue_email_otp(user, "SIGNUP")

                if not success:
                    raise Exception(message)

                return api_response(
                    status.HTTP_201_CREATED,
                    "Account created successfully. OTP sent to your email.",
                    data={
                        "user_id": user.pk,
                        "mobile": user.mobile,
                        "email": user.email,
                        "is_email_verified": user.is_email_verified,
                    },
                )

        except Exception as e:
            # This catches the exception raised above and rolls back the transaction
            return api_response(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                f"Unable to complete signup. Please try again. Error: {str(e)}",
            )



class ResendOTPAPIView(APIView):
    """Resend an OTP for an existing user and requested OTP type."""
    logger.warning("Signup API request received")
    permission_classes = [AllowAny]

    def post(self, request):
        """Validate the request and resend the requested OTP."""

        serializer = ResendOTPSerializer(data=request.data)

        if not serializer.is_valid():
            return api_response(
                status.HTTP_400_BAD_REQUEST,
                "Validation failed.",
                data={"errors": serializer.errors},
            )

        mobile = serializer.validated_data["mobile"].strip()
        email = serializer.validated_data["email"].strip().lower()
        otp_type = serializer.validated_data["otp_type"]

        user = User.objects.filter(
            mobile=mobile,
            email__iexact=email,
        ).first()

        if not user:
            return api_response(
                status.HTTP_404_NOT_FOUND,
                "User account not found.",
            )

        success, message = issue_email_otp(
            user=user,
            otp_type=otp_type,
            is_resend=True,
        )

        if not success:
            if "resend limit" in message.lower():
                return api_response(
                    status.HTTP_429_TOO_MANY_REQUESTS,
                    message,
                )

            return api_response(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                message,
            )

        return api_response(
            status.HTTP_200_OK,
            "OTP resent successfully.",
        )


class VerifyOTPAPIView(APIView):
    """Verify an OTP according to its requested purpose."""

    permission_classes = [AllowAny]

    def post(self, request):
        """Validate an OTP and update verification state when appropriate."""
        serializer = OTPSerializer(data=request.data)

        if not serializer.is_valid():
            return api_response(
                status.HTTP_400_BAD_REQUEST,
                "Validation failed.",
                data={"errors": serializer.errors},
            )

        mobile = serializer.validated_data["mobile"].strip()
        email = serializer.validated_data["email"].strip().lower()
        otp = serializer.validated_data["otp"]
        otp_type = serializer.validated_data["otp_type"]

        user = User.objects.filter(
            mobile=mobile,
            email__iexact=email,
        ).first()

        if not user:
            return api_response(
                status.HTTP_404_NOT_FOUND,
                "User account not found.",
            )

        challenge = get_valid_otp(
            user=user,
            otp=otp,
            otp_type=otp_type,
        )

        if not challenge:
            return api_response(
                status.HTTP_400_BAD_REQUEST,
                "Invalid or expired OTP.",
            )

        challenge.is_verified = True
        challenge.save(update_fields=["is_verified", "updated"])

        return api_response(
            status.HTTP_200_OK,
            "OTP verified successfully.",
        )

class ForgotPasswordAPIView(APIView):
    """Issue a password-reset OTP for an existing account."""

    permission_classes = [AllowAny]

    def post(self, request):
        """Check account ownership identifiers and send a reset OTP."""

        serializer = ForgotPasswordSerializer(data=request.data)

        if not serializer.is_valid():
            return api_response(
                101,
                "Validation failed.",
                data={"errors": serializer.errors},
                http_status=status.HTTP_400_BAD_REQUEST,
            )

        mobile = serializer.validated_data["mobile"]
        email = serializer.validated_data["email"].strip().lower()

        user = User.objects.filter(
            mobile=mobile,
            email__iexact=email,
            # is_active=True,
        ).first()

        # Use a generic response in production to reduce account enumeration.
        if not user:
            return api_response(
                status.HTTP_200_OK,
                "If the account details are valid, a password-reset OTP will be sent.",

            )

        try:
            issue_email_otp(user, "FORGOT_PASSWORD", False)
        except Exception:
            return api_response(
                     status.HTTP_503_SERVICE_UNAVAILABLE,
                "Unable to send OTP. Please try again.",

            )

        return api_response(
            status.HTTP_200_OK,
            "If the account details are valid, a password-reset OTP will be sent.",

        )


class SetPasswordAPIView(APIView):
    """Set an existing user's password and return JWT tokens."""

    permission_classes = [AllowAny]

    def post(self, request):
        """Validate the OTP, update the password, and issue JWT tokens."""
        serializer = SetPasswordSerializer(data=request.data)

        if not serializer.is_valid():
            return api_response(
                status.HTTP_400_BAD_REQUEST,
                "Validation failed.",
                data={"errors": serializer.errors},
            )

        mobile = serializer.validated_data["mobile"].strip()
        email = serializer.validated_data["email"].strip().lower()
        otp = serializer.validated_data["otp"]
        password = serializer.validated_data["password"]
        otp_type = serializer.validated_data["otp_type"]

        if otp_type not in ("SIGNUP", "FORGOT_PASSWORD"):
            return api_response(
                status.HTTP_400_BAD_REQUEST,
                "Invalid OTP type.",
            )

        with transaction.atomic():
            user = User.objects.select_for_update().filter(
                mobile=mobile,
                email__iexact=email,
            ).first()

            if not user or not user.is_active:
                return api_response(
                    status.HTTP_400_BAD_REQUEST,
                    "Unable to set password with the supplied details.",
                )

            challenge = OTP.objects.select_for_update().filter(
                user=user,
                otp_type=otp_type,
                is_verified=True,
                expires_at__gt=timezone.now(),
                otp_limit__gt=0,
            ).first()

            if not challenge:
                return api_response(
                    status.HTTP_400_BAD_REQUEST,
                    "OTP is invalid, expired, or not verified.",
                )

            if not verify_otp_hash(otp, challenge.otp):
                challenge.otp_limit -= 1
                challenge.failed_count += 1
                challenge.save(
                    update_fields=["otp_limit", "failed_count", "updated"]
                )
                return api_response(
                    status.HTTP_400_BAD_REQUEST,
                    "OTP is invalid, expired, or not verified.",
                )

            user.set_password(password)

            if otp_type == "SIGNUP":
                user.is_email_verified = True

            user.save(
                update_fields=(
                    ["password", "is_email_verified"]
                    if otp_type == "SIGNUP"
                    else ["password"]
                )
            )

            challenge.is_verified = False
            challenge.otp_limit = 0
            challenge.save(
                update_fields=["is_verified", "otp_limit", "updated"]
            )

        # refresh = RefreshToken.for_user(user)
        # user_data = UserSerializer(user).data
        # user_data["access_token"] = str(refresh.access_token)
        # user_data["refresh_token"] = str(refresh)

        # 1. Generate the JWT tokens upon successful reset
        refresh = RefreshToken.for_user(user)
        access_token = str(refresh.access_token)
        refresh_token = str(refresh)

        # 2. Serialize user data (Tokens omitted from body)
        user_data = UserSerializer(user).data

        # 3. Create response object using your custom format utility
        response = api_response(
            status.HTTP_200_OK,
            "Password set successfully.",
            data=user_data,
        )

        # 4. Inject the Access Token Cookie (Shared across subdomains)
        response.set_cookie(
            key='access_token',
            value=access_token,
            httponly=True,
            secure=True,
            samesite='Lax',
            domain='.fundlense.com',  # Matches ://fundlense.com config
            path='/'
        )

        # 5. Inject the Refresh Token Cookie
        response.set_cookie(
            key='refresh_token',
            value=refresh_token,
            httponly=True,
            secure=True,
            samesite='Lax',
            domain='.fundlense.com',
            path='/api/token/refresh/'
        )
        return response