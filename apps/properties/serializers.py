"""
Serializers for property management.
"""

from rest_framework import serializers
# from django.contrib.gis.geos import Point
from django.core.validators import MinValueValidator
from apps.auth.models import User, Agency
from .models import Property, PropertyImage, PropertyDocument, PropertyVisit


class PropertyImageSerializer(serializers.ModelSerializer):
    """Serializer for property images."""

    image = serializers.SerializerMethodField()

    class Meta:
        model = PropertyImage
        fields = [
            'id', 'image', 'thumbnail', 'title', 'description', 'alt_text',
            'is_primary', 'order', 'created_at',
        ]
        read_only_fields = ['id', 'thumbnail', 'created_at']

    def get_image(self, obj):
        if not obj.image:
            return None
        request = self.context.get('request')
        url = obj.image.url
        if request is not None:
            return request.build_absolute_uri(url)
        return url


class PropertyDocumentSerializer(serializers.ModelSerializer):
    """Serializer for property documents."""
    
    class Meta:
        model = PropertyDocument
        fields = ['id', 'title', 'document_file', 'document_type', 'is_public', 'file_size', 'mime_type', 'created_at']
        read_only_fields = ['id', 'file_size', 'mime_type', 'created_at']


class PropertyVisitSerializer(serializers.ModelSerializer):
    """Serializer for property visits."""
    property_title = serializers.CharField(source='property.title', read_only=True)
    property_address = serializers.CharField(source='property.get_full_address', read_only=True)
    property_type_display = serializers.CharField(source='property.property_type_display', read_only=True)
    client_name = serializers.CharField(source='client.get_full_name', read_only=True)
    client_phone = serializers.CharField(source='client.phone', read_only=True)
    agent_name = serializers.CharField(source='agent.get_full_name', read_only=True)
    
    class Meta:
        model = PropertyVisit
        fields = [
            'id', 'property', 'property_title', 'property_address', 'property_type_display',
            'client', 'client_name', 'client_phone',
            'visit_type', 'scheduled_date', 'duration_minutes',
            'visitor_name', 'visitor_email', 'visitor_phone', 'visitor_count',
            'status', 'notes', 'visitor_notes', 'agent_notes', 'feedback', 'rating',
            'agent', 'agent_name', 'created_at', 'updated_at'
        ]
        read_only_fields = [
            'id', 'created_at', 'updated_at', 'property_title', 
            'property_address', 'property_type_display', 'client_name', 'client_phone', 'agent_name'
        ]

