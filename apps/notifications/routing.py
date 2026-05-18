"""
WebSocket routing pour le système de notifications
Gère les connexions WebSocket pour les notifications en temps réel
"""

from django.urls import re_path
from .consumers import NotificationConsumer, AgentStatusConsumer

# Patterns WebSocket pour les notifications
websocket_urlpatterns = [
    # Notifications personnelles
    re_path(r"ws/notifications/(?P<user_id>[^/]+)/$", NotificationConsumer.as_asgi()),
    
    # Statut des agents (pour l'interface d'administration)
    re_path(r"ws/agents/status/$", AgentStatusConsumer.as_asgi()),
    
    # Notifications de groupe
    re_path(r"ws/notifications/group/(?P<group_id>[^/]+)/$", NotificationConsumer.as_asgi()),
    
    # Notifications par propriété
    re_path(r"ws/notifications/property/(?P<property_id>[^/]+)/$", NotificationConsumer.as_asgi()),
    
    # Notifications par réservation
    re_path(r"ws/notifications/reservation/(?P<reservation_id>[^/]+)/$", NotificationConsumer.as_asgi()),
]