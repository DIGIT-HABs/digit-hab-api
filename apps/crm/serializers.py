"""
Serializers for CRM (Client Relationship Management).
"""

from rest_framework import serializers
from django.utils import timezone
from django.contrib.contenttypes.models import ContentType
from apps.auth.models import User, Agency
from apps.properties.models import Property
from .models import ClientProfile, PropertyInterest, ClientInteraction, Lead, ClientNote
from .matching import PropertyMatcher


# Import for PropertyListSerializer
from apps.properties.serializers import PropertyListSerializer


class ClientProfileSerializer(serializers.ModelSerializer):
    """
    Serializer for client profile information.
    """
    user = serializers.StringRelatedField(read_only=True)
    user_id = serializers.UUIDField(write_only=True)
    username = serializers.CharField(source='user.username', read_only=True)
    full_name = serializers.CharField(source='user.get_full_name', read_only=True)
    email = serializers.CharField(source='user.email', read_only=True)
    phone = serializers.CharField(source='user.phone', read_only=True, allow_blank=True)
    agency_name = serializers.SerializerMethodField()
    agency_id = serializers.SerializerMethodField()
    matching_properties = serializers.SerializerMethodField()
    conversion_score_display = serializers.CharField(source='get_conversion_score_display', read_only=True)
    
    class Meta:
        model = ClientProfile
        fields = [
            'id', 'user', 'user_id', 'username', 'full_name', 'email', 'phone',
            'agency_name', 'agency_id',
            'date_of_birth', 'nationality', 'marital_status',
            'preferred_contact_method', 'preferred_contact_time',
            'max_budget', 'min_budget', 'preferred_property_types', 'preferred_locations',
            'min_bedrooms', 'max_bedrooms', 'min_area', 'max_area',
            'preferred_cities', 'max_distance_from_center',
            'financing_status', 'credit_score_range',
            'must_have_features', 'deal_breakers', 'lifestyle_notes',
            'status', 'priority_level', 'tags',
            'last_property_view', 'total_properties_viewed',
            'total_inquiries_made', 'conversion_score', 'conversion_score_display',
            'created_at', 'updated_at', 'matching_properties'
        ]
        read_only_fields = [
            'id', 'user', 'username', 'full_name', 'email', 'phone',
            'agency_name', 'agency_id',
            'last_property_view',
            'total_properties_viewed', 'total_inquiries_made', 'conversion_score',
            'created_at', 'updated_at', 'matching_properties', 'conversion_score_display'
        ]
    
    def _client_agency(self, obj):
        try:
            profile = getattr(obj.user, 'profile', None)
            if profile and profile.agency_id:
                return profile.agency
        except Exception:
            pass
        reservation = getattr(obj, '_primary_reservation', None)
        if reservation is None:
            from apps.reservations.models import Reservation
            reservation = (
                Reservation.objects.filter(client_profile=obj)
                .select_related('property__agency')
                .order_by('-created_at')
                .first()
            )
        if reservation and reservation.property and reservation.property.agency_id:
            return reservation.property.agency
        return None

    def get_agency_name(self, obj):
        agency = self._client_agency(obj)
        return agency.name if agency else None

    def get_agency_id(self, obj):
        agency = self._client_agency(obj)
        return str(agency.id) if agency else None
    
    def get_matching_properties(self, obj):
        """Get matching properties for the client."""
        try:
            matcher = PropertyMatcher(obj)
            properties = matcher.find_matches(limit=5)
            
            return PropertyListSerializer(properties, many=True, context=self.context).data
        except Exception:
            return []
    
    def validate_max_budget(self, value):
        """Validate max budget is positive."""
        if value and value <= 0:
            raise serializers.ValidationError("Le budget maximum doit être supérieur à 0.")
        return value
    
    def validate_min_budget(self, value):
        """Validate min budget is positive."""
        if value and value <= 0:
            raise serializers.ValidationError("Le budget minimum doit être supérieur à 0.")
        return value
    
    def validate(self, data):
        """Validate budget range consistency."""
        max_budget = data.get('max_budget')
        min_budget = data.get('min_budget')
        
        if max_budget and min_budget and max_budget < min_budget:
            raise serializers.ValidationError("Le budget maximum doit être supérieur au budget minimum.")
        
        max_bedrooms = data.get('max_bedrooms')
        min_bedrooms = data.get('min_bedrooms')
        
        if max_bedrooms and min_bedrooms and max_bedrooms < min_bedrooms:
            raise serializers.ValidationError("Le nombre maximum de chambres doit être supérieur au minimum.")
        
        max_area = data.get('max_area')
        min_area = data.get('min_area')
        
        if max_area and min_area and max_area < min_area:
            raise serializers.ValidationError("La superficie maximum doit être supérieure au minimum.")
        
        return data


