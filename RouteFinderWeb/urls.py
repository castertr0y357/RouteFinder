from django.urls import path
from django.contrib.auth import views as auth_views
from django.views.generic import TemplateView

from . import views

urlpatterns = [
    path('sw.js', TemplateView.as_view(template_name='RouteFinderWeb/sw.js', content_type='application/javascript'), name='sw_js'),
    path('manifest.json', TemplateView.as_view(template_name='RouteFinderWeb/manifest.json', content_type='application/json'), name='manifest_json'),
    path('', views.MainView.as_view(), name='main'),
    path('results/', views.ResultsView.as_view(), name='results'),
    path('register/', views.RegisterView.as_view(), name='register'),
    path('profile/', views.ProfileView.as_view(), name='profile'),
    path('api/ai/test/', views.AITestConnectionView.as_view(), name='ai_test_connection'),
    path('password_change/', auth_views.PasswordChangeView.as_view(template_name='RouteFinderWeb/password_change.html', success_url='/profile/'), name='password_change'),
    path('discover/', views.SaleDiscoveryView.as_view(), name='discover'),
    path('toggle-rating/', views.ToggleRatingView.as_view(), name='toggle_rating'),
    path('get-zip-code/', views.GetZipCodeView.as_view(), name='get_zip_code'),
    path('hide-sale/', views.HideSaleView.as_view(), name='hide_sale'),
    path('get-address/', views.GetAddressView.as_view(), name='get_address'),
    path('discovery-data/', views.DiscoveryDataView.as_view(), name='discovery_data'),
    path('route-data/', views.RouteDataView.as_view(), name='route_data'),
    path('remove-address/', views.RemoveAddressView.as_view(), name='remove_address'),
    path('clear-route/', views.ClearRouteView.as_view(), name='clear_route'),
]
