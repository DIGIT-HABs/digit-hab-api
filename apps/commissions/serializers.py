"""
Serializers for commission and payment management.
"""

from rest_framework import serializers
from .models import Commission, Payment
from apps.auth.models import User, Agency
from apps.properties.models import Property
from apps.reservations.models import Reservation


def _absolute_media_url(request, path):
    if not path:
        return None
    if str(path).startswith(('http://', 'https://')):
        return path
    if request:
        return request.build_absolute_uri(path)
    return path


def _property_primary_image_url(request, prop):
    if not prop:
        return None
    images = getattr(prop, '_prefetched_objects_cache', {}).get('images')
    if images is not None:
        primary = next((img for img in images if getattr(img, 'is_primary', False)), None)
        if not primary and images:
            primary = images[0]
    else:
        primary = prop.images.filter(is_primary=True).first() or prop.images.first()
    if primary and primary.image:
        return _absolute_media_url(request, primary.image.url)
    return None


class CommissionSerializer(serializers.ModelSerializer):
    """
    Serializer for commission management.
    """
    agent = serializers.StringRelatedField(read_only=True)
    agent_id = serializers.UUIDField(write_only=True)
    agency = serializers.StringRelatedField(read_only=True)
    agency_id = serializers.UUIDField(write_only=True)
    property = serializers.StringRelatedField(read_only=True)
    property_id = serializers.UUIDField(write_only=True, required=False, allow_null=True)
    property_title = serializers.SerializerMethodField()
    property_city = serializers.SerializerMethodField()
    property_image_url = serializers.SerializerMethodField()
    reservation = serializers.StringRelatedField(read_only=True)
    reservation_id = serializers.UUIDField(write_only=True, required=False, allow_null=True)
    agent_detail = serializers.SerializerMethodField()
    reservation_detail = serializers.SerializerMethodField()
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    commission_type_display = serializers.CharField(source='get_commission_type_display', read_only=True)

    def get_property_title(self, obj):
        if obj.property_id and obj.property:
            return obj.property.title
        return None

    def get_property_city(self, obj):
        if obj.property_id and obj.property:
            return obj.property.city
        return None

    def get_property_image_url(self, obj):
        return _property_primary_image_url(self.context.get('request'), obj.property)

    def get_agent_detail(self, obj):
        if not obj.agent_id or not obj.agent:
            return None
        agent = obj.agent
        return {
            'id': str(agent.id),
            'full_name': agent.get_full_name(),
            'email': agent.email,
            'phone': agent.phone or '',
        }

    def get_reservation_detail(self, obj):
        if not obj.reservation_id or not obj.reservation:
            return None
        res = obj.reservation
        return {
            'id': str(res.id),
            'reservation_type': res.reservation_type,
            'reservation_type_display': res.get_reservation_type_display(),
            'status': res.status,
            'status_display': res.get_status_display(),
            'scheduled_date': res.scheduled_date.isoformat() if res.scheduled_date else None,
            'client_name': res.get_client_name(),
            'payment_status': res.payment_status,
            'payment_status_display': res.get_payment_status_display(),
        }

    class Meta:
        model = Commission
        fields = [
            'id', 'agent', 'agent_id', 'agent_detail', 'agency', 'agency_id',
            'property', 'property_id', 'property_title', 'property_city', 'property_image_url',
            'reservation', 'reservation_id', 'reservation_detail',
            'commission_type', 'commission_type_display',
            'base_amount', 'commission_rate', 'commission_amount',
            'status', 'status_display', 'transaction_date', 'approved_date', 'paid_date',
            'notes', 'created_at', 'updated_at'
        ]
        read_only_fields = [
            'id', 'agent', 'agent_detail', 'agency',
            'property', 'property_title', 'property_city', 'property_image_url',
            'reservation', 'reservation_detail',
            'commission_amount', 'status_display', 'commission_type_display',
            'approved_date', 'paid_date',
            'created_at', 'updated_at'
        ]
    
    def create(self, validated_data):
        """Create commission and calculate amount."""
        # Récupérer les IDs depuis initial_data (write_only fields)
        agent_id = self.initial_data.get('agent_id')
        agency_id = self.initial_data.get('agency_id')
        property_id = self.initial_data.get('property_id')
        reservation_id = self.initial_data.get('reservation_id')
        
        if not agent_id:
            raise serializers.ValidationError({"agent_id": "Ce champ est requis."})
        if not agency_id:
            raise serializers.ValidationError({"agency_id": "Ce champ est requis."})
        
        try:
            agent = User.objects.get(id=agent_id, role='agent')
        except User.DoesNotExist:
            raise serializers.ValidationError({"agent_id": "Agent introuvable."})
        
        try:
            agency = Agency.objects.get(id=agency_id)
        except Agency.DoesNotExist:
            raise serializers.ValidationError({"agency_id": "Agence introuvable."})
        
        # Récupérer property et reservation si fournis
        property_obj = None
        if property_id:
            try:
                property_obj = Property.objects.get(id=property_id)
            except Property.DoesNotExist:
                raise serializers.ValidationError({"property_id": "Propriété introuvable."})
        
        reservation_obj = None
        if reservation_id:
            try:
                reservation_obj = Reservation.objects.get(id=reservation_id)
            except Reservation.DoesNotExist:
                raise serializers.ValidationError({"reservation_id": "Réservation introuvable."})
        
        commission = Commission.objects.create(
            agent=agent,
            agency=agency,
            property=property_obj,
            reservation=reservation_obj,
            **validated_data
        )
        
        return commission
    
    def validate(self, data):
        """Validate commission data."""
        if data.get('base_amount') and data.get('base_amount') <= 0:
            raise serializers.ValidationError("Le montant de base doit être supérieur à 0.")
        
        if data.get('commission_rate') and (data.get('commission_rate') < 0 or data.get('commission_rate') > 100):
            raise serializers.ValidationError("Le taux de commission doit être entre 0 et 100%.")
        
        return data


