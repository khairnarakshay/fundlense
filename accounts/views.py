from django.shortcuts import render
from django.contrib.auth import authenticate  # Required for authenticate()
from rest_framework.views import APIView
from rest_framework.response import Response  # Required for Response()
from rest_framework import status  # Required for status HTTP codes
from rest_framework_simplejwt.tokens import RefreshToken
from accounts.serializers import LoginSerializer, UserSerializer


# Create your views here.
class SignInAPIView(APIView):

    permission_classes = []

    serializer_class = LoginSerializer

    def post(self, request):

        serializer = self.serializer_class(
            data=request.data
        )

        if not serializer.is_valid():

            return Response(
                {
                    "status": 101,
                    "message": "Validation failed.",
                    "errors": serializer.errors,
                    "data": []
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        username = serializer.validated_data.get(
            "username"
        )

        password = serializer.validated_data.get(
            "password"
        )
        print("password",password,"\n" "username",username)
        user = authenticate(
            username=username,
            password=password
        )

        if not user:

            return Response(
                {
                    "status": 102,
                    "message": "Invalid username or password.",
                    "data": []
                },
                status=status.HTTP_401_UNAUTHORIZED
            )

        if not user.is_active:

            return Response(
                {
                    "status": 103,
                    "message": "User account is inactive.",
                    "data": []
                },
                status=status.HTTP_403_FORBIDDEN
            )



        refresh = RefreshToken.for_user(user)

        access_token = str(
            refresh.access_token
        )

        refresh_token = str(
            refresh
        )

        user_data = UserSerializer(
            user
        ).data

        user_data["access_token"] = access_token

        user_data["refresh_token"] = refresh_token

        return Response(
            {
                "status": 100,
                "message": "Login successful.",
                "data": user_data
            },
            status=status.HTTP_200_OK
        )
