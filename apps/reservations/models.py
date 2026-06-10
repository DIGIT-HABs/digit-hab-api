"""
Models for reservations management with payment integration.
"""
# Keep reference to builtin (Reservation.property is a ForeignKey and would shadow it)
_property = property

import uuid
from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from django.core.exceptions import ValidationError
from django.utils import timezone
from apps.auth.models import User, Agency
from apps.properties.models import Property
from apps.crm.models import ClientProfile


class Reservation(models.Model):
    """
    Reservation model for property bookings and purchases.
    """
    
    # Basic Information
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # Property and Client
    property = models.ForeignKey(
        Property, 
        on_delete=models.CASCADE, 
        related_name='reservations'
    )
    client_profile = models.ForeignKey(
        ClientProfile,
        on_delete=models.CASCADE,
        related_name='reservations',
        null=True,
        blank=True
    )
    
    # Reservation Type and Status
    reservation_type = models.CharField(
        max_length=20,
        choices=[
            ('visit', 'Visite'),
            ('viewing', 'Visite avec achat'),
            ('purchase', 'Achat direct'),
            ('rent', 'Location'),
            ('evaluation', 'Évaluation'),
        ],
        default='viewing'
    )
    
    status = models.CharField(
        max_length=20,
        choices=[
            ('pending', 'En attente'),
            ('confirmed', 'Confirmée'),
            ('cancelled', 'Annulée'),
            ('completed', 'Terminée'),
            ('expired', 'Expirée'),
        ],
        default='pending'
    )
    
    # Pricing
    amount = models.DecimalField(
        max_digits=12, decimal_places=2,
        validators=[MinValueValidator(0)],
        null=True,
        blank=True
    )
    currency = models.CharField(
        max_length=3,
        default='XOF',
        choices=[
            ('XOF', 'Franc CFA (XOF)'),
            ('EUR', 'Euro (EUR)'),
            ('USD', 'Dollar US (USD)'),            
        ]
    )
    
    # Dates
    scheduled_date = models.DateTimeField(null=True, blank=True)
    scheduled_end_date = models.DateTimeField(null=True, blank=True)
    
    # For visits and viewings
    duration_minutes = models.PositiveIntegerField(default=60)
    
    # For purchases
    purchase_price = models.DecimalField(
        max_digits=12, decimal_places=2,
        validators=[MinValueValidator(0)],
        null=True,
        blank=True
    )
    reservation_deposit = models.DecimalField(
        max_digits=12, decimal_places=2,
        validators=[MinValueValidator(0)],
        null=True,
        blank=True,
        help_text="Montant de la réservation ou acompte"
    )
    
    # Client Information (if no client_profile)
    client_name = models.CharField(max_length=200, blank=True)
    client_email = models.EmailField(blank=True)
    client_phone = models.CharField(max_length=20, blank=True)
    client_company = models.CharField(max_length=200, blank=True)
    
    # Additional Participants
    additional_participants = models.PositiveIntegerField(default=0)
    participant_names = models.TextField(blank=True, help_text="Noms des participants supplémentaires")
    
    # Special Requirements
    special_requirements = models.TextField(
        blank=True,
        help_text="Besoins spéciaux, accessibilité, etc."
    )
    language_preference = models.CharField(
        max_length=10,
        choices=[
            ('fr', 'Français'),
            ('en', 'Anglais'),
            ('es', 'Espagnol'),
            ('de', 'Allemand'),
            ('it', 'Italien'),
            ('other', 'Autre'),
        ],
        default='fr'
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
    allow_sms_notifications = models.BooleanField(default=True)
    allow_email_notifications = models.BooleanField(default=True)
    
    # Notes and Comments
    client_notes = models.TextField(
        blank=True,
        help_text="Notes du client sur la réservation"
    )
    internal_notes = models.TextField(
        blank=True,
        help_text="Notes internes (non visibles par le client)"
    )
    cancellation_reason = models.TextField(blank=True)
    completion_notes = models.TextField(blank=True)
    
    # Agent Assignment
    assigned_agent = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        related_name='assigned_reservations',
        null=True,
        blank=True
    )
    
    # Payment Information
    payment_required = models.BooleanField(
        default=False,
        help_text="Cette réservation nécessite un paiement"
    )
    payment_status = models.CharField(
        max_length=20,
        choices=[
            ('pending', 'Paiement en attente'),
            ('processing', 'Paiement en cours'),
            ('paid', 'Payé'),
            ('failed', 'Échec du paiement'),
            ('refunded', 'Remboursé'),
        ],
        default='pending'
    )
    
    # Status Transitions
    confirmed_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    
    # Follow-up
    follow_up_required = models.BooleanField(default=False)
    follow_up_date = models.DateTimeField(null=True, blank=True)
    follow_up_completed = models.BooleanField(default=False)
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_reservations'
    )
    
    class Meta:
        db_table = 'reservations'
        verbose_name = 'Réservation'
        verbose_name_plural = 'Réservations'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['property', 'status']),
            models.Index(fields=['client_profile']),
            models.Index(fields=['assigned_agent']),
            models.Index(fields=['scheduled_date']),
            models.Index(fields=['status', 'scheduled_date']),
            models.Index(fields=['payment_status']),
        ]
    
    def __str__(self):
        return f"{self.property.title} - {self.get_client_name()} - {self.get_status_display()}"
    
    def get_client_name(self):
        """Get client name from profile or direct field."""
        if self.client_profile and self.client_profile.user:
            return self.client_profile.user.get_full_name() or self.client_profile.user.username
        return self.client_name or "Client anonyme"
    
    def get_client_email(self):
        """Get client email from profile or direct field."""
        if self.client_profile and self.client_profile.user:
            return self.client_profile.user.email
        return self.client_email
    
    def get_client_phone(self):
        """Get client phone from profile or direct field."""
        if self.client_profile:
            return getattr(self.client_profile.user, 'phone', None) or self.client_phone
        return self.client_phone
    
    def can_be_cancelled_by(self, user):
        """Check if reservation can be cancelled by user."""
        if user.is_staff or user.is_superuser:
            return True
        if self.assigned_agent == user:
            return True
        if self.client_profile and self.client_profile.user == user:
            return True
        return False
    
    def can_be_confirmed_by(self, user):
        """Check if reservation can be confirmed by user."""
        # Staff and superusers can always confirm
        if user.is_staff or user.is_superuser:
            return True
        
        # Assigned agent can confirm
        if self.assigned_agent == user:
            return True
        
        # Client can confirm their own reservation if it's pending
        if self.status == 'pending':
            if self.client_profile and self.client_profile.user == user:
                return True
            # Also check by email for reservations without client_profile
            if not self.client_profile and self.client_email == user.email:
                return True
        
        return False
    
    def is_expired(self):
        """Check if reservation is expired."""
        if self.expires_at and timezone.now() > self.expires_at:
            return True
        if self.status == 'pending' and self.scheduled_date:
            # Auto-expire pending reservations 24h after scheduled date
            return timezone.now() > self.scheduled_date + timezone.timedelta(hours=24)
        return False
    
    @_property
    def is_stay_ended(self):
        """
        Pour une location (rent) : True si le séjour est terminé (date de fin dépassée).
        Permet d'afficher "Séjour terminé" et de proposer de marquer la résa en "terminée".
        """
        if self.reservation_type != 'rent' or self.status != 'confirmed':
            return False
        if not self.scheduled_end_date:
            return False
        return timezone.now() > self.scheduled_end_date
    
    def get_total_participants(self):
        """Get total number of participants."""
        return 1 + self.additional_participants
    
    def get_actual_duration(self):
        """Get actual duration in minutes."""
        if self.completed_at and self.confirmed_at:
            return int((self.completed_at - self.confirmed_at).total_seconds() / 60)
        return self.duration_minutes
    
    def confirm(self, user=None):
        """Confirm the reservation."""
        self.status = 'confirmed'
        self.confirmed_at = timezone.now()
        if user:
            self.assigned_agent = user
        self.save()
    
    def cancel(self, reason='', user=None):
        """Cancel the reservation."""
        self.status = 'cancelled'
        self.cancelled_at = timezone.now()
        self.cancellation_reason = reason
        self.save()
    
    def complete(self, notes=''):
        """Mark reservation as completed."""
        self.status = 'completed'
        self.completed_at = timezone.now()
        self.completion_notes = notes
        self.save()
    
    def requires_payment(self):
        """Check if reservation requires payment."""
        return self.payment_required or self.reservation_deposit
    
    def get_outstanding_amount(self):
        """Get outstanding amount to be paid."""
        if not self.requires_payment():
            return 0
        return self.amount or self.reservation_deposit or 0


