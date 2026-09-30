# mutual_fund/api/urls.py
from django.urls import path

from mutual_fund import views
from mutual_fund.views import *

urlpatterns = [
    path("nav-history/", NavHistoryAPIView.as_view(), name="mf-nav-history"),
    path("schemes/", SchemeListAPIView.as_view(), name="mf-scheme-list"),
    path("schemes/filter-options/", SchemeFilterOptionsAPIView.as_view(), name="mf-scheme-filter-options"),
]