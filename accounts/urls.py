from django.contrib.auth.views import LogoutView
from django.urls import include, path
from .views import *
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from django.urls import path

urlpatterns = [
    path('token/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('auth/login/', SignInAPIView.as_view(), name='user_login'),
    path("auth/signup/", SignupAPIView.as_view(), name="signup"),
    path("auth/resend-otp/", ResendOTPAPIView.as_view(), name="resend-otp"),
    path("auth/verify-otp/", VerifyOTPAPIView.as_view(), name="verify-otp"),
    path("auth/forgot-password/", ForgotPasswordAPIView.as_view(), name="forgot-password"),
    path("auth/set-password/", SetPasswordAPIView.as_view(), name="set-password"),
]