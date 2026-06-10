"""
Serializers for reservations management API.
"""

from decimal import Decimal
from rest_framework import serializers
from django.utils import timezone
from django.core.exceptions import ValidationError
from apps.auth.models import User
from apps.properties.models import Property
from apps.crm.models import ClientProfile
from .models import Reservation, Payment, ReservationActivity, Contract, ContractTemplate


class PropertySummarySerializer(serializers.ModelSerializer):
    """Summary serializer for property in reservations."""
    
    class Meta:
        model = Property
        fields = [
            'id', 'title', 'property_type', 'status', 'price',
            'address_line1', 'city', 'postal_code', 'surface_area',
            'bedrooms', 'bathrooms'
        ]


class ClientSummarySerializer(serializers.ModelSerializer):
    """Summary serializer for client in reservations."""
    
    class Meta:
        model = ClientProfile
        fields = [
            'id', 'user', 'preferred_contact_method',
            'preferred_contact_time', 'max_budget', 'min_budget'
        ]
    
    def to_representation(self, instance):
        """Custom representation with user details."""
        data = super().to_representation(instance)
        if instance.user:
            data['user'] = {
                'id': instance.user.id,
                'username': instance.user.username,
                'first_name': instance.user.first_name,
                'last_name': instance.user.last_name,
                'email': instance.user.email,
                'phone': getattr(instance.user, 'phone', None)
            }
        return data


class PaymentSerializer(serializers.ModelSerializer):
    """Serializer for payment information."""
    
    class Meta:
        model = Payment
        fields = [
            'id', 'amount', 'currency', 'status', 'payment_method',
            'card_brand', 'card_last_four', 'description',
            'created_at', 'updated_at', 'processing_started_at',
            'completed_at', 'failed_at', 'refunded_amount',
            'refunded_at', 'error_message'
        ]
        read_only_fields = [
            'id', 'created_at', 'updated_at', 'processing_started_at',
            'completed_at', 'failed_at', 'refunded_at', 'refunded_amount'
        ]


class ReservationActivitySerializer(serializers.ModelSerializer):
    """Serializer for reservation activity log."""
    
    performed_by_name = serializers.CharField(
        source='performed_by.get_full_name',
        read_only=True
    )
    ip_address = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    
    class Meta:
        model = ReservationActivity
        fields = [
            'id', 'activity_type', 'description', 'old_value', 'new_value',
            'performed_by', 'performed_by_name', 'ip_address', 'user_agent', 'created_at'
        ]
        read_only_fields = ['id', 'created_at']


class ContractSummarySerializer(serializers.ModelSerializer):
    """Minimal contract info for nesting in reservation."""
    class Meta:
        model = Contract
        fields = ['id', 'status', 'contract_type', 'document', 'sent_at', 'signed_at', 'verification_code', 'viewed_at']


