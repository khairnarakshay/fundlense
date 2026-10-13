# frontend/views.py
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
def home_page(request):
    return render(request, 'base/home_page.html')

def dashboard_view(request):
    if request.headers.get("HX-Request"):
        # If requested via htmx, return only the block fragment
        return render(request, "dashboard_content.html")
    # If visited directly in browser URL, return full base template
    return render(request, "pages/dashboard/dashboard.html")
