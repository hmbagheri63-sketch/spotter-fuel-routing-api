from django.contrib import admin
from django.conf import settings
from django.conf.urls.static import static
from django.urls import path
from django.views.generic import TemplateView
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from api.views import CitiesAutocompleteView, OptimizeRouteView

urlpatterns = [
    path('admin/', admin.site.urls),
    
    # UI Dashboard Endpoints
    path('', TemplateView.as_view(template_name='index.html'), name='home-dashboard'),
    path('map/', TemplateView.as_view(template_name='index.html'), name='map-dashboard'),

    # API Endpoints
    path('api/route', OptimizeRouteView.as_view(), name='optimize-route-no-slash'),
    path('api/route/', OptimizeRouteView.as_view(), name='optimize-route'),
    path('api/cities/', CitiesAutocompleteView.as_view(), name='city-autocomplete'),
    
    # OpenAPI 3 & Swagger Docs
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
]

if settings.DEBUG:
    urlpatterns += static(
        settings.STATIC_URL,
        document_root=settings.STATICFILES_DIRS[0],
    )