class ReservationSerializer(serializers.ModelSerializer):
    """Serializer for reservation management."""
    
    # Nested serializers
    property = PropertySummarySerializer(read_only=True)
    property_id = serializers.UUIDField(write_only=True)
    client_profile = ClientSummarySerializer(read_only=True)
    client_profile_id = serializers.UUIDField(write_only=True, required=False, allow_null=True)
    assigned_agent_name = serializers.CharField(
        source='assigned_agent.get_full_name',
        read_only=True
    )
    created_by_name = serializers.CharField(
        source='created_by.get_full_name',
        read_only=True
    )
    
    # Computed fields
    client_name_display = serializers.CharField(source='get_client_name', read_only=True)
    total_participants = serializers.IntegerField(source='get_total_participants', read_only=True)
    outstanding_amount = serializers.DecimalField(
        max_digits=12, decimal_places=2,
        source='get_outstanding_amount',
        read_only=True
    )
    
    # Status information
    is_expired = serializers.BooleanField(read_only=True)
    is_stay_ended = serializers.BooleanField(read_only=True)
    can_be_cancelled = serializers.SerializerMethodField()
    can_be_confirmed = serializers.SerializerMethodField()
    
    primary_image_url = serializers.SerializerMethodField()
    
    # Payment information
    payments = PaymentSerializer(many=True, read_only=True)
    contract = serializers.SerializerMethodField()
    payment_status_display = serializers.CharField(
        source='get_payment_status_display',
        read_only=True
    )
    
    class Meta:
        model = Reservation
        fields = [
            # Basic Information
            'id', 'reservation_type', 'status', 'amount', 'currency', 'primary_image_url',
            
            # Property and Client
            'property', 'property_id', 'client_profile', 'client_profile_id',
            'client_name', 'client_email', 'client_phone', 'client_company',
            
            # Dates and Duration
            'scheduled_date', 'scheduled_end_date', 'duration_minutes',
            
            # Purchase Information
            'purchase_price', 'reservation_deposit',
            
            # Participants
            'additional_participants', 'participant_names',
            
            # Special Requirements
            'special_requirements', 'language_preference',
            'preferred_contact_method', 'allow_sms_notifications', 'allow_email_notifications',
            
            # Notes
            'client_notes', 'internal_notes', 'cancellation_reason', 'completion_notes',
            
            # Agent Assignment
            'assigned_agent', 'assigned_agent_name',
            
            # Payment
            'payment_required', 'payment_status', 'payment_status_display',
            
            # Status Transitions
            'confirmed_at', 'cancelled_at', 'completed_at', 'expires_at',
            
            # Follow-up
            'follow_up_required', 'follow_up_date', 'follow_up_completed',
            
            # Computed fields
            'client_name_display', 'total_participants', 'outstanding_amount',
            'is_expired', 'is_stay_ended', 'can_be_cancelled', 'can_be_confirmed',
            
            # Related data
            'payments', 'contract',
            
            # Metadata
            'created_at', 'updated_at', 'created_by', 'created_by_name',
        ]
        read_only_fields = [
            'id', 'status', 'confirmed_at', 'cancelled_at', 'completed_at',
            'created_at', 'updated_at', 'payment_status'
        ]
    
    def get_primary_image_url(self, obj):
        """Get the primary image URL."""
        primary_image = obj.property.images.filter(is_primary=True).first()
        if primary_image:
            return primary_image.image.url
        first_image = obj.property.images.first()
        return first_image.image.url if first_image else None

    def get_contract(self, obj):
        """Return contract summary if the reservation has a contract."""
        try:
            c = obj.contract
            return ContractSummarySerializer(c).data
        except Contract.DoesNotExist:
            return None

    def get_can_be_cancelled(self, obj):
        """Check if reservation can be cancelled."""
        request = self.context.get('request')
        if request and request.user:
            return obj.can_be_cancelled_by(request.user)
        return False
    
    def get_can_be_confirmed(self, obj):
        """Check if reservation can be confirmed."""
        request = self.context.get('request')
        if request and request.user:
            return obj.can_be_confirmed_by(request.user)
        return False
    
    def validate_scheduled_date(self, value):
        """Validate scheduled date."""
        if value and value < timezone.now():
            raise serializers.ValidationError("La date de réservation ne peut pas être dans le passé.")
        return value
    
    def validate_reservation_deposit(self, value):
        """Validate reservation deposit amount."""
        if value and value < 0:
            raise serializers.ValidationError("Le montant de réservation doit être positif.")
        return value
    
    def validate_client_email(self, value):
        """Validate client email if provided."""
        if value and not self.instance and not self.initial_data.get('client_profile_id'):
            # Check if email already exists for another reservation
            existing = Reservation.objects.filter(
                client_email=value,
                status__in=['pending', 'confirmed']
            ).exclude(pk=getattr(self.instance, 'pk', None))
            if existing.exists():
                raise serializers.ValidationError("Cette adresse email a déjà une réservation en attente ou confirmée.")
        return value
    
    def validate(self, data):
        """Cross-field validation."""
        # Validate scheduled dates
        if data.get('scheduled_date') and data.get('scheduled_end_date'):
            if data['scheduled_end_date'] <= data['scheduled_date']:
                raise serializers.ValidationError({
                    'scheduled_end_date': "La date de fin doit être postérieure à la date de début."
                })
        
        # Validate deposit vs amount
        if data.get('reservation_deposit') and data.get('amount'):
            if data['reservation_deposit'] > data['amount']:
                raise serializers.ValidationError({
                    'reservation_deposit': "Le montant de réservation ne peut pas dépasser le montant total."
                })
        
        # Validate property is available
        if data.get('property_id'):
            try:
                property_obj = Property.objects.get(id=data['property_id'])
                if property_obj.status not in ['available', 'under_offer']:
                    raise serializers.ValidationError({
                        'property_id': f"Le bien n'est pas disponible (statut: {property_obj.get_status_display()})."
                    })
            except Property.DoesNotExist:
                raise serializers.ValidationError({
                    'property_id': "Le bien spécifié n'existe pas."
                })
        
        # Set default values
        request = self.context.get('request')
        if request and request.user:
            # assigned_agent: only default to current user if they are agent/manager/admin (creating on behalf of client).
            # Otherwise leave None so post_save signal can assign property.agent for client-created reservations.
            if not data.get('assigned_agent') and getattr(request.user, 'role', None) in ('agent', 'manager', 'admin'):
                data['assigned_agent'] = request.user
            if not data.get('created_by'):
                data['created_by'] = request.user

        # Agent crée pour un client sans compte : infos contact requises
        if request and getattr(request.user, 'role', None) in ('agent', 'manager', 'admin'):
            if not data.get('client_profile_id'):
                name = (data.get('client_name') or '').strip()
                email = (data.get('client_email') or '').strip()
                phone = (data.get('client_phone') or '').strip()
                if not name:
                    raise serializers.ValidationError({
                        'client_name': "Indiquez le nom du client.",
                    })
                if not email and not phone:
                    raise serializers.ValidationError({
                        'client_email': "Indiquez au moins un email ou un numéro de téléphone.",
                    })
        
        return data


