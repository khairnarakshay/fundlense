# frontend/views.py
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
def home_page(request):
    return render(request, 'base/home_page.html')

def logout_user(request):
    request.session.flush()
    return redirect('')


def dashboard_view(request):
    if request.headers.get("HX-Request"):
        # If requested via htmx, return only the block fragment
        return render(request, "pages/dashboard/dashboard_content.html")
    # If visited directly in browser URL, return full base template
    return render(request, "pages/dashboard/dashboard.html")


def statements_view(request):
    # If HTMX triggers the request, return ONLY the inner form/table fragment
    if request.headers.get('HX-Request'):
        return render(request, "pages/statements/statements_content.html")
    # If visited directly via the browser URL, return the full page wrapper
    return render(request, "pages/statements/statements.html")


