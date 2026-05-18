"""
Modèles pour le système de notifications en temps réel
Intégration avec Django Channels et WebSockets
"""

import uuid
from django.db import models
from django.contrib.auth import get_user_model
from django.core.validators import MinLengthValidator
from django.conf import settings
from django.utils import timezone
from django.core.mail import send_mail
from django.contrib.contenttypes.models import ContentType
from django.contrib.contenttypes.fields import GenericForeignKey

User = get_user_model()


class NotificationTemplate(models.Model):
    """Modèles de notifications personnalisables"""
    
    TEMPLATE_TYPES = [
        ('reservation', 'Reservation'),
        ('payment', 'Payment'),
        ('property', 'Property'),
        ('client', 'Client'),
        ('agent', 'Agent'),
        ('system', 'System'),
        ('marketing', 'Marketing'),
    ]
    
    CHANNELS = [
        ('websocket', 'WebSocket'),
        ('email', 'Email'),
        ('sms', 'SMS'),
        ('push', 'Push Notification'),
        ('in_app', 'In-App'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100, unique=True)
    template_type = models.CharField(max_length=20, choices=TEMPLATE_TYPES)
    channels = models.JSONField(default=list, help_text="Liste des canaux activés")
    subject = models.CharField(max_length=200, blank=True)
    message_template = models.TextField(validators=[MinLengthValidator(10)])
    variables = models.JSONField(default=dict, help_text="Variables disponibles dans le template")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'notification_template'
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.get_template_type_display()})"


class UserNotificationSetting(models.Model):
    """Préférences de notification par utilisateur"""
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='notification_settings')
    
    # Canaux activés
    email_enabled = models.BooleanField(default=True)
    sms_enabled = models.BooleanField(default=False)
    push_enabled = models.BooleanField(default=True)
    websocket_enabled = models.BooleanField(default=True)
    in_app_enabled = models.BooleanField(default=True)
    
    # Types de notifications
    reservation_notifications = models.BooleanField(default=True)
    payment_notifications = models.BooleanField(default=True)
    property_notifications = models.BooleanField(default=False)
    client_notifications = models.BooleanField(default=False)
    agent_notifications = models.BooleanField(default=False)
    system_notifications = models.BooleanField(default=True)
    marketing_notifications = models.BooleanField(default=False)
    
    # Configuration avancée
    quiet_hours_start = models.TimeField(null=True, blank=True)
    quiet_hours_end = models.TimeField(null=True, blank=True)
    timezone = models.CharField(max_length=50, default='Europe/Paris')
    language = models.CharField(max_length=10, default='fr')
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'user_notification_setting'

    def __str__(self):
        return f"Settings for {self.user.get_full_name() or self.user.username}"

    def is_in_quiet_hours(self):
        """Vérifie si l'utilisateur est en heures silencieuses"""
        if not self.quiet_hours_start or not self.quiet_hours_end:
            return False
        
        import pytz
        from datetime import time
        
        now = timezone.now()
        user_tz = pytz.timezone(self.timezone)
        local_time = now.astimezone(user_tz).time()
        
        return self.quiet_hours_start <= local_time <= self.quiet_hours_end