class Payment(models.Model):
    """
    Payment model for reservations with Stripe integration.
    """
    
    # Basic Information
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    reservation = models.ForeignKey(
        Reservation,
        on_delete=models.CASCADE,
        related_name='payments'
    )
    
    # Stripe Integration
    stripe_payment_intent_id = models.CharField(
        max_length=100,
        unique=True,
        null=True,
        blank=True
    )
    stripe_charge_id = models.CharField(
        max_length=100,
        null=True,
        blank=True
    )
    stripe_customer_id = models.CharField(
        max_length=100,
        null=True,
        blank=True
    )
    
    # Payment Amount and Currency
    amount = models.DecimalField(
        max_digits=12, decimal_places=2,
        validators=[MinValueValidator(0.01)]
    )
    currency = models.CharField(
        max_length=3,
        default='EUR',
        choices=[
            ('EUR', 'Euro (EUR)'),
            ('USD', 'Dollar US (USD)'),
            ('GBP', 'Livre Sterling (GBP)'),
            ('CHF', 'Franc Suisse (CHF)'),
            ('XOF', 'Franc CFA (XOF)'),
        ]
    )
    
    # Payment Status
    status = models.CharField(
        max_length=20,
        choices=[
            ('pending', 'En attente'),
            ('processing', 'En cours'),
            ('completed', 'Terminé'),
            ('failed', 'Échoué'),
            ('cancelled', 'Annulé'),
            ('refunded', 'Remboursé'),
            ('partial_refund', 'Remboursement partiel'),
        ],
        default='pending'
    )
    
    # Payment Method
    payment_method = models.CharField(
        max_length=20,
        choices=[
            ('card', 'Carte bancaire'),
            ('bank_transfer', 'Virement bancaire'),
            ('paypal', 'PayPal'),
            ('apple_pay', 'Apple Pay'),
            ('google_pay', 'Google Pay'),
            ('cash', 'Espèces'),
            ('check', 'Chèque'),
        ],
        default='card'
    )
    
    # Card Details (for card payments)
    card_brand = models.CharField(
        max_length=20,
        blank=True,
        help_text="Visa, Mastercard, etc."
    )
    card_last_four = models.CharField(
        max_length=4,
        blank=True,
        help_text="4 derniers chiffres de la carte"
    )
    card_exp_month = models.PositiveIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(12)]
    )
    card_exp_year = models.PositiveIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(2020), MaxValueValidator(2050)]
    )
    
    # Billing Address
    billing_name = models.CharField(max_length=200, blank=True)
    billing_email = models.EmailField(blank=True)
    billing_phone = models.CharField(max_length=20, blank=True)
    billing_address_line1 = models.CharField(max_length=200, blank=True)
    billing_address_line2 = models.CharField(max_length=200, blank=True)
    billing_city = models.CharField(max_length=100, blank=True)
    billing_postal_code = models.CharField(max_length=20, blank=True)
    billing_country = models.CharField(max_length=100, blank=True)
    
    # Payment Description
    description = models.TextField(
        blank=True,
        help_text="Description du paiement"
    )
    
    # Status Transitions
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    # Processing Information
    processing_started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    failed_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    
    # Error Information
    error_code = models.CharField(max_length=50, blank=True)
    error_message = models.TextField(blank=True)
    failure_reason = models.TextField(blank=True)
    
    # Refund Information
    refunded_amount = models.DecimalField(
        max_digits=12, decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)]
    )
    refund_reason = models.TextField(blank=True)
    refunded_at = models.DateTimeField(null=True, blank=True)
    
    # Metadata
    metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text="Métadonnées additionnelles (Stripe, système, etc.)"
    )
    
    class Meta:
        db_table = 'payments'
        verbose_name = 'Paiement'
        verbose_name_plural = 'Paiements'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['reservation']),
            models.Index(fields=['stripe_payment_intent_id']),
            models.Index(fields=['status']),
            models.Index(fields=['created_at']),
        ]
    
    def __str__(self):
        return f"Paiement {self.amount} {self.currency} - {self.get_status_display()}"
    
    def get_refundable_amount(self):
        """Get amount that can be refunded."""
        if self.status != 'completed':
            return 0
        return self.amount - self.refunded_amount
    
    def can_be_refunded(self):
        """Check if payment can be refunded."""
        return self.status == 'completed' and self.get_refundable_amount() > 0
    
    def mark_as_processing(self):
        """Mark payment as processing."""
        self.status = 'processing'
        self.processing_started_at = timezone.now()
        self.save()
    
    def mark_as_completed(self, charge_id=None):
        """Mark payment as completed."""
        self.status = 'completed'
        self.completed_at = timezone.now()
        if charge_id:
            self.stripe_charge_id = charge_id
        self.save()
        
        # Update reservation payment status
        self.reservation.payment_status = 'paid'
        self.reservation.save()
    
    def mark_as_failed(self, error_code='', error_message=''):
        """Mark payment as failed."""
        self.status = 'failed'
        self.failed_at = timezone.now()
        self.error_code = error_code
        self.error_message = error_message
        self.save()
        
        # Update reservation payment status
        self.reservation.payment_status = 'failed'
        self.reservation.save()
    
    def refund(self, amount, reason=''):
        """Process a refund."""
        if not self.can_be_refunded() or amount > self.get_refundable_amount():
            return False
        
        self.refunded_amount += amount
        self.refund_reason = reason
        self.refunded_at = timezone.now()
        
        if self.refunded_amount >= self.amount:
            self.status = 'refunded'
        else:
            self.status = 'partial_refund'
        
        self.save()
        return True


