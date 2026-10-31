# ai_intelligence/urls.py
from django.urls import path

from ai_intelligence.views import ChatAPIView, PortfolioAnalysisAPIView,PortfolioReportAPIView

urlpatterns = [
    path("portfolio-analysis/", PortfolioAnalysisAPIView.as_view(), name="ai-portfolio-analysis"),
    path("portfolio-report/", PortfolioReportAPIView.as_view(), name="ai-portfolio-report"),
    path("chat/", ChatAPIView.as_view(), name="ai-chat"),
]