class PropertyInterestSerializer(serializers.ModelSerializer):
    """
    Serializer for property interest tracking.
    """
    client = serializers.StringRelatedField(read_only=True)
    client_id = serializers.UUIDField(write_only=True)
    property = serializers.StringRelatedField(read_only=True)
    property_id = serializers.UUIDField(write_only=True)
    property_title = serializers.CharField(source='property.title', read_only=True)
    property_type = serializers.CharField(source='property.property_type', read_only=True)
    property_price = serializers.DecimalField(source='property.price', max_digits=12, decimal_places=2, read_only=True)
    property_city = serializers.CharField(source='property.city', read_only=True)
    match_explanation = serializers.SerializerMethodField()
    
    class Meta:
        model = PropertyInterest
        fields = [
            'id', 'client', 'client_id', 'property', 'property_id', 'property_title',
            'property_type', 'property_price', 'property_city',
            'interaction_type', 'interaction_date', 'interest_level', 'match_score',
            'notes', 'status', 'created_at', 'updated_at', 'match_explanation'
        ]
        read_only_fields = [
            'id', 'client', 'property', 'match_score', 'interaction_date',
            'created_at', 'updated_at', 'match_explanation'
        ]
    
    def get_match_explanation(self, obj):
        """Get detailed match explanation."""
        try:
            if hasattr(obj.client, 'client_profile'):
                matcher = PropertyMatcher(obj.client.client_profile)
                return matcher.get_match_explanation(obj.property)
        except Exception:
            pass
        return None
    
    def create(self, validated_data):
        """Create property interest and update client activity."""
        client_id = validated_data.pop('client_id')
        property_id = validated_data.pop('property_id')
        
        client = User.objects.get(id=client_id, role='client')
        property_obj = Property.objects.get(id=property_id)
        
        # Create or update interest
        interest, created = PropertyInterest.objects.get_or_create(
            client=client,
            property=property_obj,
            defaults=validated_data
        )
        
        if not created:
            # Update existing interest
            for key, value in validated_data.items():
                setattr(interest, key, value)
            interest.save()
        
        return interest


class PropertyListSerializer(serializers.ModelSerializer):
    """
    Lightweight property serializer for matching results.
    """
    primary_image_url = serializers.SerializerMethodField()
    agent_name = serializers.CharField(source='agent.get_full_name', read_only=True)
    match_score = serializers.IntegerField(read_only=True, default=0)
    
    class Meta:
        model = Property
        fields = [
            'id', 'title', 'property_type', 'price', 'surface_area',
            'bedrooms', 'bathrooms', 'city', 'agent_name', 'is_featured',
            'primary_image_url', 'match_score'
        ]
    
    def get_primary_image_url(self, obj):
        """Get the primary image URL."""
        primary_image = obj.images.filter(is_primary=True).first()
        if primary_image:
            return primary_image.image.url
        first_image = obj.images.first()
        return first_image.image.url if first_image else None