class PropertySerializer(serializers.ModelSerializer):
    """Serializer for property listings."""
    
    # Related field serializers
    images = PropertyImageSerializer(many=True, read_only=True)
    documents = PropertyDocumentSerializer(many=True, read_only=True)
    agent = serializers.StringRelatedField(read_only=True)
    agent_name = serializers.CharField(source='agent.get_full_name', read_only=True)
    agency = serializers.StringRelatedField(read_only=True)
    agency_name = serializers.CharField(source='agency.name', read_only=True)
    
    # Primary key fields for nested operations
    images_data = serializers.ListField(
        child=serializers.ImageField(),
        write_only=True,
        required=False,
        allow_empty=True
    )
    primary_image_url = serializers.SerializerMethodField()
    
    # Computed fields
    full_price = serializers.SerializerMethodField()
    price_per_sqm = serializers.SerializerMethodField()
    formatted_address = serializers.SerializerMethodField()
    
    class Meta:
        model = Property
        fields = [
            'id', 'title', 'description', 'property_type', 'status',
            'price', 'full_price', 'surface_area', 'bedrooms', 'bathrooms', 'rooms', 'floor',
            'year_built', 'heating_type', 'furnished', 
            # Basic Features
            'has_parking', 'has_balcony', 'has_terrace', 'has_garden', 'has_pool', 'has_elevator',
            'has_garage', 'has_fireplace', 'has_air_conditioning', 'has_security_system',
            # Bathroom Features
            'has_bathtub', 'has_outdoor_shower', 'has_hot_water',
            # Bedroom & Laundry Features
            'has_washing_machine', 'has_dryer', 'has_essentials', 'has_hangers', 'has_sheets',
            'has_extra_pillows_blankets', 'has_blinds', 'has_iron', 'has_clothes_rack', 'has_clothes_storage',
            # Entertainment & Family
            'has_tv', 'has_baby_crib', 'has_children_playroom',
            # Heating & Cooling
            'has_portable_fans', 'has_heating',
            # Security
            'has_outdoor_security_cameras', 'has_security_cameras', 'has_smoke_detector', 'has_carbon_monoxide_detector',
            # Internet & Office
            'has_wifi', 'has_portable_wifi',
            # Kitchen & Dining
            'has_kitchen', 'has_refrigerator', 'has_microwave', 'has_basic_kitchen_equipment',
            'has_dishes_utensils', 'has_freezer', 'has_dishwasher', 'has_stove', 'has_oven',
            'has_coffee_maker', 'has_blender', 'has_dining_table',
            # Outdoor
            'has_backyard', 'has_outdoor_furniture', 'has_outdoor_dining_space',
            'has_outdoor_kitchen', 'has_lounge_chairs',
            # Parking & Facilities
            'has_free_parking_on_premises', 'has_free_street_parking', 'has_year_round_pool',
            # Services
            'has_luggage_dropoff_allowed', 'has_long_term_stays_allowed',
            'has_cleaning_during_stay', 'has_key_exchange_by_host',
            # Location
            'address_line1', 'address_line2', 'city', 'country', 'postal_code', 'latitude', 'longitude',
            # Additional
            'amenities', 'additional_features', 'furnished_level',
            # Relations
            'agent', 'agent_name', 'agency', 'agency_name',
            # Metadata
            'is_featured', 'view_count', 'available_from', 'created_at', 'updated_at',
            'images', 'documents', 'primary_image_url', 'price_per_sqm', 'formatted_address',
            'images_data', 'property_type_display'
        ]
        read_only_fields = [
            'id', 'view_count', 'created_at', 'updated_at', 'agent', 'agent_name',
            'agency', 'agency_name', 'images', 'documents', 'primary_image_url',
            'full_price', 'price_per_sqm', 'formatted_address', 'property_type_display'
        ]
    
    def get_primary_image_url(self, obj):
        """Get the primary image URL or the first image."""
        primary_image = obj.images.filter(is_primary=True).first()
        if primary_image:
            return primary_image.image.url
        first_image = obj.images.first()
        return first_image.image.url if first_image else None
    
    def get_full_price(self, obj):
        """Get formatted price with currency."""
        return f"{obj.price:,.0f} FCFA"
    
    def get_price_per_sqm(self, obj):
        """Calculate and return price per square meter."""
        if obj.surface_area and obj.surface_area > 0:
            return f"{(obj.price / obj.surface_area):,.0f} FCFA"
        return None
    
    def get_formatted_address(self, obj):
        """Get formatted address."""
        return obj.get_full_address()
    
    def validate_price(self, value):
        """Validate price is positive."""
        if value <= 0:
            raise serializers.ValidationError("Le prix doit être supérieur à 0.")
        return value
    
    def validate_surface_area(self, value):
        """Validate surface area is positive."""
        if value <= 0:
            raise serializers.ValidationError("La superficie doit être supérieure à 0.")
        return value
    
    def validate_bedrooms(self, value):
        """Validate bedrooms count."""
        if value < 0:
            raise serializers.ValidationError("Le nombre de chambres ne peut pas être négatif.")
        return value
    
    def validate_bathrooms(self, value):
        """Validate bathrooms count."""
        if value < 0:
            raise serializers.ValidationError("Le nombre de salles de bain ne peut pas être négatif.")
        return value
    
    def validate(self, data):
        """Custom validation for property data."""
        # Validate coordinate consistency
        latitude = data.get('latitude')
        longitude = data.get('longitude')
        
        if latitude is not None and (latitude < -90 or latitude > 90):
            raise serializers.ValidationError("La latitude doit être entre -90 et 90.")
        
        if longitude is not None and (longitude < -180 or longitude > 180):
            raise serializers.ValidationError("La longitude doit être entre -180 et 180.")
        
        # Validate required fields based on property type
        if data.get('property_type') == 'commercial' and not data.get('features', {}).get('commercial_type'):
            raise serializers.ValidationError("Le type d'activité commerciale est requis pour les biens commerciaux.")
        
        return data
    
    def create(self, validated_data):
        """Create property with images and location."""
        images_data = validated_data.pop('images_data', [])
        
        # Create property
        property_instance = super().create(validated_data)
        
        # Add images
        for i, image_data in enumerate(images_data):
            PropertyImage.objects.create(
                property=property_instance,
                image=image_data,
                is_primary=(i == 0)  # First image is primary
            )
        
        return property_instance


class PropertyListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for property listings."""
    
    primary_image_url = serializers.SerializerMethodField()
    agent_name = serializers.CharField(source='agent.get_full_name', read_only=True)
    full_price = serializers.SerializerMethodField()
    price_per_sqm = serializers.SerializerMethodField()
    
    class Meta:
        model = Property
        fields = [
            'id', 'title', 'description', 'property_type', 'status',
            'price', 'full_price', 'surface_area', 'bedrooms', 'bathrooms', 'city',
            'agent_name', 'is_featured', 'primary_image_url', 'price_per_sqm',
            'created_at', 'property_type_display'
        ]
    
    def get_primary_image_url(self, obj):
        """Get the primary image URL."""
        primary_image = obj.images.filter(is_primary=True).first()
        if primary_image:
            return primary_image.image.url
        first_image = obj.images.first()
        return first_image.image.url if first_image else None
    
    def get_full_price(self, obj):
        """Get formatted price."""
        return f"{obj.price:,.0f} FCFA"
    
    def get_price_per_sqm(self, obj):
        """Calculate price per square meter."""
        if obj.surface_area and obj.surface_area > 0:
            return f"{(obj.price / obj.surface_area):,.0f} FCFA"
        return None


class PropertySearchSerializer(serializers.ModelSerializer):
    """Serializer for property search results."""
    
    class Meta:
        model = Property
        fields = ['id', 'title', 'description', 'property_type', 'status', 
                 'price', 'surface_area', 'bedrooms', 'bathrooms', 'city', 'latitude', 'longitude', 'property_type_display']