class ReservationActivity(models.Model):
    """
    Activity log for reservation events and state changes.
    """
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    reservation = models.ForeignKey(
        Reservation,
        on_delete=models.CASCADE,
        related_name='activities'
    )
    
    # Activity Details
    activity_type = models.CharField(
        max_length=30,
        choices=[
            ('created', 'Créé'),
            ('updated', 'Modifié'),
            ('status_changed', 'Statut modifié'),
            ('confirmed', 'Confirmé'),
            ('cancelled', 'Annulé'),
            ('completed', 'Terminé'),
            ('payment_created', 'Paiement créé'),
            ('payment_completed', 'Paiement complété'),
            ('payment_failed', 'Paiement échoué'),
            ('refund_created', 'Remboursement créé'),
            ('agent_assigned', 'Agent assigné'),
            ('notes_added', 'Notes ajoutées'),
            ('follow_up_scheduled', 'Suivi programmé'),
            ('contract_created', 'Contrat créé'),
            ('contract_sent', 'Contrat envoyé'),
            ('contract_signed', 'Contrat signé'),
        ]
    )
    
    description = models.TextField()
    old_value = models.TextField(blank=True)
    new_value = models.TextField(blank=True)
    
    # Actor Information
    performed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reservation_activities'
    )
    
    # Context
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'reservation_activities'
        verbose_name = 'Activité de Réservation'
        verbose_name_plural = 'Activités de Réservation'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['reservation', 'created_at']),
            models.Index(fields=['activity_type']),
            models.Index(fields=['performed_by']),
        ]
    
    def __str__(self):
        return f"{self.reservation} - {self.get_activity_type_display()} - {self.created_at}"


