"""RouteFinder URL Configuration"""
from django.contrib import admin
from django.urls import include, path
from django.views.generic.base import RedirectView
from django.conf import settings
from django.contrib.auth import views as auth_views
from RouteFinderWeb.forms import EmailAuthenticationForm
from RouteFinderWeb.observability import metrics_view, debug_logging_toggle_api

urlpatterns = [
    path('metrics', metrics_view, name='metrics'),
    path('metrics/', metrics_view, name='metrics_slash'),
    path('api/observability/debug/', debug_logging_toggle_api, name='debug_logging_toggle'),
    path('favicon.ico', RedirectView.as_view(url=settings.STATIC_URL + 'icon.png')),
    path('', include('RouteFinderWeb.urls')),
    path('admin/', admin.site.urls),
    path('accounts/login/', auth_views.LoginView.as_view(authentication_form=EmailAuthenticationForm), name='login'),
    path('accounts/', include('django.contrib.auth.urls')),
]