class PaymentSerializer(serializers.ModelSerializer):
    """
    Serializer for payment management.
    """
    agent = serializers.StringRelatedField(read_only=True)
    agent_id = serializers.UUIDField(write_only=True)
    agency = serializers.StringRelatedField(read_only=True)
    agency_id = serializers.UUIDField(write_only=True)
    commissions = serializers.StringRelatedField(many=True, read_only=True)
    commission_ids = serializers.ListField(
        child=serializers.UUIDField(),
        write_only=True,
        required=False
    )
    
    class Meta:
        model = Payment
        fields = [
            'id', 'agent', 'agent_id', 'agency', 'agency_id',
            'commissions', 'commission_ids',
            'amount', 'payment_method', 'payment_reference',
            'status', 'payment_date', 'processed_date',
            'notes', 'created_at', 'updated_at'
        ]
        read_only_fields = [
            'id', 'agent', 'agency', 'commissions',
            'processed_date', 'created_at', 'updated_at'
        ]
    
    def create(self, validated_data):
        """Create payment and link commissions."""
        # Récupérer les IDs depuis initial_data (write_only fields)
        agent_id = self.initial_data.get('agent_id')
        agency_id = self.initial_data.get('agency_id')
        commission_ids = self.initial_data.get('commission_ids', [])
        
        if not agent_id:
            raise serializers.ValidationError({"agent_id": "Ce champ est requis."})
        if not agency_id:
            raise serializers.ValidationError({"agency_id": "Ce champ est requis."})
        
        try:
            agent = User.objects.get(id=agent_id, role='agent')
        except User.DoesNotExist:
            raise serializers.ValidationError({"agent_id": "Agent introuvable."})
        
        try:
            agency = Agency.objects.get(id=agency_id)
        except Agency.DoesNotExist:
            raise serializers.ValidationError({"agency_id": "Agence introuvable."})
        
        payment = Payment.objects.create(
            agent=agent,
            agency=agency,
            **validated_data
        )
        
        # Link commissions
        if commission_ids:
            try:
                commissions = Commission.objects.filter(id__in=commission_ids, agent=agent, status='approved')
                payment.commissions.set(commissions)
            except Exception as e:
                raise serializers.ValidationError({"commission_ids": f"Erreur lors de la liaison des commissions: {str(e)}"})
        
        return payment
    
    def validate(self, data):
        """Validate payment data."""
        if data.get('amount') and data.get('amount') <= 0:
            raise serializers.ValidationError("Le montant doit être supérieur à 0.")
        
        return data

