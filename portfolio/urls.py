# portfolio/api/urls.py
from django.urls import path

from .views import *

urlpatterns = [

    path("summary/", PortfolioSummaryAPIView.as_view(), name="portfolio-summary"),
    path("allocation/", AllocationAPIView.as_view(), name="portfolio-allocation"),
    path("returns-by-category/", ReturnsByCategoryAPIView.as_view(), name="portfolio-returns-by-category"),
    path("insights/", InsightsAPIView.as_view(), name="portfolio-insights"),
    path("transactions/", TransactionsAPIView.as_view(), name="portfolio-transactions"),
    path("invested-value/", PortfolioInvestedValueAPIView.as_view(), name="portfolio-invested-value"),
    path("current-value/", PortfolioCurrentValueAPIView.as_view(), name="portfolio-current-value"),
    path("value-history/", PortfolioValueHistoryAPIView.as_view(), name="portfolio-value-history"),

]

