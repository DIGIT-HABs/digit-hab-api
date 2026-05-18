"""
Serializers pour le système de notifications
Validation et sérialisation des données
"""

from rest_framework import serializers
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone

from .models import (
    Notification, NotificationTemplate, UserNotificationSetting,
    NotificationGroup, NotificationLog, NotificationSubscription
)

User = get_user_model()


class UserBasicSerializer(serializers.ModelSerializer):
    """Serializer basique pour les utilisateurs"""
    
    class Meta:
        model = User
        fields = ['id', 'username', 'first_name', 'last_name', 'email']
        read_only_fields = ['id']


class NotificationTemplateSerializer(serializers.ModelSerializer):
    """Serializer pour les modèles de notifications"""
    
    class Meta:
        model = NotificationTemplate
        fields = [
            'id', 'name', 'template_type', 'channels', 'subject',
            'message_template', 'variables', 'is_active', 'created_at'
        ]
        read_only_fields = ['id', 'created_at']
    
    def validate_channels(self, value):
        """Valide que les canaux spécifiés sont valides"""
        valid_channels = ['websocket', 'email', 'sms', 'push', 'in_app']
        for channel in value:
            if channel not in valid_channels:
                raise serializers.ValidationError(f"Canal invalide: {channel}")
        return value


class UserNotificationSettingSerializer(serializers.ModelSerializer):
    """Serializer pour les paramètres de notification utilisateur"""
    
    user = UserBasicSerializer(read_only=True)
    
    class Meta:
        model = UserNotificationSetting
        fields = [
            'id', 'user', 'email_enabled', 'sms_enabled', 'push_enabled',
            'websocket_enabled', 'in_app_enabled', 'reservation_notifications',
            'payment_notifications', 'property_notifications', 'client_notifications',
            'agent_notifications', 'system_notifications', 'marketing_notifications',
            'quiet_hours_start', 'quiet_hours_end', 'timezone', 'language'
        ]
        read_only_fields = ['id']
    
    def validate_timezone(self, value):
        """Valide que le fuseau horaire est valide"""
        try:
            import pytz
            pytz.timezone(value)
        except:
            raise serializers.ValidationError("Fuseau horaire invalide")
        return value


class NotificationGroupSerializer(serializers.ModelSerializer):
    """Serializer pour les groupes de notifications"""
    
    users = UserBasicSerializer(many=True, read_only=True)
    users_data = serializers.ListField(
        child=serializers.UUIDField(),
        write_only=True,
        required=False
    )
    
    class Meta:
        model = NotificationGroup
        fields = [
            'id', 'name', 'description', 'users', 'users_data', 
            'is_active', 'created_at'
        ]
        read_only_fields = ['id', 'created_at']
    
    def create(self, validated_data):
        users_data = validated_data.pop('users_data', [])
        group = NotificationGroup.objects.create(**validated_data)
        
        if users_data:
            users = User.objects.filter(id__in=users_data)
            group.users.set(users)
        
        return group
    
    def update(self, instance, validated_data):
        users_data = validated_data.pop('users_data', None)
        
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        
        if users_data is not None:
            users = User.objects.filter(id__in=users_data)
            instance.users.set(users)
        
        return instance


class NotificationLogSerializer(serializers.ModelSerializer):
    """Serializer pour les journaux de notifications"""
    
    channel = serializers.ChoiceField(choices=NotificationLog.CHANNELS)
    status = serializers.ChoiceField(choices=NotificationLog.STATUS_CHOICES)
    
    class Meta:
        model = NotificationLog
        fields = [
            'id', 'channel', 'status', 'external_id', 'error_message',
            'error_code', 'response_data', 'request_data', 'sent_at',
            'delivered_at', 'failed_at', 'created_at'
        ]
        read_only_fields = ['id', 'created_at']


class NotificationSerializer(serializers.ModelSerializer):
    """Serializer principal pour les notifications"""
    
    recipient = UserBasicSerializer(read_only=True)
    template = NotificationTemplateSerializer(read_only=True)
    content_type_name = serializers.CharField(source='content_type.model', read_only=True)
    
    # Champs pour la création
    recipient_id = serializers.UUIDField(write_only=True, required=False)
    template_id = serializers.UUIDField(write_only=True, required=False)
    content_type_id = serializers.IntegerField(write_only=True, required=False)
    object_id = serializers.UUIDField(write_only=True, required=False, allow_null=True)
    
    class Meta:
        model = Notification
        fields = [
            'id', 'recipient', 'recipient_id', 'group', 'template', 'template_id',
            'title', 'message', 'notification_type', 'priority', 
            'content_type', 'content_type_id', 'content_type_name', 'object_id',
            'status', 'channels_sent', 'delivery_attempts', 'max_attempts',
            'sent_at', 'delivered_at', 'read_at', 'metadata', 'created_at'
        ]
        read_only_fields = [
            'id', 'recipient', 'template', 'status', 'channels_sent', 
            'delivery_attempts', 'sent_at', 'delivered_at', 'read_at', 'created_at'
        ]
    
    def validate_priority(self, value):
        """Valide la priorité de la notification"""
        if value not in dict(Notification.PRIORITY_CHOICES):
            raise serializers.ValidationError("Priorité invalide")
        return value
    
    def validate_recipient_id(self, value):
        """Valide l'ID du destinataire"""
        try:
            User.objects.get(id=value)
        except User.DoesNotExist:
            raise serializers.ValidationError("Utilisateur introuvable")
        return value
    
    def validate_template_id(self, value):
        """Valide l'ID du template"""
        try:
            NotificationTemplate.objects.get(id=value)
        except NotificationTemplate.DoesNotExist:
            raise serializers.ValidationError("Template introuvable")
        return value
    
    def validate_content_type_id(self, value):
        """Valide l'ID du type de contenu"""
        try:
            ContentType.objects.get_for_id(value)
        except ContentType.DoesNotExist:
            raise serializers.ValidationError("Type de contenu introuvable")
        return value
    
    def create(self, validated_data):
        # Extraire les IDs pour la création
        recipient_id = validated_data.pop('recipient_id', None)
        template_id = validated_data.pop('template_id', None)
        content_type_id = validated_data.pop('content_type_id', None)
        object_id = validated_data.pop('object_id', None)
        
        # Créer la notification
        notification = Notification.objects.create(**validated_data)
        
        # Associer les relations si fournies
        if recipient_id:
            try:
                notification.recipient_id = recipient_id
            except User.DoesNotExist:
                pass
        
        if template_id:
            try:
                notification.template_id = template_id
            except NotificationTemplate.DoesNotExist:
                pass
        
        if content_type_id and object_id:
            try:
                content_type = ContentType.objects.get_for_id(content_type_id)
                notification.content_type = content_type
                notification.object_id = object_id
            except ContentType.DoesNotExist:
                pass
        
        notification.save()
        return notification