class ReservationCreateSerializer(ReservationSerializer):
    """Serializer for creating new reservations."""
    
    class Meta(ReservationSerializer.Meta):
        read_only_fields = ReservationSerializer.Meta.read_only_fields + [
            'confirmed_at', 'cancelled_at', 'completed_at', 'payment_status'
        ]

    def create(self, validated_data):
        """
        Si un utilisateur "client" crée une réservation, on crée/attache automatiquement
        un ClientProfile CRM à ce compte et on le lie à la réservation.
        """
        request = self.context.get('request')
        user = getattr(request, 'user', None) if request else None

        if user and getattr(user, 'role', None) == 'client' and not validated_data.get('client_profile'):
            # Créer le profil CRM si besoin
            from apps.crm.models import ClientProfile
            client_profile, _ = ClientProfile.objects.get_or_create(
                user=user,
                defaults={
                    'preferred_contact_method': getattr(user, 'preferred_contact_method', 'email') or 'email',
                    'status': 'prospect',
                },
            )
            validated_data['client_profile'] = client_profile

            # Compléter les infos "snapshot" si elles sont vides (utile si pas client_profile_id)
            validated_data.setdefault('client_name', user.get_full_name() or user.username)
            validated_data.setdefault('client_email', user.email or '')
            validated_data.setdefault('client_phone', getattr(user, 'phone', '') or '')

        # Location: facturation par nuit (base = prix du bien * nb de nuits).
        # Si le frontend n'a pas envoyé amount, on le calcule côté backend.
        if validated_data.get('reservation_type') == 'rent':
            start = validated_data.get('scheduled_date')
            end = validated_data.get('scheduled_end_date')
            property_obj = validated_data.get('property')
            if not property_obj and validated_data.get('property_id'):
                try:
                    property_obj = Property.objects.get(id=validated_data.get('property_id'))
                except Property.DoesNotExist:
                    property_obj = None

            if start and end and end > start:
                delta = end - start
                nights = max(1, delta.days)
                # Si heure de fin dépasse heure de début, compter une nuit supplémentaire.
                if delta.seconds > 0:
                    nights += 1

                validated_data['duration_minutes'] = nights * 24 * 60

                if property_obj and validated_data.get('amount') in (None, ''):
                    validated_data['amount'] = (property_obj.price or Decimal('0')) * Decimal(nights)

        return super().create(validated_data)


