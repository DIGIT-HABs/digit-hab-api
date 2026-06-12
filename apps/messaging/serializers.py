"""
Serializers for messaging system.
"""

from rest_framework import serializers
from .models import Conversation, Message
from apps.auth.models import User


class PropertyCardSerializer(serializers.Serializer):
    """
    Résumé propriété pour affichage carte dans le chat (maquette).
    """
    id = serializers.UUIDField(read_only=True)
    title = serializers.CharField(read_only=True)
    city = serializers.CharField(read_only=True)
    price = serializers.DecimalField(max_digits=12, decimal_places=0, read_only=True)
    price_display = serializers.SerializerMethodField()
    primary_image_url = serializers.SerializerMethodField()
    rating = serializers.SerializerMethodField()

    def get_price_display(self, obj):
        if not obj or obj.price is None:
            return None
        return f"{obj.price:,.0f} FCFA".replace(",", " ")

    def get_primary_image_url(self, obj):
        if not obj:
            return None
        primary = obj.images.filter(is_primary=True).first()
        if primary and primary.image:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(primary.image.url)
            return primary.image.url
        first = obj.images.first()
        if first and first.image:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(first.image.url)
            return first.image.url
        if getattr(obj, 'featured_image', None) and obj.featured_image:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.featured_image.url)
            return obj.featured_image.url
        return None

    def get_rating(self, obj):
        return None


def _get_user_avatar_url(user: User, request=None):
    """
    Helper sécurisé pour récupérer l'URL de l'avatar d'un utilisateur.
    Évite les ValueError lorsque aucun fichier n'est associé.
    """
    avatar = getattr(user, "avatar", None)
    # Pour un ImageField/FileField sans fichier, avatar existe mais avatar.name est vide
    if not avatar or not getattr(avatar, "name", ""):
        return None
    try:
        url = avatar.url
        if request and url and not str(url).startswith('http'):
            return request.build_absolute_uri(url)
        return url
    except Exception:
        return None


def _participant_payload(user: User, request=None):
    """Dict standard pour affichage profil dans la messagerie."""
    return {
        'id': str(user.id),
        'name': user.get_full_name() or user.email or user.username,
        'email': user.email or '',
        'avatar': _get_user_avatar_url(user, request),
        'role': getattr(user, 'role', None),
    }


def _resolve_other_user(conversation, current_user):
    """Retrouve l'autre interlocuteur (participants, agent propriété, client CRM)."""
    if not current_user or not getattr(current_user, 'is_authenticated', False):
        return None

    current_pk = current_user.pk
    for participant in conversation.participants.all():
        if participant.pk != current_pk:
            return participant

    prop = getattr(conversation, 'property', None)
    if prop is not None:
        agent = getattr(prop, 'agent', None)
        if agent and agent.pk != current_pk:
            return agent

    client = getattr(conversation, 'client', None)
    if client is not None:
        client_user = getattr(client, 'user', None)
        if client_user and client_user.pk != current_pk:
            return client_user

    return None


class MessageSerializer(serializers.ModelSerializer):
    """
    Serializer for messages.
    """
    sender = serializers.StringRelatedField(read_only=True)
    sender_id = serializers.UUIDField(read_only=True)
    sender_name = serializers.SerializerMethodField()
    sender_avatar = serializers.SerializerMethodField()
    is_own = serializers.SerializerMethodField()
    
    class Meta:
        model = Message
        fields = [
            'id', 'conversation', 'sender', 'sender_id', 'sender_name', 'sender_avatar',
            'message_type', 'content', 'image', 'file',
            'read_by', 'read_at', 'is_edited', 'is_deleted', 'edited_at',
            'is_own', 'created_at', 'updated_at'
        ]
        read_only_fields = [
            'id', 'sender', 'sender_id', 'sender_name', 'sender_avatar',
            'read_by', 'read_at', 'is_edited', 'is_deleted', 'edited_at',
            'is_own', 'created_at', 'updated_at'
        ]
    
    def get_sender_name(self, obj):
        """Get sender full name."""
        return obj.sender.get_full_name() or obj.sender.email
    
    def get_sender_avatar(self, obj):
        """Get sender avatar URL (champ avatar sur User)."""
        request = self.context.get('request')
        return _get_user_avatar_url(obj.sender, request)
    
    def get_is_own(self, obj):
        """Check if message is from current user."""
        request = self.context.get('request')
        if request and request.user:
            return obj.sender.id == request.user.id
        return False


