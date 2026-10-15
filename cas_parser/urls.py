# cas_parser/api/urls.py
from django.urls import path

from cas_parser.views import *

urlpatterns = [
    path("upload/", CASStatementUploadAPIView.as_view(), name="cas-statement-upload"),

    path("summary/", PortfolioSummaryAPIView.as_view(), name="portfolio-summary"),
    path("allocation/", AllocationAPIView.as_view(), name="portfolio-allocation"),
    path("returns-by-category/", ReturnsByCategoryAPIView.as_view(), name="portfolio-returns-by-category"),
    path("insights/", InsightsAPIView.as_view(), name="portfolio-insights"),
    path("transactions/", TransactionsAPIView.as_view(), name="portfolio-transactions"),


    path("statements/", CASStatementListAPIView.as_view(), name="cas-statement-list"),
    path("statements/delete/<int:statement_id>/", CASStatementDeleteAPIView.as_view(), name="cas-statement-delete"),
    path("value-history/", PortfolioValueHistoryAPIView.as_view(), name="portfolio-value-history"),

]

