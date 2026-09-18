from django.urls import include, path
from .views import *
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from django.urls import path

urlpatterns = [
    path('token/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('login/', SignInAPIView.as_view(), name='user_login'),
]