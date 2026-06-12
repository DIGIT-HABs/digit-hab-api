"""
Django ASGI config for digit_hab_crm project.
Supporte Django Channels pour les WebSockets
"""

import os
from django.core.asgi import get_asgi_application
from django.conf import settings
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.security.websocket import OriginValidator

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'digit_hab_crm.settings')

# Initialiser Django ASGI application plus tôt pour s'assurer que le AppRegistry
# est rempli avant d'importer du code qui peut en avoir besoin
django_asgi_app = get_asgi_application()

# Import des routers des applications
from apps.notifications.routing import websocket_urlpatterns as notification_websocket_urlpatterns
from apps.messaging.routing import websocket_urlpatterns as messaging_websocket_urlpatterns
from apps.messaging.middleware import JWTAuthMiddleware

# Combine all WebSocket URL patterns
all_websocket_urlpatterns = notification_websocket_urlpatterns + messaging_websocket_urlpatterns

def _websocket_allowed_origins():
    """Origines autorisées pour les connexions WebSocket (app mobile + Expo web)."""
    origins = set()
    for host in getattr(settings, 'ALLOWED_HOSTS', []):
        if host and host != '*':
            origins.add(f'https://{host}')
            origins.add(f'http://{host}')
    for origin in getattr(settings, 'CORS_ALLOWED_ORIGINS', []):
        if origin:
            origins.add(origin.rstrip('/'))
    origins.update({
        'http://localhost:8081',
        'http://127.0.0.1:8081',
        'http://localhost:19006',
        'http://127.0.0.1:19006',
    })
    return list(origins)


# WebSocket stack (JWT via query ?token= ou 1er message auth pour le chat).
ws_app = JWTAuthMiddleware(URLRouter(all_websocket_urlpatterns))
if not getattr(settings, 'DEBUG', False):
    ws_app = OriginValidator(ws_app, _websocket_allowed_origins())

application = ProtocolTypeRouter({
    "http": django_asgi_app,
    "websocket": ws_app,
})