class ReservationUpdateSerializer(ReservationSerializer):
    """Serializer for updating reservations."""
    
    class Meta(ReservationSerializer.Meta):
        read_only_fields = ReservationSerializer.Meta.read_only_fields + [
            'id', 'property', 'property_id', 'client_profile', 'client_profile_id',
            'created_at', 'created_by'
        ]


class ReservationStatusUpdateSerializer(serializers.Serializer):
    """Serializer for status updates."""
    
    status = serializers.ChoiceField(
        choices=['confirmed', 'cancelled', 'completed', 'expired']
    )
    notes = serializers.CharField(required=False, allow_blank=True)
    
    def validate_status(self, value):
        """Validate status change."""
        reservation = self.instance
        
        # Define allowed status transitions
        allowed_transitions = {
            'pending': ['confirmed', 'cancelled'],
            'confirmed': ['completed', 'cancelled'],
            'cancelled': [],  # Cancelled reservations cannot be changed
            'completed': [],  # Completed reservations cannot be changed
            'expired': [],    # Expired reservations cannot be changed
        }
        
        current_status = reservation.status
        if value not in allowed_transitions.get(current_status, []):
            raise serializers.ValidationError(
                f"Transition de statut non autorisée de '{current_status}' vers '{value}'"
            )
        
        return value


class PaymentCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating payments."""
    
    reservation = ReservationSerializer(read_only=True)
    reservation_id = serializers.UUIDField(write_only=True)
    
    class Meta:
        model = Payment
        fields = [
            'id', 'reservation', 'reservation_id',
            'amount', 'currency', 'payment_method',
            'description', 'billing_name', 'billing_email', 'billing_phone',
            'billing_address_line1', 'billing_address_line2',
            'billing_city', 'billing_postal_code', 'billing_country'
        ]
    
    def validate_amount(self, value):
        """Validate payment amount."""
        if value <= 0:
            raise serializers.ValidationError("Le montant du paiement doit être positif.")
        return value
    
    def validate(self, data):
        """Cross-field validation."""
        # Validate reservation exists and can be paid
        try:
            reservation = Reservation.objects.get(id=data['reservation_id'])
        except Reservation.DoesNotExist:
            raise serializers.ValidationError({
                'reservation_id': "La réservation spécifiée n'existe pas."
            })
        
        # Check if reservation requires payment
        if not reservation.requires_payment():
            raise serializers.ValidationError({
                'reservation_id': "Cette réservation ne nécessite pas de paiement."
            })
        
        # Check outstanding amount
        outstanding = reservation.get_outstanding_amount()
        if data['amount'] > outstanding:
            raise serializers.ValidationError({
                'amount': f"Le montant ne peut pas dépasser le solde restant ({outstanding} {reservation.currency})."
            })
        
        data['reservation'] = reservation
        return data


class PaymentStatusUpdateSerializer(serializers.Serializer):
    """Serializer for payment status updates."""
    
    status = serializers.ChoiceField(
        choices=[
            'processing', 'completed', 'failed', 'cancelled',
            'refunded', 'partial_refund'
        ]
    )
    error_code = serializers.CharField(required=False, allow_blank=True)
    error_message = serializers.CharField(required=False, allow_blank=True)
    failure_reason = serializers.CharField(required=False, allow_blank=True)
    
    def validate(self, data):
        """Validate status update."""
        payment = self.instance
        
        # Define allowed status transitions
        allowed_transitions = {
            'pending': ['processing', 'failed', 'cancelled'],
            'processing': ['completed', 'failed'],
            'completed': ['refunded', 'partial_refund'],
            'failed': [],  # Failed payments cannot be changed
            'cancelled': [],  # Cancelled payments cannot be changed
            'refunded': [],  # Refunded payments cannot be changed
            'partial_refund': ['refunded'],  # Can complete the refund
        }
        
        current_status = payment.status
        new_status = data['status']
        
        if new_status not in allowed_transitions.get(current_status, []):
            raise serializers.ValidationError(
                f"Transition de statut non autorisée de '{current_status}' vers '{new_status}'"
            )
        
        return data


class ReservationStatsSerializer(serializers.Serializer):
    """Serializer for reservation statistics."""
    
    total_reservations = serializers.IntegerField()
    pending_reservations = serializers.IntegerField()
    confirmed_reservations = serializers.IntegerField()
    completed_reservations = serializers.IntegerField()
    cancelled_reservations = serializers.IntegerField()
    total_revenue = serializers.DecimalField(max_digits=12, decimal_places=2)
    avg_booking_value = serializers.DecimalField(max_digits=12, decimal_places=2)
    conversion_rate = serializers.FloatField()


# --- Contract ---

class ContractTemplateSerializer(serializers.ModelSerializer):
    """Serializer for contract templates (list/detail)."""
    
    class Meta:
        model = ContractTemplate
        fields = ['id', 'name', 'contract_type', 'body', 'is_active', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']


class ContractSerializer(serializers.ModelSerializer):
    """Serializer for contract list/detail."""
    
    reservation_id = serializers.UUIDField(source='reservation.id', read_only=True)
    created_by_name = serializers.CharField(source='created_by.get_full_name', read_only=True)
    signed_by_name = serializers.CharField(source='signed_by.get_full_name', read_only=True)
    can_be_edited = serializers.BooleanField(read_only=True)
    
    class Meta:
        model = Contract
        fields = [
            'id', 'reservation', 'reservation_id', 'contract_type', 'status',
            'template', 'document', 'signed_document',
            'sent_at', 'signed_at', 'signed_by', 'signed_by_name',
            'created_by', 'created_by_name', 'created_at', 'updated_at', 'notes',
            'can_be_edited', 'verification_code', 'viewed_at'
        ]
        read_only_fields = [
            'id', 'reservation', 'sent_at', 'signed_at', 'signed_by', 'created_at', 'updated_at',
            'verification_code', 'viewed_at'
        ]


class ContractCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating a contract (draft) for a reservation."""
    
    reservation_id = serializers.UUIDField(write_only=True)
    
    class Meta:
        model = Contract
        fields = [
            'id', 'reservation_id', 'contract_type', 'template', 'notes'
        ]
        read_only_fields = ['id']
    
    def validate_reservation_id(self, value):
        try:
            res = Reservation.objects.get(id=value)
        except Reservation.DoesNotExist:
            raise serializers.ValidationError("Réservation introuvable.")
        if res.status not in ['confirmed', 'completed']:
            raise serializers.ValidationError(
                "Un contrat ne peut être créé que pour une réservation confirmée ou terminée."
            )
        if hasattr(res, 'contract') and res.contract:
            raise serializers.ValidationError("Cette réservation a déjà un contrat.")
        return value
    
    def create(self, validated_data):
        reservation_id = validated_data.pop('reservation_id')
        reservation = Reservation.objects.get(id=reservation_id)
        validated_data['reservation'] = reservation
        validated_data['created_by'] = self.context['request'].user
        return super().create(validated_data)


class ContractUpdateSerializer(serializers.ModelSerializer):
    """Serializer for updating a contract in draft status."""
    
    class Meta:
        model = Contract
        fields = ['contract_type', 'template', 'notes']
    
    def validate(self, data):
        if not self.instance.can_be_edited():
            raise serializers.ValidationError("Seul un contrat en brouillon peut être modifié.")
        return data