class NotificationGroup(models.Model):
    """Groupes de notifications pour les utilisateurs"""
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    users = models.ManyToManyField(User, related_name='notification_groups', blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'notification_group'

    def __str__(self):
        return self.name


class Notification(models.Model):
    """Notification principale avec support multi-canal"""
    
    NOTIFICATION_TYPES = [
        ('info', 'Information'),
        ('success', 'Succès'),
        ('warning', 'Avertissement'),
        ('error', 'Erreur'),
        ('urgent', 'Urgent'),
    ]
    
    STATUS_CHOICES = [
        ('pending', 'En attente'),
        ('sent', 'Envoyé'),
        ('delivered', 'Livré'),
        ('read', 'Lu'),
        ('failed', 'Échoué'),
    ]
    
    PRIORITY_CHOICES = [
        ('low', 'Basse'),
        ('normal', 'Normale'),
        ('high', 'Haute'),
        ('urgent', 'Urgente'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # Destinataires
    recipient = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')
    group = models.ForeignKey(NotificationGroup, on_delete=models.CASCADE, null=True, blank=True)
    
    # Contenu
    template = models.ForeignKey(NotificationTemplate, on_delete=models.SET_NULL, null=True, blank=True)
    title = models.CharField(max_length=200)
    message = models.TextField()
    notification_type = models.CharField(max_length=20, choices=NOTIFICATION_TYPES, default='info')
    priority = models.CharField(max_length=20, choices=PRIORITY_CHOICES, default='normal')
    
    # Objet lié (GenericForeignKey)
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE, null=True, blank=True)
    object_id = models.UUIDField(null=True, blank=True)
    content_object = GenericForeignKey('content_type', 'object_id')
    
    # État
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    channels_sent = models.JSONField(default=list)
    delivery_attempts = models.PositiveIntegerField(default=0)
    max_attempts = models.PositiveIntegerField(default=3)
    
    # Données de lecture
    sent_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)
    
    # Métadonnées
    metadata = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'notification'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['recipient', 'status']),
            models.Index(fields=['content_type', 'object_id']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        return f"{self.title} - {self.recipient.get_full_name() or self.recipient.username}"

    def mark_as_read(self):
        """Marque la notification comme lue"""
        if not self.read_at:
            self.read_at = timezone.now()
            self.status = 'read'
            self.save()

    def mark_as_delivered(self, channel):
        """Marque comme livré pour un canal spécifique"""
        if channel not in self.channels_sent:
            self.channels_sent.append(channel)
        
        if not self.delivered_at:
            self.delivered_at = timezone.now()
            self.status = 'delivered'
        
        self.save()

    def mark_as_sent(self, channel):
        """Marque comme envoyé pour un canal spécifique"""
        if channel not in self.channels_sent:
            self.channels_sent.append(channel)
        
        if not self.sent_at:
            self.sent_at = timezone.now()
            self.status = 'sent'
        
        self.save()


class NotificationLog(models.Model):
    """Journal des notifications pour le débogage"""
    
    CHANNELS = [
        ('websocket', 'WebSocket'),
        ('email', 'Email'),
        ('sms', 'SMS'),
        ('push', 'Push'),
        ('in_app', 'In-App'),
    ]
    
    STATUS_CHOICES = [
        ('pending', 'En attente'),
        ('sent', 'Envoyé'),
        ('delivered', 'Livré'),
        ('failed', 'Échoué'),
        ('bounced', 'Rejeté'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    notification = models.ForeignKey(Notification, on_delete=models.CASCADE, related_name='logs')
    channel = models.CharField(max_length=20, choices=CHANNELS)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    external_id = models.CharField(max_length=100, null=True, blank=True)  # ID du service externe
    
    # Messages d'erreur
    error_message = models.TextField(blank=True)
    error_code = models.CharField(max_length=50, null=True, blank=True)
    
    # Métadonnées
    response_data = models.JSONField(default=dict)
    request_data = models.JSONField(default=dict)
    
    # Timing
    sent_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    failed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'notification_log'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['notification', 'channel']),
            models.Index(fields=['status']),
        ]

    def __str__(self):
        return f"{self.notification.title} via {self.get_channel_display()}"


class NotificationSubscription(models.Model):
    """Abonnements pour les notifications en temps réel"""
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='subscriptions')
    channel_name = models.CharField(max_length=100)  # Nom du channel WebSocket
    channel_type = models.CharField(max_length=20, choices=[
        ('user', 'Utilisateur'),
        ('group', 'Groupe'),
        ('property', 'Propriété'),
        ('reservation', 'Réservation'),
    ])
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE, null=True, blank=True)
    object_id = models.UUIDField(null=True, blank=True)
    content_object = GenericForeignKey('content_type', 'object_id')
    
    # État
    is_active = models.BooleanField(default=True)
    last_seen = models.DateTimeField(null=True, blank=True)
    connection_count = models.PositiveIntegerField(default=0)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'notification_subscription'
        unique_together = [
            ('user', 'channel_name', 'content_type', 'object_id')
        ]
        indexes = [
            models.Index(fields=['user', 'is_active']),
            models.Index(fields=['channel_name']),
        ]

    def __str__(self):
        return f"{self.user.get_full_name()} - {self.channel_name}"