class ClientInteractionSerializer(serializers.ModelSerializer):
    """
    Serializer for client interactions and communications.
    """
    client = serializers.StringRelatedField(read_only=True)
    client_id = serializers.UUIDField(write_only=True)
    agent = serializers.StringRelatedField(read_only=True)
    agent_id = serializers.UUIDField(write_only=True)
    client_name = serializers.CharField(source='client.get_full_name', read_only=True)
    agent_name = serializers.CharField(source='agent.get_full_name', read_only=True)
    related_property = serializers.SerializerMethodField()
    related_object_type = serializers.CharField(source='content_type.model', read_only=True)
    
    class Meta:
        model = ClientInteraction
        fields = [
            'id', 'client', 'client_id', 'agent', 'agent_id',
            'client_name', 'agent_name',
            'interaction_type', 'channel', 'subject', 'content', 'outcome',
            'scheduled_date', 'completed_date', 'duration_minutes',
            'related_property', 'related_object_type',
            'requires_follow_up', 'follow_up_date', 'follow_up_completed',
            'priority', 'status', 'created_at', 'updated_at'
        ]
        read_only_fields = [
            'id', 'client', 'agent', 'client_name', 'agent_name',
            'related_property', 'related_object_type',
            'created_at', 'updated_at'
        ]
    
    def get_related_property(self, obj):
        """Get related property if applicable."""
        if obj.content_type and obj.content_type.model == 'property':
            try:
                return Property.objects.get(id=obj.object_id).title
            except Property.DoesNotExist:
                return None
        return None
    
    def create(self, validated_data):
        """Create client interaction."""
        client_id = validated_data.pop('client_id')
        agent_id = validated_data.pop('agent_id')
        
        client = User.objects.get(id=client_id, role='client')
        agent = User.objects.get(id=agent_id, role='agent')
        
        return ClientInteraction.objects.create(
            client=client, agent=agent, **validated_data
        )
    
    def validate(self, data):
        """Validate interaction data."""
        # Ensure agent is assigned to the client
        if data.get('client') and data.get('agent'):
            client = data['client']
            agent = data['agent']
            
            # Check if agent is assigned to client's agency
            if client.agency != agent.agency:
                raise serializers.ValidationError(
                    "L'agent doit appartenir à la même agence que le client."
                )
        
        return data


class LeadSerializer(serializers.ModelSerializer):
    """
    Serializer for lead management.
    """
    assigned_agent = serializers.StringRelatedField(read_only=True)
    assigned_agent_id = serializers.UUIDField(write_only=True, required=False)
    agency = serializers.StringRelatedField(read_only=True)
    agency_id = serializers.UUIDField(write_only=True)
    full_name = serializers.CharField(read_only=True)
    urgency_score = serializers.SerializerMethodField()
    next_actions = serializers.SerializerMethodField()
    client_profile_id = serializers.SerializerMethodField()

    class Meta:
        model = Lead
        fields = [
            'id', 'first_name', 'last_name', 'full_name', 'email', 'phone', 'company',
            'source', 'status', 'qualification', 'score', 'urgency_score',
            'property_type_interest', 'budget_range', 'location_interest', 'timeframe',
            'assigned_agent', 'assigned_agent_id', 'agency', 'agency_id',
            'notes', 'next_action', 'next_action_date', 'next_actions',
            'converted_to_client', 'conversion_date', 'lost_reason', 'client_profile_id',
            'created_at', 'updated_at'
        ]
        read_only_fields = [
            'id', 'assigned_agent', 'agency', 'full_name', 'score', 'urgency_score',
            'next_actions', 'converted_to_client', 'conversion_date', 'client_profile_id',
            'created_at', 'updated_at'
        ]
    
    def get_urgency_score(self, obj):
        """Calculate urgency score for the lead."""
        from .matching import LeadMatcher
        matcher = LeadMatcher(obj)
        return matcher.calculate_urgency_score()
    
    def get_next_actions(self, obj):
        """Get recommended next actions."""
        from .matching import LeadMatcher
        matcher = LeadMatcher(obj)
        return matcher.recommend_action()

    def get_client_profile_id(self, obj):
        """When lead is converted, return the linked client profile id for navigation."""
        if not obj.converted_to_client:
            return None
        profile = ClientProfile.objects.filter(
            user__email=obj.email, user__role='client'
        ).values_list('id', flat=True).first()
        return str(profile) if profile else None

    def create(self, validated_data):
        """Create lead and calculate initial score."""
        agency_id = validated_data.pop('agency_id')
        agency = Agency.objects.get(id=agency_id)
        
        lead = Lead.objects.create(agency=agency, **validated_data)
        lead.calculate_score()
        lead.save()
        
        return lead
    
    def validate(self, data):
        """Validate lead data."""
        # Ensure lead source is valid
        valid_sources = dict(Lead.LEAD_SOURCES)
        if data.get('source') and data['source'] not in valid_sources:
            raise serializers.ValidationError("Source de lead invalide.")
        
        return data


