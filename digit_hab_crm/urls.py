"""
Main URL configuration for digit_hab_crm project.
"""

from django.contrib import admin
from django.urls import path, include, re_path
from django.conf import settings
from django.conf.urls.static import static
from django.views.static import serve
from django.http import JsonResponse
from drf_spectacular.views import (
    SpectacularAPIView, 
    SpectacularRedocView, 
    SpectacularSwaggerView
)


def health_check(request):
    """Health check endpoint for monitoring and deployment verification."""
    return JsonResponse({
        "status": "ok",
        "message": "DIGIT-HAB CRM is running",
        "version": "1.0"
    })

urlpatterns = [
    # Admin interface
    path('admin/', admin.site.urls),
    
    # Health check endpoint
    path('health/', health_check, name='health-check'),
    
    # API Documentation
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    path('api/redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),
    
    # API endpoints
    path('api/auth/', include('apps.auth.urls')),
    path('api/properties/', include('apps.properties.urls')),
    path('api/favorites/', include('apps.favorites.urls')),
    path('api/crm/', include('apps.crm.urls')),
    path('api/reservations/', include('apps.reservations.urls')),
    path('api/notifications/', include('apps.notifications.urls')),
    path('api/calendar/', include('apps.calendar.urls')),
    path('api/commissions/', include('apps.commissions.urls')),
    path('api/messaging/', include('apps.messaging.urls')),
    path('api/', include('apps.reviews.urls')),
    path('api/', include('apps.core.urls')),
]

# Médias : dev (DEBUG) ou prod SERVE_MEDIA=true (repli si Caddy ne sert pas /media/)
_serve_media = settings.DEBUG or getattr(settings, 'SERVE_MEDIA', False)
if _serve_media:
    _media_url = settings.MEDIA_URL.lstrip('/').rstrip('/')
    urlpatterns += [
        re_path(
            rf'^{_media_url}/(?P<path>.*)$',
            serve,
            {'document_root': str(settings.MEDIA_ROOT)},
        ),
    ]

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    import debug_toolbar
    urlpatterns += [path('__debug__/', include(debug_toolbar.urls))]