class NotificationCreateSerializer(serializers.Serializer):
    """Serializer pour la création de notifications"""
    
    # Destinataires
    recipient_id = serializers.UUIDField(required=False)
    recipient_ids = serializers.ListField(
        child=serializers.UUIDField(),
        required=False
    )
    group_id = serializers.UUIDField(required=False)
    
    # Template ou contenu personnalisé
    template_id = serializers.UUIDField(required=False)
    title = serializers.CharField(max_length=200, required=False)
    message = serializers.CharField(max_length=2000, required=False)
    notification_type = serializers.ChoiceField(
        choices=Notification.NOTIFICATION_TYPES,
        default='info'
    )
    priority = serializers.ChoiceField(
        choices=Notification.PRIORITY_CHOICES,
        default='normal'
    )
    
    # Objet lié
    content_type_id = serializers.IntegerField(required=False)
    object_id = serializers.UUIDField(required=False, allow_null=True)
    
    # Canaux
    channels = serializers.ListField(
        child=serializers.CharField(),
        required=False
    )
    
    # Variables pour le template
    variables = serializers.DictField(default=dict)
    
    def validate(self, data):
        """Validation globale"""
        # Au moins un destinataire
        if not any([data.get('recipient_id'), data.get('recipient_ids'), data.get('group_id')]):
            raise serializers.ValidationError(
                "Au moins un destinataire doit être spécifié"
            )
        
        # Template ou contenu personnalisé
        if not any([data.get('template_id'), data.get('title') and data.get('message')]):
            raise serializers.ValidationError(
                "Un template ou du contenu personnalisé doit être fourni"
            )
        
        return data
    
    def validate_channels(self, value):
        """Valide les canaux spécifiés"""
        valid_channels = ['websocket', 'email', 'sms', 'push', 'in_app']
        for channel in value:
            if channel not in valid_channels:
                raise serializers.ValidationError(f"Canal invalide: {channel}")
        return value


class NotificationSubscriptionSerializer(serializers.ModelSerializer):
    """Serializer pour les abonnements aux canaux"""
    
    user = UserBasicSerializer(read_only=True)
    content_type_name = serializers.CharField(source='content_type.model', read_only=True)
    
    # Champs pour la création
    content_type_id = serializers.IntegerField(write_only=True, required=False)
    object_id = serializers.UUIDField(write_only=True, required=False, allow_null=True)
    
    class Meta:
        model = NotificationSubscription
        fields = [
            'id', 'user', 'channel_name', 'channel_type', 'content_type',
            'content_type_id', 'content_type_name', 'object_id', 'is_active',
            'last_seen', 'connection_count', 'created_at'
        ]
        read_only_fields = [
            'id', 'user', 'last_seen', 'connection_count', 'created_at'
        ]
    
    def validate_channel_type(self, value):
        """Valide le type de canal"""
        valid_types = ['user', 'group', 'property', 'reservation']
        if value not in valid_types:
            raise serializers.ValidationError("Type de canal invalide")
        return value
    
    def create(self, validated_data):
        content_type_id = validated_data.pop('content_type_id', None)
        object_id = validated_data.pop('object_id', None)
        
        subscription = NotificationSubscription.objects.create(**validated_data)
        
        if content_type_id and object_id:
            try:
                content_type = ContentType.objects.get_for_id(content_type_id)
                subscription.content_type = content_type
                subscription.object_id = object_id
                subscription.save()
            except ContentType.DoesNotExist:
                pass
        
        return subscription


class NotificationStatsSerializer(serializers.Serializer):
    """Serializer pour les statistiques de notifications"""
    
    total_notifications = serializers.IntegerField()
    unread_notifications = serializers.IntegerField()
    sent_today = serializers.IntegerField()
    failed_notifications = serializers.IntegerField()
    by_type = serializers.DictField()
    by_priority = serializers.DictField()
    by_channel = serializers.DictField()
    response_rate = serializers.FloatField()