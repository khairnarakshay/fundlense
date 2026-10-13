from django.urls import path
from . import views


urlpatterns = [
    # =====================================base===========================================#
    path('', views.home_page, name='home_page'),
    path('dashboard', views.dashboard_view, name='dashboard')
]