"""
Consumers WebSocket pour le système de notifications
Gère les connexions temps réel et l'envoi de notifications
"""

import json
import logging
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from asgiref.sync import sync_to_async

from .models import Notification, NotificationSubscription

User = get_user_model()
logger = logging.getLogger(__name__)


class NotificationConsumer(AsyncWebsocketConsumer):
    """Consumer pour les notifications WebSocket"""
    
    async def connect(self):
        """Gère la connexion WebSocket"""
        try:
            # Extraire l'ID utilisateur du URL
            self.user_id = self.scope['url_route']['kwargs'].get('user_id')
            self.group_id = self.scope['url_route']['kwargs'].get('group_id')
            self.property_id = self.scope['url_route']['kwargs'].get('property_id')
            self.reservation_id = self.scope['url_route']['kwargs'].get('reservation_id')
            
            # Vérifier l'authentification
            if not self.scope.get("user") or not self.scope["user"].is_authenticated:
                await self.close()
                return
            
            self.user = self.scope["user"]
            
            # Déterminer le nom du groupe
            if self.user_id and self.user.id != self.user_id:
                # Tentative d'accès à un autre utilisateur
                await self.close()
                return
            
            # Joindre le groupe approprié
            if self.group_id:
                self.room_group_name = f'group_{self.group_id}'
            elif self.property_id:
                self.room_group_name = f'property_{self.property_id}'
            elif self.reservation_id:
                self.room_group_name = f'reservation_{self.reservation_id}'
            else:
                # Groupe personnel
                self.room_group_name = f'user_{self.user.id}'
            
            # Joindre le groupe
            await self.channel_layer.group_add(
                self.room_group_name,
                self.channel_name
            )
            
            # Accepter la connexion
            await self.accept()
            
            # Envoyer les notifications non lues
            await self.send_unread_notifications()
            
            # Mettre à jour le last_seen
            await self.update_subscription_last_seen()
            
            logger.info(f"WebSocket connecté: {self.user.username} - {self.room_group_name}")
            
        except Exception as e:
            logger.error(f"Erreur connexion WebSocket: {e}")
            await self.close()
    
    async def disconnect(self, close_code):
        """Gère la déconnexion WebSocket"""
        try:
            if hasattr(self, 'room_group_name'):
                # Quitter le groupe
                await self.channel_layer.group_discard(
                    self.room_group_name,
                    self.channel_name
                )
            
            # Mettre à jour le last_seen
            await self.update_subscription_last_seen()
            
            logger.info(f"WebSocket déconnecté: {self.user.username if hasattr(self, 'user') else 'unknown'}")
            
        except Exception as e:
            logger.error(f"Erreur déconnexion WebSocket: {e}")
    
    async def receive(self, text_data):
        """Gère la réception de messages WebSocket"""
        try:
            text_data_json = json.loads(text_data)
            message_type = text_data_json.get('type')
            
            if message_type == 'mark_read':
                # Marquer une notification comme lue
                notification_id = text_data_json.get('notification_id')
                await self.mark_notification_read(notification_id)
            
            elif message_type == 'get_notifications':
                # Récupérer les notifications
                await self.send_unread_notifications()
            
            elif message_type == 'ping':
                # Ping/Pong pour maintenir la connexion
                await self.send(text_data=json.dumps({
                    'type': 'pong',
                    'timestamp': text_data_json.get('timestamp')
                }))
            
        except json.JSONDecodeError:
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': 'Message JSON invalide'
            }))
        except Exception as e:
            logger.error(f"Erreur réception WebSocket: {e}")
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': 'Erreur traitement message'
            }))
    
    async def send_notification(self, event):
        """Envoie une notification au client (event['notification'] ou event['message'])"""
        try:
            payload = event.get('notification') or event.get('message') or {}
            await self.send(text_data=json.dumps({
                'type': 'notification',
                'notification': payload
            }))
        except Exception as e:
            logger.error(f"Erreur envoi notification WebSocket: {e}")
    
    async def send_unread_notifications(self):
        """Envoie les notifications non lues"""
        try:
            notifications = await self.get_unread_notifications()
            
            await self.send(text_data=json.dumps({
                'type': 'unread_notifications',
                'count': len(notifications),
                'notifications': notifications
            }))
            
        except Exception as e:
            logger.error(f"Erreur récupération notifications: {e}")
    
    @database_sync_to_async
    def get_unread_notifications(self):
        """Récupère les notifications non lues (synchronously)"""
        notifications = Notification.objects.filter(
            recipient=self.user,
            read_at__isnull=True
        ).select_related('template', 'content_type').order_by('-created_at')[:20]
        
        return [
            {
                'id': str(n.id),
                'title': n.title,
                'message': n.message,
                'type': n.notification_type,
                'priority': n.priority,
                'created_at': n.created_at.isoformat(),
                'has_content': n.content_object is not None,
            }
            for n in notifications
        ]
    
    @database_sync_to_async
    def mark_notification_read(self, notification_id):
        """Marque une notification comme lue (synchronously)"""
        try:
            notification = Notification.objects.get(
                id=notification_id,
                recipient=self.user
            )
            notification.mark_as_read()
        except Notification.DoesNotExist:
            pass
    
    @database_sync_to_async
    def update_subscription_last_seen(self):
        """Met à jour le last_seen de l'abonnement (synchronously)"""
        try:
            NotificationSubscription.objects.filter(
                user=self.user,
                channel_type='user',
                is_active=True
            ).update(last_seen=sync_to_async(lambda: None)())  # Utilise la date/heure actuelle
        except Exception:
            pass  # Ignorer les erreurs de mise à jour


