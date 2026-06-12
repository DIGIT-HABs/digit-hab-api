"""
WebSocket consumers for real-time messaging.
Auth: connexion acceptée d'abord, token JWT requis dans le premier message (type=auth).
"""

import json
import logging
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.contrib.auth import get_user_model
from django.utils import timezone

from .models import Conversation, Message
from .middleware import get_user_from_token

User = get_user_model()
logger = logging.getLogger(__name__)


class ChatConsumer(AsyncWebsocketConsumer):
    """
    WebSocket consumer for real-time chat messaging.
    Client must send {"type": "auth", "token": "<JWT>"} as first message after connect.
    """

    async def connect(self):
        """Accept connection; auth is done on first message (token in body)."""
        self.conversation_id = self.scope['url_route']['kwargs']['conversation_id']
        self.conversation_group_name = f'chat_{self.conversation_id}'
        self.user = None
        self.authenticated = False
        await self.accept()

    async def _finish_connect(self):
        """After auth success: join group and send confirmation."""
        is_participant = await self.check_participant()
        if not is_participant:
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': 'Vous n\'êtes pas participant de cette conversation.',
            }))
            await self.close(code=1008)
            return
        await self.channel_layer.group_add(
            self.conversation_group_name,
            self.channel_name
        )
        await self.send(text_data=json.dumps({
            'type': 'connection',
            'message': 'Connected to conversation',
            'conversation_id': str(self.conversation_id),
            'user_id': str(self.user.id),
        }))
    
    async def disconnect(self, close_code):
        """Handle WebSocket disconnection."""
        if getattr(self, 'authenticated', False):
            await self.channel_layer.group_discard(
                self.conversation_group_name,
                self.channel_name
            )
    
    async def receive(self, text_data):
        """Receive message from WebSocket."""
        try:
            data = json.loads(text_data)
            message_type = data.get('type')

            # First message must be auth with JWT
            if not self.authenticated:
                if message_type != 'auth':
                    await self.send(text_data=json.dumps({
                        'type': 'error',
                        'message': 'Envoyez d\'abord {"type": "auth", "token": "<JWT>"}.',
                    }))
                    await self.close(code=1008)
                    return
                token = data.get('token') or data.get('access')
                if not token:
                    await self.send(text_data=json.dumps({
                        'type': 'error',
                        'message': 'Token manquant dans le message auth.',
                    }))
                    await self.close(code=1008)
                    return
                self.user = await get_user_from_token(token)
                if not self.user or not self.user.is_authenticated:
                    await self.send(text_data=json.dumps({
                        'type': 'error',
                        'message': 'Token invalide ou expiré.',
                    }))
                    await self.close(code=1008)
                    return
                self.authenticated = True
                await self._finish_connect()
                return

            if message_type == 'message':
                # Handle new message
                await self.handle_new_message(data)
            elif message_type == 'edit':
                # Handle message edit
                await self.handle_edit_message(data)
            elif message_type == 'delete':
                # Handle message delete
                await self.handle_delete_message(data)
            elif message_type == 'typing':
                # Handle typing indicator
                await self.handle_typing(data)
            elif message_type == 'read':
                # Handle read receipt
                await self.handle_read_receipt(data)
            else:
                await self.send(text_data=json.dumps({
                    'type': 'error',
                    'message': 'Unknown message type'
                }))
                
        except json.JSONDecodeError:
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': 'Invalid JSON'
            }))
        except Exception as e:
            logger.error(f"Error in receive: {e}")
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': str(e)
            }))
    
    async def handle_new_message(self, data):
        """Handle new message creation."""
        content = data.get('content')
        message_type = data.get('message_type', 'text')
        
        if not content:
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': 'Content is required'
            }))
            return
        
        # Create message in database
        message = await self.create_message(content, message_type)
        
        if message:
            # Broadcast to conversation group
            await self.channel_layer.group_send(
                self.conversation_group_name,
                {
                    'type': 'chat_message',
                    'message': await self.serialize_message(message)
                }
            )
    
    async def handle_typing(self, data):
        """Handle typing indicator."""
        is_typing = data.get('is_typing', False)
        
        # Broadcast typing status to other participants
        await self.channel_layer.group_send(
            self.conversation_group_name,
            {
                'type': 'typing_indicator',
                'user_id': str(self.user.id),
                'user_name': self.user.get_full_name() or self.user.email,
                'is_typing': is_typing
            }
        )
    
    async def handle_read_receipt(self, data):
        """Handle read receipt."""
        message_id = data.get('message_id')
        
        if message_id:
            # Mark message as read
            await self.mark_message_read(message_id)
            
            # Broadcast read receipt
            await self.channel_layer.group_send(
                self.conversation_group_name,
                {
                    'type': 'read_receipt',
                    'message_id': str(message_id),
                    'user_id': str(self.user.id),
                    'read_at': timezone.now().isoformat()
                }
            )
    
    async def handle_edit_message(self, data):
        """Handle message edition."""
        message_id = data.get('message_id')
        content = data.get('content')
        if not message_id or not content:
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': 'message_id et content sont requis pour éditer un message.'
            }))
            return
        message = await self.edit_message(message_id, content)
        if message:
            await self.channel_layer.group_send(
                self.conversation_group_name,
                {
                    'type': 'chat_message',
                    'message': await self.serialize_message(message)
                }
            )
    
    async def handle_delete_message(self, data):
        """Handle message deletion (soft delete)."""
        message_id = data.get('message_id')
        if not message_id:
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': 'message_id est requis pour supprimer un message.'
            }))
            return
        message = await self.delete_message(message_id)
        if message:
            await self.channel_layer.group_send(
                self.conversation_group_name,
                {
                    'type': 'chat_message',
                    'message': await self.serialize_message(message)
                }
            )
    
    # WebSocket message handlers
    
    async def chat_message(self, event):
        """Send chat message to WebSocket."""
        await self.send(text_data=json.dumps({
            'type': 'message',
            'data': event['message']
        }))
    
    async def typing_indicator(self, event):
        """Send typing indicator to WebSocket."""
        # Don't send typing indicator to the user who is typing
        if str(self.user.id) != event['user_id']:
            await self.send(text_data=json.dumps({
                'type': 'typing',
                'user_id': event['user_id'],
                'user_name': event['user_name'],
                'is_typing': event['is_typing']
            }))
    
    async def read_receipt(self, event):
        """Send read receipt to WebSocket."""
        await self.send(text_data=json.dumps({
            'type': 'read',
            'message_id': event['message_id'],
            'user_id': event['user_id'],
            'read_at': event['read_at']
        }))
    
    # Database operations
    
    @database_sync_to_async
    def check_participant(self):
        """Check if user is a participant of the conversation."""
        try:
            conversation = Conversation.objects.get(id=self.conversation_id)
            return self.user in conversation.participants.all()
        except Conversation.DoesNotExist:
            return False
    
    @database_sync_to_async
    def create_message(self, content, message_type='text'):
        """Create a new message in the database."""
        try:
            conversation = Conversation.objects.get(id=self.conversation_id)
            
            message = Message.objects.create(
                conversation=conversation,
                sender=self.user,
                content=content,
                message_type=message_type
            )
            
            # Update conversation last message
            conversation.last_message = content[:100]
            conversation.last_message_at = message.created_at
            conversation.last_message_by = self.user
            conversation.save(update_fields=['last_message', 'last_message_at', 'last_message_by', 'updated_at'])
            
            return message
        except Exception as e:
            logger.error(f"Error creating message: {e}")
            return None
    
    @database_sync_to_async
    def edit_message(self, message_id, content):
        """Edit an existing message (sender only)."""
        try:
            message = Message.objects.get(id=message_id, conversation_id=self.conversation_id)
            if message.sender != self.user:
                return None
            message.content = content
            message.is_edited = True
            message.edited_at = timezone.now()
            message.save(update_fields=['content', 'is_edited', 'edited_at', 'updated_at'])
            # Mettre à jour la conversation si besoin
            conversation = message.conversation
            if conversation.last_message_at == message.created_at:
                conversation.last_message = content[:100]
                conversation.last_message_by = self.user
                conversation.last_message_at = message.created_at
                conversation.save(update_fields=['last_message', 'last_message_at', 'last_message_by', 'updated_at'])
            return message
        except Exception as e:
            logger.error(f"Error editing message: {e}")
            return None
    
    @database_sync_to_async
    def delete_message(self, message_id):
        """Soft delete a message (sender only)."""
        try:
            message = Message.objects.get(id=message_id, conversation_id=self.conversation_id)
            if message.sender != self.user:
                return None
            message.is_deleted = True
            message.content = ""
            message.image = None
            message.file = None
            message.save(update_fields=['is_deleted', 'content', 'image', 'file', 'updated_at'])
            return message
        except Exception as e:
            logger.error(f"Error deleting message: {e}")
            return None
    
    @database_sync_to_async
    def serialize_message(self, message):
        """Serialize message for WebSocket."""
        from .serializers import _get_user_avatar_url

        return {
            'id': str(message.id),
            'conversation': str(message.conversation.id),
            'conversation_id': str(message.conversation.id),
            'sender_id': str(message.sender.id),
            'sender_name': message.sender.get_full_name() or message.sender.email,
            'sender_avatar': _get_user_avatar_url(message.sender),
            'sender_email': message.sender.email,
            'content': message.content,
            'message_type': message.message_type,
            'image': message.image.url if message.image and getattr(message.image, 'name', '') else None,
            'file': message.file.url if message.file and getattr(message.file, 'name', '') else None,
            'is_deleted': message.is_deleted,
            'created_at': message.created_at.isoformat(),
            'is_own': message.sender.id == self.user.id,
        }
    
    @database_sync_to_async
    def mark_message_read(self, message_id):
        """Mark a message as read."""
        try:
            message = Message.objects.get(id=message_id, conversation_id=self.conversation_id)
            if not message.read_by:
                message.read_by = self.user
                message.read_at = timezone.now()
                message.save(update_fields=['read_by', 'read_at', 'updated_at'])
        except Message.DoesNotExist:
            pass

