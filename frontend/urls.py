from django.urls import path
from . import views


urlpatterns = [
    # =====================================base===========================================#
    path('', views.home_page, name=''),
    path('dashboard', views.dashboard_view, name='dashboard'),
    path('logout', views.logout_user, name='logout'),
    path('statements', views.statements_view, name='statements'),
    path('transactions', views.statements_view, name='transactions'),
    path('explore', views.statements_view, name='explore'),

    path('compare', views.statements_view, name='compare'),

    path('reports', views.statements_view, name='reports'),
    path('settings', views.statements_view, name='settings'),
    path('pricing', views.statements_view, name='pricing'),

    path('logout', views.statements_view, name='logout'),
    path('settings', views.statements_view, name='settings'),

]