class AgentStatusConsumer(AsyncWebsocketConsumer):
    """Consumer pour le statut des agents (interface admin)"""
    
    async def connect(self):
        """Gère la connexion pour le statut des agents"""
        try:
            # Vérifier les permissions admin
            if not self.scope.get("user") or not self.scope["user"].is_authenticated:
                await self.close()
                return
            
            self.user = self.scope["user"]
            
            # Seul les admins et managers peuvent voir le statut des agents
            from apps.core.user_roles import user_has_role, MANAGER_ROLES
            if not (
                self.user.is_superuser
                or self.user.is_staff
                or user_has_role(self.user, MANAGER_ROLES)
            ):
                await self.close()
                return
            
            # Joindre le groupe des administrateurs
            self.room_group_name = 'admin_agents_status'
            
            await self.channel_layer.group_add(
                self.room_group_name,
                self.channel_name
            )
            
            await self.accept()
            
            # Envoyer le statut actuel
            await self.send_agent_status()
            
            logger.info(f"Agent status WebSocket connecté: {self.user.username}")
            
        except Exception as e:
            logger.error(f"Erreur connexion agent status WebSocket: {e}")
            await self.close()
    
    async def disconnect(self, close_code):
        """Gère la déconnexion"""
        if hasattr(self, 'room_group_name'):
            await self.channel_layer.group_discard(
                self.room_group_name,
                self.channel_name
            )
    
    async def receive(self, text_data):
        """Gère la réception de messages"""
        try:
            text_data_json = json.loads(text_data)
            message_type = text_data_json.get('type')
            
            if message_type == 'get_status':
                await self.send_agent_status()
            elif message_type == 'update_agent_status':
                # Seuls les admins peuvent mettre à jour le statut
                if self.user.is_superuser or self.user.is_staff:
                    await self.update_agent_status(text_data_json)
            
        except json.JSONDecodeError:
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': 'Message JSON invalide'
            }))
    
    async def agent_status_update(self, event):
        """Reçoit une mise à jour de statut d'agent"""
        await self.send(text_data=json.dumps({
            'type': 'agent_status_update',
            'agent_status': event['agent_status']
        }))
    
    async def send_agent_status(self):
        """Envoie le statut des agents"""
        try:
            # Cette fonction serait implémentée pour récupérer le statut
            # en temps réel des agents (connectés, occupés, etc.)
            await self.send(text_data=json.dumps({
                'type': 'agent_status',
                'agents': []  # Liste vide pour l'instant
            }))
        except Exception as e:
            logger.error(f"Erreur envoi statut agents: {e}")
    
    @database_sync_to_async
    def update_agent_status(self, data):
        """Met à jour le statut d'un agent (synchronously)"""
        # Implémentation pour mettre à jour le statut d'un agent
        # (en ligne, occupé, en visite, etc.)
        pass


# ============================================================================
# UTILITAIRES
# ============================================================================

async def send_notification_to_user(user_id, notification_data):
    """Fonction utilitaire pour envoyer une notification à un utilisateur"""
    try:
        from channels.layers import get_channel_layer
        
        channel_layer = get_channel_layer()
        if channel_layer:
            await channel_layer.group_send(
                f'user_{user_id}',
                {
                    'type': 'send_notification',
                    'notification': notification_data
                }
            )
    except Exception as e:
        logger.error(f"Erreur envoi notification utilisateur {user_id}: {e}")


async def send_notification_to_group(group_id, notification_data):
    """Fonction utilitaire pour envoyer une notification à un groupe"""
    try:
        from channels.layers import get_channel_layer
        
        channel_layer = get_channel_layer()
        if channel_layer:
            await channel_layer.group_send(
                f'group_{group_id}',
                {
                    'type': 'send_notification',
                    'notification': notification_data
                }
            )
    except Exception as e:
        logger.error(f"Erreur envoi notification groupe {group_id}: {e}")