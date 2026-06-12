"""
Views for messaging system.
"""

import uuid as uuid_module
from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.filters import SearchFilter, OrderingFilter
from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Q, Count, Max, Prefetch
from django.utils import timezone
from django.contrib.auth import get_user_model

from .models import Conversation, Message

User = get_user_model()
from .serializers import (
    ConversationSerializer,
    ConversationDetailSerializer,
    MessageSerializer,
    CreateMessageSerializer
)


class ConversationViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing conversations.
    """
    queryset = Conversation.objects.select_related(
        'property',
        'property__agent',
        'client',
        'client__user',
        'last_message_by',
    ).prefetch_related(
        # Prefetch complet : filter(participants=user) sinon ne charge que l'utilisateur courant
        Prefetch('participants', queryset=User.objects.all()),
        'messages',
        'property__images',
    ).all()
    serializer_class = ConversationSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = {
        'conversation_type': ['exact'],
        'is_active': ['exact'],
        'is_archived': ['exact'],
        'client': ['exact'],
        'property': ['exact'],
    }
    search_fields = ['last_message']
    ordering_fields = ['last_message_at', 'created_at']
    ordering = ['-last_message_at', '-created_at']
    
    def get_queryset(self):
        """Filter conversations for current user."""
        user = self.request.user
        queryset = super().get_queryset()
        
        # Only show conversations where user is a participant
        queryset = queryset.filter(participants=user)
        
        # Filter by archived status if requested
        is_archived = self.request.query_params.get('is_archived', 'false')
        if is_archived.lower() == 'true':
            queryset = queryset.filter(is_archived=True)
        else:
            queryset = queryset.filter(is_archived=False)
        
        return queryset.distinct()
    
    def get_serializer_class(self):
        """Return appropriate serializer."""
        if self.action == 'retrieve':
            return ConversationDetailSerializer
        return ConversationSerializer
    
    @action(detail=True, methods=['get'])
    def messages(self, request, pk=None):
        """Get messages for a conversation."""
        conversation = self.get_object()
        messages = conversation.messages.filter(is_deleted=False).order_by('created_at')
        
        # Mark messages as read
        unread_messages = messages.filter(
            read_by__isnull=True
        ).exclude(sender=request.user)
        
        if unread_messages.exists():
            unread_messages.update(
                read_by=request.user,
                read_at=timezone.now()
            )
        
        serializer = MessageSerializer(messages, many=True, context={'request': request})
        return Response(serializer.data)
    
    @action(detail=True, methods=['post'])
    def send(self, request, pk=None):
        """Send a message in a conversation."""
        conversation = self.get_object()
        
        # Check if user is a participant
        if request.user not in conversation.participants.all():
            return Response(
                {'error': 'Vous n\'êtes pas participant de cette conversation.'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        serializer = CreateMessageSerializer(
            data=request.data,
            context={'request': request}
        )
        
        if serializer.is_valid():
            serializer.save(conversation=conversation)
            message_serializer = MessageSerializer(
                serializer.instance,
                context={'request': request}
            )
            return Response(message_serializer.data, status=status.HTTP_201_CREATED)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    @action(detail=True, methods=['post'])
    def mark_read(self, request, pk=None):
        """Mark conversation as read."""
        conversation = self.get_object()
        conversation.mark_as_read(request.user)
        return Response({'status': 'marked as read'})
    
    @action(detail=True, methods=['post'])
    def archive(self, request, pk=None):
        """Archive/unarchive conversation."""
        conversation = self.get_object()
        conversation.is_archived = not conversation.is_archived
        conversation.save(update_fields=['is_archived', 'updated_at'])
        serializer = self.get_serializer(conversation)
        return Response(serializer.data)
    
    @action(detail=False, methods=['post'])
    def create_with_participants(self, request):
        """Create a conversation with participants."""
        raw_ids = request.data.get('participant_ids', [])
        # Accept single ID (string) or list
        if isinstance(raw_ids, str):
            raw_ids = [raw_ids] if raw_ids.strip() else []
        if not raw_ids:
            return Response(
                {'error': 'Au moins un participant est requis.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        # Normalize to unique string IDs, then to UUIDs for query
        participant_ids = list({str(pid).strip() for pid in raw_ids})
        current_id = str(request.user.id)
        if current_id not in participant_ids:
            participant_ids.append(current_id)
        try:
            uuid_list = [uuid_module.UUID(pid) for pid in participant_ids]
        except (ValueError, TypeError) as e:
            return Response(
                {'error': f'Format d\'ID invalide: {str(e)}'},
                status=status.HTTP_400_BAD_REQUEST
            )
        participants = User.objects.filter(id__in=uuid_list)
        if participants.count() != len(uuid_list):
            return Response(
                {'error': 'Un ou plusieurs participants introuvables.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        property_id = request.data.get('property_id')

        # Check if conversation already exists (même participants + même propriété si fournie)
        existing = Conversation.objects.filter(participants=request.user)
        if property_id:
            existing = existing.filter(property_id=property_id)
        existing = existing.annotate(participant_count=Count('participants')).filter(
            participant_count=len(participant_ids)
        )
        for participant in participants:
            existing = existing.filter(participants=participant)

        if existing.exists():
            conversation = existing.first()
            # Réparer les participants manquants (ex. agent absent du M2M)
            conversation.participants.set(participants)
            serializer = self.get_serializer(conversation, context={'request': request})
            return Response(serializer.data)
        
        # Create new conversation
        conversation = Conversation.objects.create(
            conversation_type=request.data.get('conversation_type', 'direct'),
            client_id=request.data.get('client_id'),
            property_id=request.data.get('property_id'),
        )
        conversation.participants.set(participants)
        
        serializer = self.get_serializer(conversation, context={'request': request})
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class MessageViewSet(viewsets.ModelViewSet):
    """
    ViewSet for viewing and managing messages.
    - list/retrieve : lecture
    - update        : modification (expéditeur uniquement)
    - destroy       : suppression logique (soft delete, expéditeur uniquement)
    - mark_read     : marquer un message comme lu
    """
    queryset = Message.objects.select_related('sender', 'conversation').all()
    serializer_class = MessageSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_fields = {
        'conversation': ['exact'],
        'sender': ['exact'],
        'message_type': ['exact'],
        'read_by': ['exact'],
    }
    ordering_fields = ['created_at']
    ordering = ['-created_at']
    
    def get_queryset(self):
        """Filter messages for current user."""
        user = self.request.user
        queryset = super().get_queryset()
        
        # Only show messages from conversations where user is a participant
        queryset = queryset.filter(conversation__participants=user)
        
        return queryset.distinct()
    
    def perform_update(self, serializer):
        """Allow sender to edit their own message (soft edit)."""
        message = self.get_object()
        request = self.request
        if message.sender != request.user:
            return Response(
                {'error': "Vous ne pouvez modifier que vos propres messages."},
                status=status.HTTP_403_FORBIDDEN,
            )
        # Marquer comme modifié
        serializer.save(is_edited=True, edited_at=timezone.now())
    
    def perform_destroy(self, instance):
        """Soft delete: marquer le message comme supprimé au lieu de le supprimer physiquement."""
        request = self.request
        if instance.sender != request.user:
            raise PermissionDenied("Vous ne pouvez supprimer que vos propres messages.")
        instance.is_deleted = True
        # On vide le contenu textuel, garde éventuellement les méta
        instance.content = ""
        instance.image = None
        instance.file = None
        instance.save(update_fields=['is_deleted', 'content', 'image', 'file', 'updated_at'])
    
    @action(detail=True, methods=['post'])
    def mark_read(self, request, pk=None):
        """Mark message as read."""
        message = self.get_object()
        message.mark_as_read(request.user)
        serializer = self.get_serializer(message)
        return Response(serializer.data)