class ConversationSerializer(serializers.ModelSerializer):
    """
    Serializer for conversations.
    """
    participants = serializers.StringRelatedField(many=True, read_only=True)
    participant_ids = serializers.PrimaryKeyRelatedField(
        many=True,
        queryset=User.objects.all(),
        write_only=True,
        source='participants'
    )
    last_message_by_name = serializers.SerializerMethodField()
    unread_count = serializers.SerializerMethodField()
    other_participant = serializers.SerializerMethodField()
    property_detail = serializers.SerializerMethodField()
    
    class Meta:
        model = Conversation
        fields = [
            'id', 'participants', 'participant_ids',
            'conversation_type', 'client', 'property',
            'property_detail',
            'is_active', 'is_archived',
            'last_message', 'last_message_at', 'last_message_by', 'last_message_by_name',
            'unread_count', 'other_participant',
            'created_at', 'updated_at'
        ]
        read_only_fields = [
            'id', 'last_message', 'last_message_at', 'last_message_by',
            'last_message_by_name', 'unread_count', 'other_participant',
            'property_detail', 'created_at', 'updated_at'
        ]
    
    def get_last_message_by_name(self, obj):
        """Get last message sender name."""
        if obj.last_message_by:
            return obj.last_message_by.get_full_name() or obj.last_message_by.email
        return None
    
    def get_unread_count(self, obj):
        """Get unread message count for current user."""
        request = self.context.get('request')
        if request and request.user:
            return obj.get_unread_count(request.user)
        return 0
    
    def get_other_participant(self, obj):
        """Get other participant (not current user)."""
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return None
        other = _resolve_other_user(obj, request.user)
        if other:
            return _participant_payload(other, request)
        return None

    def get_property_detail(self, obj):
        """Résumé propriété pour la carte dans le chat (maquette)."""
        if not obj.property_id:
            return None
        prop = getattr(obj, 'property', None)
        if not prop:
            return None
        return PropertyCardSerializer(prop, context=self.context).data


class ConversationDetailSerializer(ConversationSerializer):
    """
    Detailed serializer for conversation with messages.
    """
    messages = MessageSerializer(many=True, read_only=True)
    
    class Meta(ConversationSerializer.Meta):
        fields = ConversationSerializer.Meta.fields + ['messages']


class CreateMessageSerializer(serializers.ModelSerializer):
    """
    Serializer for creating messages (texte, image ou fichier).
    content optionnel si image ou file fourni.
    conversation est injecté par la vue (send action), pas envoyé dans le formulaire.
    """
    conversation = serializers.PrimaryKeyRelatedField(
        queryset=Conversation.objects.all(),
        required=False,
        write_only=True,
    )
    content = serializers.CharField(required=False, allow_blank=True, default='')

    class Meta:
        model = Message
        fields = ['conversation', 'content', 'message_type', 'image', 'file']

    def validate(self, attrs):
        content = (attrs.get('content') or '').strip()
        image = attrs.get('image')
        file = attrs.get('file')
        if not content and not image and not file:
            raise serializers.ValidationError(
                {'content': 'Indiquez un contenu texte, une image ou un fichier.'}
            )
        return attrs

    def create(self, validated_data):
        """Create message and update conversation."""
        request = self.context.get('request')
        if request and request.user:
            validated_data['sender'] = request.user

        content = (validated_data.get('content') or '').strip()
        if not content:
            if validated_data.get('image'):
                content = '[Image]'
            elif validated_data.get('file'):
                content = '[Fichier]'
        validated_data['content'] = content

        message = Message.objects.create(**validated_data)

        # Update conversation last message
        conversation = message.conversation
        conversation.last_message = content[:100]
        conversation.last_message_at = message.created_at
        conversation.last_message_by = message.sender
        conversation.save(update_fields=['last_message', 'last_message_at', 'last_message_by', 'updated_at'])

        return message