class ContractTemplate(models.Model):
    """
    Template for generating contracts (sale or rent).
    Body can contain placeholders: {{client_name}}, {{property_title}}, {{amount}}, etc.
    """
    name = models.CharField(max_length=200)
    contract_type = models.CharField(
        max_length=20,
        choices=[
            ('sale', 'Vente'),
            ('rent', 'Location'),
        ],
        default='sale'
    )
    body = models.TextField(
        help_text="Contenu du contrat. Placeholders: {{client_name}}, {{property_title}}, {{amount}}, {{scheduled_date}}, etc."
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'contract_templates'
        verbose_name = 'Modèle de contrat'
        verbose_name_plural = 'Modèles de contrat'
        ordering = ['contract_type', 'name']

    def __str__(self):
        return f"{self.name} ({self.get_contract_type_display()})"


class Contract(models.Model):
    """
    Contract linked to a reservation. Flow: draft → sent → signed.
    When signed: reservation is completed and property status updated (sold/rented).
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    reservation = models.OneToOneField(
        Reservation,
        on_delete=models.CASCADE,
        related_name='contract'
    )
    contract_type = models.CharField(
        max_length=20,
        choices=[
            ('sale', 'Vente'),
            ('rent', 'Location'),
        ],
        default='sale'
    )
    status = models.CharField(
        max_length=20,
        choices=[
            ('draft', 'Brouillon'),
            ('sent', 'Envoyé au client'),
            ('signed', 'Signé'),
            ('archived', 'Archivé'),
        ],
        default='draft'
    )
    template = models.ForeignKey(
        ContractTemplate,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='contracts'
    )
    # Document: uploaded by agent or generated from template
    document = models.FileField(
        upload_to='contracts/documents/%Y/%m/',
        null=True,
        blank=True,
        max_length=500
    )
    # Signed document (uploaded after client signature)
    signed_document = models.FileField(
        upload_to='contracts/signed/%Y/%m/',
        null=True,
        blank=True,
        max_length=500
    )
    sent_at = models.DateTimeField(null=True, blank=True)
    signed_at = models.DateTimeField(null=True, blank=True)
    signed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='signed_contracts'
    )
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_contracts'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    notes = models.TextField(blank=True)
    # QR code verification: code unique pour scan + authentification
    verification_code = models.CharField(
        max_length=32,
        unique=True,
        null=True,
        blank=True,
        db_index=True,
        help_text="Code unique pour vérification du contrat (QR code)"
    )
    viewed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Date de première consultation du contrat (scan QR ou validation)"
    )

    class Meta:
        db_table = 'contracts'
        verbose_name = 'Contrat'
        verbose_name_plural = 'Contrats'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['reservation']),
            models.Index(fields=['status']),
            models.Index(fields=['contract_type']),
            models.Index(fields=['verification_code']),
        ]

    def __str__(self):
        return f"Contrat {self.reservation} - {self.get_status_display()}"

    def ensure_verification_code(self):
        """Generate a unique verification code if not set."""
        if self.verification_code:
            return
        import secrets
        self.verification_code = secrets.token_urlsafe(16)[:22]  # ~22 chars URL-safe
        self.save(update_fields=['verification_code', 'updated_at'])

    def can_be_edited(self):
        return self.status == 'draft'

    def mark_sent(self):
        self.status = 'sent'
        self.sent_at = timezone.now()
        self.save(update_fields=['status', 'sent_at', 'updated_at'])

    def mark_signed(self, user=None):
        self.status = 'signed'
        self.signed_at = timezone.now()
        self.signed_by = user
        self.save(update_fields=['status', 'signed_at', 'signed_by', 'updated_at'])