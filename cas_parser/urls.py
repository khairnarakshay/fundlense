# cas_parser/api/urls.py
from django.urls import path

from cas_parser.views import CASStatementUploadAPIView

urlpatterns = [
    path("upload/", CASStatementUploadAPIView.as_view(), name="cas-statement-upload"),
]

