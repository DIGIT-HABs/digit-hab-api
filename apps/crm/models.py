"""
Models for CRM (Client Relationship Management) system.
"""

import uuid
import math
from django.db import models
# from django.contrib.gis.db import models as gis_models
from django.core.validators import MinValueValidator, MaxValueValidator
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from apps.auth.models import User, Agency
from apps.properties.models import Property


class ClientProfile(models.Model):
    """
    Extended profile information for client users.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='client_profile')
    
    # Personal Information
    date_of_birth = models.DateField(null=True, blank=True)
    nationality = models.CharField(max_length=100, blank=True)
    marital_status = models.CharField(
        max_length=20,
        choices=[
            ('single', 'Célibataire'),
            ('married', 'Marié(e)'),
            ('divorced', 'Divorcé(e)'),
            ('widowed', 'Veuf/Veuve'),
            ('partnership', 'Union civile'),
        ],
        blank=True
    )
    
    # Contact Preferences
    preferred_contact_method = models.CharField(
        max_length=20,
        choices=[
            ('email', 'Email'),
            ('phone', 'Téléphone'),
            ('sms', 'SMS'),
            ('whatsapp', 'WhatsApp'),
        ],
        default='email'
    )
    preferred_contact_time = models.CharField(
        max_length=50,
        choices=[
            ('morning', 'Matin (8h-12h)'),
            ('afternoon', 'Après-midi (12h-18h)'),
            ('evening', 'Soirée (18h-20h)'),
            ('anytime', 'À tout moment'),
        ],
        default='anytime'
    )
    
    # Property Preferences
    max_budget = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    min_budget = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    preferred_property_types = models.JSONField(default=list, blank=True)
    preferred_locations = models.JSONField(default=list, blank=True)
    min_bedrooms = models.IntegerField(default=0, validators=[MinValueValidator(0)])
    max_bedrooms = models.IntegerField(null=True, blank=True, validators=[MinValueValidator(0)])
    min_area = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(0)])
    max_area = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(0)])
    
    # Location Preferences
    preferred_cities = models.JSONField(default=list, blank=True)
    max_distance_from_center = models.IntegerField(default=10, help_text="Distance maximale du centre-ville en km")
    
    # Financial Information
    financing_status = models.CharField(
        max_length=20,
        choices=[
            ('cash', 'Financement personnel'),
            ('mortgage', 'Prêt immobilier'),
            ('not_sure', 'Non défini'),
            ('pre_approved', 'Pré-approbation obtenue'),
        ],
        default='not_sure'
    )
    credit_score_range = models.CharField(
        max_length=20,
        choices=[
            ('excellent', 'Excellent (750+)'),
            ('good', 'Bon (650-749)'),
            ('fair', 'Moyen (600-649)'),
            ('poor', 'Faible (<600)'),
            ('unknown', 'Inconnu'),
        ],
        default='unknown'
    )
    
    # Additional Preferences
    must_have_features = models.JSONField(default=list, blank=True)
    deal_breakers = models.JSONField(default=list, blank=True)
    lifestyle_notes = models.TextField(blank=True, help_text="Notes sur le mode de vie, habitudes, etc.")
    
    # Status and Activity
    status = models.CharField(
        max_length=20,
        choices=[
            ('active', 'Actif'),
            ('inactive', 'Inactif'),
            ('prospect', 'Prospect'),
            ('client', 'Client'),
            ('archived', 'Archivé'),
        ],
        default='prospect'
    )
    priority_level = models.CharField(
        max_length=20,
        choices=[
            ('low', 'Faible'),
            ('medium', 'Moyen'),
            ('high', 'Élevé'),
            ('urgent', 'Urgent'),
        ],
        default='medium'
    )
    
    # Activity Tracking
    last_property_view = models.DateTimeField(null=True, blank=True)
    total_properties_viewed = models.IntegerField(default=0)
    total_inquiries_made = models.IntegerField(default=0)
    conversion_score = models.IntegerField(default=0, validators=[MinValueValidator(0), MaxValueValidator(100)])
    
    # Tags & Organization (Phase 1)
    tags = models.JSONField(
        default=list,
        blank=True,
        help_text="Tags pour catégoriser le client (ex: ['vip', 'investisseur', 'premier_achat'])"
    )
    
    # Dates
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'crm_client_profile'
        verbose_name = 'Profil Client'
        verbose_name_plural = 'Profils Clients'
    
    def __str__(self):
        return f"Profil de {self.user.get_full_name() or self.user.username}"
    
    def update_activity(self):
        """Update client activity statistics."""
        self.total_properties_viewed = PropertyInterest.objects.filter(client=self.user).count()
        self.total_inquiries_made = ClientInteraction.objects.filter(client=self.user, interaction_type='inquiry').count()
        
        # Calculate conversion score based on various factors
        self.calculate_conversion_score()
        self.save(update_fields=['total_properties_viewed', 'total_inquiries_made', 'conversion_score', 'last_property_view'])
    
    def calculate_conversion_score(self):
        """Calculate client conversion score (0-100)."""
        score = 0
        
        # Base score from activity
        score += min(self.total_properties_viewed * 2, 20)  # Max 20 points
        score += min(self.total_inquiries_made * 3, 30)  # Max 30 points
        
        # Priority level bonus
        priority_bonuses = {'low': 0, 'medium': 5, 'high': 10, 'urgent': 15}
        score += priority_bonuses.get(self.priority_level, 0)
        
        # Status bonus
        status_bonuses = {'prospect': 0, 'active': 10, 'client': 20}
        score += status_bonuses.get(self.status, 0)
        
        # Financial readiness bonus
        finance_bonuses = {
            'cash': 15, 'pre_approved': 20, 'mortgage': 10, 'not_sure': 0
        }
        score += finance_bonuses.get(self.financing_status, 0)
        
        # Recent activity bonus (last 30 days)
        if self.last_property_view and (timezone.now() - self.last_property_view).days <= 30:
            score += 10
        
        # Clamp score to 0-100
        self.conversion_score = min(score, 100)
    
    def get_matching_properties(self, limit=10):
        """
        Get properties that match client preferences.
        This is the core of the automatic matching system.
        """
        from .matching import PropertyMatcher
        
        matcher = PropertyMatcher(self)
        return matcher.find_matches(limit=limit)
    
    def get_match_score(self, property_obj):
        """Get match score for a specific property (0-100)."""
        from .matching import PropertyMatcher
        
        matcher = PropertyMatcher(self)
        return matcher.calculate_match_score(property_obj)


class PropertyInterest(models.Model):
    """
    Track client interest in specific properties.
    """
    INTERACTION_TYPES = [
        ('view', 'Vue'),
        ('favorite', 'Favori'),
        ('inquiry', 'Demande d\'informations'),
        ('visit_request', 'Demande de visite'),
        ('visit_scheduled', 'Visite programmée'),
        ('offer_made', 'Offre soumise'),
        ('offer_rejected', 'Offre refusée'),
        ('purchase_completed', 'Achat complété'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    client = models.ForeignKey(User, on_delete=models.CASCADE, related_name='property_interests')
    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name='client_interests')
    
    interaction_type = models.CharField(max_length=20, choices=INTERACTION_TYPES)
    interaction_date = models.DateTimeField(default=timezone.now)
    notes = models.TextField(blank=True)
    
    # Interest tracking
    interest_level = models.CharField(
        max_length=20,
        choices=[
            ('low', 'Faible'),
            ('medium', 'Moyen'),
            ('high', 'Élevé'),
            ('very_high', 'Très élevé'),
        ],
        default='medium'
    )
    match_score = models.IntegerField(default=0, validators=[MinValueValidator(0), MaxValueValidator(100)])
    
    # Status tracking
    status = models.CharField(
        max_length=20,
        choices=[
            ('active', 'Actif'),
            ('archived', 'Archivé'),
            ('converted', 'Converti'),
            ('lost', 'Perdu'),
        ],
        default='active'
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'crm_property_interest'
        verbose_name = 'Intérêt Propriété'
        verbose_name_plural = 'Intérêts Propriétés'
        unique_together = ['client', 'property']
        ordering = ['-interaction_date']
    
    def __str__(self):
        return f"{self.client.get_full_name()} - {self.property.title}"
    
    def save(self, *args, **kwargs):
        """Override save to calculate match score if not set."""
        if not self.match_score and hasattr(self.client, 'client_profile'):
            self.match_score = self.client.client_profile.get_match_score(self.property)
        super().save(*args, **kwargs)
    
    @classmethod
    def create_from_interaction(cls, client, property_obj, interaction_type, notes=''):
        """Create interest from user interaction."""
        interest, created = cls.objects.get_or_create(
            client=client,
            property=property_obj,
            defaults={
                'interaction_type': interaction_type,
                'notes': notes,
                'interest_level': 'medium'
            }
        )
        
        if not created:
            # Update existing interest
            interest.interaction_type = interaction_type
            interest.interaction_date = timezone.now()
            interest.notes = notes
            interest.save()
        
        # Update client activity
        if hasattr(client, 'client_profile'):
            client.client_profile.last_property_view = timezone.now()
            client.client_profile.save(update_fields=['last_property_view', 'updated_at'])
        
        return interest


class ClientInteraction(models.Model):
    """
    Track all client interactions and communications.
    """
    INTERACTION_TYPES = [
        ('call', 'Appel téléphonique'),
        ('email', 'Email'),
        ('sms', 'SMS'),
        ('meeting', 'Rendez-vous'),
        ('visit', 'Visite'),
        ('inquiry', 'Demande d\'informations'),
        ('follow_up', 'Relance'),
        ('complaint', 'Réclamation'),
        ('feedback', 'Retour client'),
    ]
    
    INTERACTION_CHANNELS = [
        ('phone', 'Téléphone'),
        ('email', 'Email'),
        ('sms', 'SMS'),
        ('whatsapp', 'WhatsApp'),
        ('in_person', 'En personne'),
        ('video_call', 'Appel vidéo'),
        ('portal', 'Portail client'),
    ]
    
    OUTCOMES = [
        ('successful', 'Réussi'),
        ('unsuccessful', 'Échoué'),
        ('callback_requested', 'Rappel demandé'),
        ('follow_up_required', 'Suivi requis'),
        ('meeting_scheduled', 'Rendez-vous programmé'),
        ('no_response', 'Pas de réponse'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    client = models.ForeignKey(User, on_delete=models.CASCADE, related_name='interactions')
    agent = models.ForeignKey(User, on_delete=models.CASCADE, related_name='client_interactions')
    
    interaction_type = models.CharField(max_length=20, choices=INTERACTION_TYPES)
    channel = models.CharField(max_length=20, choices=INTERACTION_CHANNELS)
    subject = models.CharField(max_length=200, blank=True)
    content = models.TextField()
    outcome = models.CharField(max_length=20, choices=OUTCOMES, blank=True)
    
    # Timing
    scheduled_date = models.DateTimeField(null=True, blank=True)
    completed_date = models.DateTimeField(null=True, blank=True)
    duration_minutes = models.IntegerField(null=True, blank=True)
    
    # Related objects
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE, null=True, blank=True)
    object_id = models.UUIDField(null=True, blank=True)
    related_object = GenericForeignKey('content_type', 'object_id')
    
    # Follow-up
    requires_follow_up = models.BooleanField(default=False)
    follow_up_date = models.DateTimeField(null=True, blank=True)
    follow_up_completed = models.BooleanField(default=False)
    
    # Priority and status
    priority = models.CharField(
        max_length=20,
        choices=[
            ('low', 'Faible'),
            ('medium', 'Moyen'),
            ('high', 'Élevé'),
            ('urgent', 'Urgent'),
        ],
        default='medium'
    )
    status = models.CharField(
        max_length=20,
        choices=[
            ('scheduled', 'Programmée'),
            ('in_progress', 'En cours'),
            ('completed', 'Terminée'),
            ('cancelled', 'Annulée'),
            ('no_show', 'Absent'),
        ],
        default='scheduled'
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'crm_client_interaction'
        verbose_name = 'Interaction Client'
        verbose_name_plural = 'Interactions Clients'
        ordering = ['-scheduled_date', '-created_at']
    
    def __str__(self):
        return f"{self.client.get_full_name()} - {self.get_interaction_type_display()}"
    
    def complete_interaction(self, outcome, notes=''):
        """Mark interaction as completed with outcome."""
        self.status = 'completed'
        self.completed_date = timezone.now()
        self.outcome = outcome
        if notes:
            self.content += f"\n\n[Suivi] {notes}"
        self.save()
    
    def schedule_follow_up(self, follow_up_date, notes=''):
        """Schedule a follow-up interaction."""
        self.requires_follow_up = True
        self.follow_up_date = follow_up_date
        if notes:
            self.content += f"\n\n[Suivi programmé] {notes}"
        self.save()


class Lead(models.Model):
    """
    Lead management system for new potential clients.
    """
    LEAD_SOURCES = [
        ('website', 'Site web'),
        ('referral', 'Référence'),
        ('social_media', 'Réseaux sociaux'),
        ('advertisement', 'Publicité'),
        ('walk_in', 'Visite directe'),
        ('phone_call', 'Appel téléphonique'),
        ('email', 'Email'),
        ('open_house', 'Journée portes ouvertes'),
        ('partner', 'Partenaire'),
        ('other', 'Autre'),
    ]
    
    LEAD_STATUS = [
        ('new', 'Nouveau'),
        ('contacted', 'Contacté'),
        ('qualified', 'Qualifié'),
        ('proposal_sent', 'Proposition envoyée'),
        ('negotiation', 'En négociation'),
        ('won', 'Converti'),
        ('lost', 'Perdu'),
        ('archived', 'Archivé'),
    ]
    
    LEAD_QUALIFICATION = [
        ('hot', 'Brûlant'),
        ('warm', 'Tiède'),
        ('cold', 'Froid'),
        ('unqualified', 'Non qualifié'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # Lead Information
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    email = models.EmailField()
    phone = models.CharField(max_length=20, blank=True)
    company = models.CharField(max_length=200, blank=True)
    
    # Lead Details
    source = models.CharField(max_length=20, choices=LEAD_SOURCES)
    status = models.CharField(max_length=20, choices=LEAD_STATUS, default='new')
    qualification = models.CharField(max_length=20, choices=LEAD_QUALIFICATION, default='cold')
    
    # Property Interest
    property_type_interest = models.CharField(max_length=50, blank=True)
    budget_range = models.CharField(max_length=100, blank=True)
    location_interest = models.CharField(max_length=200, blank=True)
    timeframe = models.CharField(max_length=50, blank=True, help_text="Délai souhaité pour l'achat/location")
    
    # Assignment
    assigned_agent = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, 
                                     related_name='assigned_leads')
    agency = models.ForeignKey(Agency, on_delete=models.CASCADE, related_name='leads')
    
    # Assessment
    score = models.IntegerField(default=0, validators=[MinValueValidator(0), MaxValueValidator(100)])
    notes = models.TextField(blank=True)
    next_action = models.CharField(max_length=200, blank=True)
    next_action_date = models.DateTimeField(null=True, blank=True)
    
    # Conversion tracking
    converted_to_client = models.BooleanField(default=False)
    conversion_date = models.DateTimeField(null=True, blank=True)
    lost_reason = models.CharField(max_length=200, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'crm_lead'
        verbose_name = 'Lead'
        verbose_name_plural = 'Leads'
        ordering = ['-score', '-created_at']
    
    def __str__(self):
        return f"{self.first_name} {self.last_name} ({self.get_status_display()})"
    
    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"
    
    def calculate_score(self):
        """Calculate lead score based on various factors."""
        score = 0
        
        # Source score
        source_scores = {
            'referral': 20, 'website': 15, 'social_media': 10,
            'advertisement': 8, 'walk_in': 12, 'phone_call': 10,
            'email': 5, 'open_house': 15, 'partner': 12, 'other': 5
        }
        score += source_scores.get(self.source, 0)
        
        # Contact information completeness
        if self.email:
            score += 5
        if self.phone:
            score += 10
        
        # Property interest detail
        if self.property_type_interest:
            score += 10
        if self.budget_range:
            score += 15
        if self.location_interest:
            score += 10
        if self.timeframe:
            score += 10
        
        # Time-based scoring (newer leads get higher scores)
        days_old = (timezone.now() - self.created_at).days
        if days_old == 0:
            score += 20
        elif days_old <= 7:
            score += 15
        elif days_old <= 30:
            score += 10
        elif days_old <= 90:
            score += 5
        
        self.score = min(score, 100)
        return self.score
    
    def convert_to_client(self, user_data=None):
        """Convert lead to client user account."""
        if self.converted_to_client:
            return None
        
        # Create user account for the lead
        username = self.email.split('@')[0]
        # Ensure unique username
        counter = 1
        original_username = username
        while User.objects.filter(username=username).exists():
            username = f"{original_username}_{counter}"
            counter += 1
        
        client_user = User.objects.create_user(
            username=username,
            email=self.email,
            first_name=self.first_name,
            last_name=self.last_name,
            phone=self.phone,
            role='client',
            agency=self.agency
        )
        
        # Create client profile
        ClientProfile.objects.create(
            user=client_user,
            status='client',
            priority_level='high'
        )
        
        # Update lead status
        self.converted_to_client = True
        self.conversion_date = timezone.now()
        self.status = 'won'
        self.save()
        
        return client_user
    
    def assign_to_agent(self, agent):
        """Assign lead to an agent."""
        if agent.role != 'agent':
            raise ValidationError("Seuls les agents peuvent se voir attribuer des leads.")
        
        self.assigned_agent = agent
        if self.status == 'new':
            self.status = 'contacted'
        self.save()
        
        from apps.core.activity import log_activity

        log_activity(
            user=agent,
            component='clients',
            action='LEAD_ASSIGNED',
            message=f'Lead assigné à {agent}',
            metadata={
                'object_type': 'Lead',
                'object_id': str(self.id),
                'assigned_to': str(agent.id),
            },
        )
    
    def __str__(self):
        return f"Lead: {self.client.get_full_name() if self.client else self.email}"


class ClientNote(models.Model):
    """
    Private notes about clients (for agents only).
    Added in Phase 1 - Post-deployment.
    """
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    client_profile = models.ForeignKey(
        ClientProfile,
        on_delete=models.CASCADE,
        related_name='notes'
    )
    author = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='client_notes_written',
        help_text='Agent qui a écrit la note'
    )
    
    # Note Content
    title = models.CharField(max_length=200, blank=True)
    content = models.TextField()
    
    # Note Type
    note_type = models.CharField(
        max_length=20,
        choices=[
            ('general', 'Général'),
            ('meeting', 'Compte-rendu réunion'),
            ('call', 'Appel téléphonique'),
            ('follow_up', 'Suivi'),
            ('alert', 'Alerte'),
            ('opportunity', 'Opportunité'),
        ],
        default='general'
    )
    
    # Priority
    is_important = models.BooleanField(default=False)
    is_pinned = models.BooleanField(default=False)
    
    # Reminder
    reminder_date = models.DateTimeField(null=True, blank=True)
    reminder_sent = models.BooleanField(default=False)
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-is_pinned', '-is_important', '-created_at']
        indexes = [
            models.Index(fields=['client_profile', '-created_at']),
            models.Index(fields=['author', '-created_at']),
        ]
    
    def __str__(self):
        return f"Note sur {self.client_profile.user.get_full_name()} par {self.author.get_full_name()}"