class LeadConversionSerializer(serializers.Serializer):
    """
    Serializer for converting leads to clients.
    """
    convert_to_client = serializers.BooleanField(required=True)
    user_data = serializers.JSONField(required=False, help_text="Additional user data for client creation")
    
    def convert(self, validated_data):
        """Convert lead to client."""
        lead = self.instance
        if not validated_data.get('convert_to_client'):
            return lead
        
        client_user = lead.convert_to_client(validated_data.get('user_data'))
        return lead


class PropertyMatchSerializer(serializers.Serializer):
    """
    Serializer for property matching results with detailed analysis.
    """
    property = PropertyListSerializer()
    match_score = serializers.IntegerField()
    match_explanation = serializers.DictField()
    recommendations = serializers.ListField(child=serializers.CharField())


class ClientDashboardSerializer(serializers.Serializer):
    """
    Serializer for client dashboard overview.
    """
    total_interests = serializers.IntegerField()
    recent_interactions = serializers.ListField()
    upcoming_visits = serializers.ListField()
    matching_properties = serializers.ListField()
    activity_summary = serializers.DictField()


class AgentDashboardSerializer(serializers.Serializer):
    """
    Serializer for agent dashboard overview.
    """
    total_clients = serializers.IntegerField()
    pending_leads = serializers.IntegerField()
    upcoming_visits = serializers.ListField()
    recent_interactions = serializers.ListField()
    performance_stats = serializers.DictField()


class ClientNoteSerializer(serializers.ModelSerializer):
    """
    Serializer for client notes (Phase 1 - Post-deployment).
    """
    
    author_name = serializers.CharField(source='author.get_full_name', read_only=True)
    client_name = serializers.CharField(source='client_profile.user.get_full_name', read_only=True)
    is_author = serializers.SerializerMethodField()
    
    class Meta:
        model = ClientNote
        fields = [
            'id', 'client_profile', 'author', 'author_name', 'client_name',
            'title', 'content', 'note_type',
            'is_important', 'is_pinned',
            'reminder_date', 'reminder_sent',
            'created_at', 'updated_at', 'is_author',
        ]
        read_only_fields = ['id', 'author', 'reminder_sent', 'created_at', 'updated_at']
    
    def get_is_author(self, obj):
        """Check if current user is the author."""
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            return obj.author == request.user
        return False
    
    def create(self, validated_data):
        """Auto-set author from request."""
        request = self.context.get('request')
        validated_data['author'] = request.user
        return super().create(validated_data)


class ClientNoteCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating client notes."""
    
    class Meta:
        model = ClientNote
        fields = [
            'title', 'content', 'note_type',
            'is_important', 'is_pinned', 'reminder_date',
        ]
    
    def create(self, validated_data):
        """Auto-set author from request."""
        request = self.context.get('request')
        validated_data['author'] = request.user
        return super().create(validated_data)