"""
Views for property management.
"""

import logging

from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.filters import SearchFilter, OrderingFilter
from rest_framework.exceptions import NotFound
from django_filters.rest_framework import DjangoFilterBackend
# from django.contrib.gis.geos import Point
# from django.contrib.gis.measure import D
from django.db.models import Q, Count, Avg
from django.core.cache import cache
from django.utils import timezone

from apps.auth.models import User
from .models import Property, PropertyImage, PropertyDocument, PropertyVisit
from .serializers import (
    PropertySerializer, PropertyListSerializer, PropertySearchSerializer,
    PropertyImageSerializer, PropertyDocumentSerializer, PropertyVisitSerializer
)
from .permissions import (
    IsPropertyAgentOrOwner, CanViewProperty, IsPropertyAgent, 
    IsAdminOrAgent, CanManageVisits, CanCreateVisit,
    CanUploadDocuments, CanUploadImages
)
import os

logger = logging.getLogger(__name__)


class PropertyViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing property listings.
    """
    queryset = Property.objects.select_related('agent', 'agency').prefetch_related('images', 'documents')
    permission_classes = [permissions.IsAuthenticated, CanViewProperty]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = {
        'property_type': ['exact'],
        'status': ['exact'],
        'price': ['gte', 'lte'],
        'surface_area': ['gte', 'lte'],
        'bedrooms': ['gte', 'lte'],
        'bathrooms': ['gte', 'lte'],
        'city': ['exact', 'icontains'],
        'is_featured': ['exact']
    }
    search_fields = ['title', 'description', 'address_line1', 'city']
    ordering_fields = ['price', 'surface_area', 'created_at', 'view_count']
    ordering = ['-created_at']
    
    def get_serializer_class(self):
        """Return appropriate serializer based on action."""
        if self.action == 'list':
            return PropertyListSerializer
        elif self.action == 'search':
            return PropertySearchSerializer
        else:
            return PropertySerializer
    
    def get_permissions(self):
        """Get permissions for different actions."""
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            permission_classes = [permissions.IsAuthenticated, IsPropertyAgentOrOwner]
        elif self.action in ['create_visit', 'my_visits']:
            permission_classes = [permissions.IsAuthenticated]
        elif self.action in ['categories', 'featured', 'search', 'list', 'retrieve']:
            # Endpoints publics - lecture sans authentification (IsAuthenticatedOrReadOnly)
            permission_classes = [permissions.AllowAny]
        else:
            permission_classes = [permissions.IsAuthenticated, CanViewProperty]
        
        return [permission() for permission in permission_classes]
    
    def get_object(self):
        """For agents: return 404 if property status is not 'available' (detail view)."""
        obj = super().get_object()
        user = self.request.user
        role = getattr(user, 'role', None)
        if user.is_authenticated and role != 'agent' and role != 'admin':
            if obj.status != 'available':
                raise NotFound('Ce bien n\'est pas disponible.')
        return obj
    
    def get_queryset(self):
        """Get filtered queryset based on user role and query parameters."""
        queryset = super().get_queryset()
        
        user = self.request.user
        
        # # Check if user is authenticated first
        # if not user.is_authenticated:
        #     # Anonymous users: only see available and public properties
        #     return queryset.filter(status='available', is_public=True)
        
        # Filter based on user role (authenticated users only)
        print("user:", user)
        role = getattr(user, 'role', None)
        print("role:", role)
        if role == 'client':
            # Clients can only see available and public properties
            queryset = queryset.filter(status='available', is_public=True)
        elif role == 'agent':
            # Agents can see all properties from their agency + public properties
            if hasattr(user, 'profile') and user.profile.agency:
                queryset = queryset.filter(
                    Q(agency=user.profile.agency) | Q(is_public=True)
                )
        elif role == 'admin' or getattr(user, 'is_staff', False) or getattr(user, 'is_superuser', False):
            # Admin can see all properties
            pass
        else:
            # Unknown role: only public available properties
            print("role:", role)
            # queryset = queryset.filter(status='available', is_public=True)
        
        # Apply additional filters from query parameters
        # latitude = self.request.query_params.get('latitude')
        # longitude = self.request.query_params.get('longitude')
        # radius = self.request.query_params.get('radius', 10)  # Default 10km radius
        # 
        # if latitude and longitude:
        #     try:
        #         lat = float(latitude)
        #         lon = float(longitude)
        #         point = Point(lon, lat, srid=4326)
        #         
        #         # Use PostGIS for distance filtering
        #         queryset = queryset.filter(
        #             location__distance_lte=(point, D(km=radius))
        #         ).annotate(
        #             distance=Distance('location', point)
        #         ).order_by('distance')
        #     except (ValueError, TypeError):
        #         pass  # Invalid coordinates, ignore
        
        return queryset
    
    def perform_create(self, serializer):
        """Set the agent and agency when creating a property."""
        user = self.request.user
        
        # Get agency from user profile
        agency = None
        if hasattr(user, 'profile') and user.profile.agency:
            agency = user.profile.agency
        elif hasattr(user, 'agency'):
            agency = user.agency
        
        if not agency:
            from rest_framework.exceptions import ValidationError
            raise ValidationError({"agency": "User must be associated with an agency to create properties."})
        
        serializer.save(agent=user, agency=agency)
    
    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated])
    def increment_views(self, request, pk=None):
        """Increment the view count for a property."""
        try:
            property_obj = self.get_object()
            # Use F() expression to avoid race conditions
            from django.db.models import F
            Property.objects.filter(pk=property_obj.pk).update(view_count=F('view_count') + 1)
            property_obj.refresh_from_db()
            return Response({'view_count': property_obj.view_count})
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
    
    @action(
        detail=True,
        methods=['post'],
        parser_classes=[MultiPartParser, FormParser],
    )
    def add_image(self, request, pk=None):
        """Add an image to a property."""
        property_obj = self.get_object()

        if not CanUploadImages().has_object_permission(request, self, property_obj):
            return Response(
                {'error': 'Vous n\'avez pas la permission d\'ajouter des images.'},
                status=status.HTTP_403_FORBIDDEN
            )

        image_data = request.FILES.get('image')
        is_primary_raw = request.data.get('is_primary', 'false')
        is_primary = is_primary_raw in ['true', 'True', '1', True, 1]

        if not image_data:
            return Response(
                {'error': 'Une image est requise (champ multipart « image »).'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            if is_primary:
                PropertyImage.objects.filter(
                    property=property_obj, is_primary=True
                ).update(is_primary=False)

            image = PropertyImage.objects.create(
                property=property_obj,
                image=image_data,
                is_primary=is_primary,
            )
            serializer = PropertyImageSerializer(
                image, context={'request': request}
            )
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        except OSError as exc:
            logger.exception('add_image: écriture fichier impossible (permissions MEDIA_ROOT?)')
            return Response(
                {
                    'error': 'Impossible d\'enregistrer l\'image sur le serveur.',
                    'detail': str(exc),
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        except Exception as exc:
            logger.exception('add_image failed property=%s user=%s', pk, request.user)
            return Response(
                {
                    'error': 'Erreur lors de l\'enregistrement de l\'image.',
                    'detail': str(exc),
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
    
    @action(detail=True, methods=['delete'], url_path='delete_image/(?P<image_id>[^/.]+)')
    def delete_image(self, request, pk=None, image_id=None):
        """Delete an image from a property."""
        property_obj = self.get_object()
        
        # Check permissions
        if not CanUploadImages().has_object_permission(request, self, property_obj):
            return Response(
                {'error': 'Vous n\'avez pas la permission de supprimer des images.'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        try:
            # suppremer aussi le l'image
            
          

            image = PropertyImage.objects.get(id=image_id, property=property_obj)
            image_path = image.image.path
            if os.path.exists(image_path):
                os.remove(image_path)
            
            image.delete()
            # suppremer aussi le l'image
            return Response({'message': 'Image supprimée avec succès'}, status=status.HTTP_200_OK)
        except PropertyImage.DoesNotExist:
            return Response(
                {'error': 'Image introuvable.'},
                status=status.HTTP_404_NOT_FOUND
            )
    
    @action(detail=True, methods=['post'], url_path='set_primary_image')
    def set_primary_image(self, request, pk=None):
        """Set an image as the primary image for a property."""
        property_obj = self.get_object()
        
        # Check permissions
        if not CanUploadImages().has_object_permission(request, self, property_obj):
            return Response(
                {'error': 'Vous n\'avez pas la permission de modifier les images.'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        image_id = request.data.get('image_id')
        if not image_id:
            return Response(
                {'error': 'image_id est requis.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            # Unset all primary images for this property
            PropertyImage.objects.filter(property=property_obj, is_primary=True).update(is_primary=False)
            
            # Set the new primary image
            image = PropertyImage.objects.get(id=image_id, property=property_obj)
            image.is_primary = True
            image.save()
            
            serializer = PropertyImageSerializer(image)
            return Response(serializer.data, status=status.HTTP_200_OK)
        except PropertyImage.DoesNotExist:
            return Response(
                {'error': 'Image introuvable.'},
                status=status.HTTP_404_NOT_FOUND
            )
    
    @action(detail=True, methods=['post'])
    def add_document(self, request, pk=None):
        """Add a document to a property."""
        property_obj = self.get_object()
        
        # Check permissions
        if not CanUploadDocuments().has_object_permission(request, self, property_obj):
            return Response(
                {'error': 'Vous n\'avez pas la permission d\'ajouter des documents.'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        document_data = request.FILES.get('document')
        document_type = request.data.get('document_type', 'other')
        
        if not document_data:
            return Response(
                {'error': 'Un document est requis.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        document = PropertyDocument.objects.create(
            property=property_obj,
            document=document_data,
            document_type=document_type
        )
        
        serializer = PropertyDocumentSerializer(document)
        return Response(serializer.data, status=status.HTTP_201_CREATED)
    
    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated])
    def create_visit(self, request, pk=None):
        """Schedule a visit for a property."""
        property_obj = self.get_object()
        
        # Check if property is available
        if property_obj.status != 'available':
            return Response(
                {'error': 'Ce bien n\'est pas disponible pour les visites.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Check if user has permission to create visits
        if not CanCreateVisit().has_permission(request, self):
            return Response(
                {'error': 'Vous n\'avez pas la permission de créer des visites.'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Check if user is the agent (agents can create visits for their properties)
        if request.user.role == 'agent' and property_obj.agent != request.user:
            return Response(
                {'error': 'Vous ne pouvez créer des visites que pour vos biens.'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Get client from request or use current user
        client_id = request.data.get('client')
        if client_id:
            try:
                client = User.objects.get(id=client_id, role='client')
            except User.DoesNotExist:
                return Response(
                    {'error': 'Client introuvable.'},
                    status=status.HTTP_400_BAD_REQUEST
                )
        else:
            client = request.user
        
        scheduled_date_str = request.data.get('scheduled_date')
        if not scheduled_date_str:
            return Response(
                {'error': 'La date de visite est requise.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            scheduled_date = timezone.datetime.fromisoformat(scheduled_date_str.replace('Z', '+00:00'))
        except (ValueError, TypeError):
            return Response(
                {'error': 'Format de date invalide. Utilisez le format ISO 8601.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        notes = request.data.get('notes', '')
        
        visit = PropertyVisit.objects.create(
            property=property_obj,
            client=client,
            agent=property_obj.agent,
            scheduled_date=scheduled_date,
            status='scheduled',
            notes=notes
        )
        
        serializer = PropertyVisitSerializer(visit)
        return Response(serializer.data, status=status.HTTP_201_CREATED)
    
    @action(detail=False, methods=['get'], permission_classes=[permissions.IsAuthenticated])
    def my_properties(self, request):
        """Get all properties created by the current agent."""
        if request.user.role not in ['agent', 'admin', 'manager']:
            return Response(
                {'error': 'Seuls les agents et administrateurs peuvent voir leurs propriétés.'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Filter properties by agent
        queryset = Property.objects.filter(agent=request.user).select_related('agency').prefetch_related('images', 'documents')
        
        # Apply additional filters if provided
        status_filter = request.query_params.get('status')
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        
        property_type_filter = request.query_params.get('property_type')
        if property_type_filter:
            queryset = queryset.filter(property_type=property_type_filter)
        
        # Order by most recent first
        queryset = queryset.order_by('-created_at')
        
        # Serialize and return
        serializer = PropertyListSerializer(queryset, many=True, context={'request': request})
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'], permission_classes=[permissions.IsAuthenticated])
    def my_visits(self, request):
        """Get visits for properties owned by the current agent."""
        if request.user.role not in ['agent', 'admin']:
            return Response(
                {'error': 'Seuls les agents et administrateurs peuvent voir les visites.'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        queryset = PropertyVisit.objects.filter(agent=request.user)
        
        # Filter by status if provided
        status_filter = request.query_params.get('status')
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        
        # Filter by date range
        date_from = request.query_params.get('date_from')
        date_to = request.query_params.get('date_to')
        
        if date_from:
            queryset = queryset.filter(scheduled_date__date__gte=date_from)
        if date_to:
            queryset = queryset.filter(scheduled_date__date__lte=date_to)
        
        queryset = queryset.select_related('property', 'client', 'agent')
        serializer = PropertyVisitSerializer(queryset, many=True)
        
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'])
    def search(self, request):
        """Advanced property search with geolocation and caching."""
        queryset = self.get_queryset()
        
        # Apply filters from query parameters
        queryset = self.filter_queryset(queryset)
        
        # Limit results for performance
        page_size = min(int(request.query_params.get('limit', 20)), 100)
        queryset = queryset[:page_size]
        
        # Cache search results for performance
        import hashlib
        cache_key = f"property_search_{hashlib.md5(str(request.query_params).encode()).hexdigest()}"
        cached_results = cache.get(cache_key)
        
        if cached_results:
            return Response(cached_results)
        
        serializer = self.get_serializer(queryset, many=True)
        
        # Cache results for 5 minutes
        cache.set(cache_key, serializer.data, 300)
        
        return Response({
            'count': len(serializer.data),
            'results': serializer.data
        })
    
    @action(detail=False, methods=['get'])
    def featured(self, request):
        """Get featured properties."""
        queryset = self.get_queryset().filter(is_featured=True)[:20]  # Limit to 20
        serializer = PropertyListSerializer(queryset, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'])
    def statistics(self, request):
        """Get property statistics for the current user with caching."""
        if not request.user.is_authenticated:
            return Response({'error': 'Authentification requise.'}, status=status.HTTP_401_UNAUTHORIZED)
        
        user = request.user
        
        # Check cache first
        cache_key = f"property_stats_{user.id}_{user.role}"
        cached_stats = cache.get(cache_key)
        if cached_stats:
            return Response(cached_stats)
        
        if user.role == 'admin' or user.is_staff or user.is_superuser:
            queryset = Property.objects.all()
        elif user.role == 'agent':
            queryset = Property.objects.filter(agent=user)
        else:
            return Response({'error': 'Statistiques non disponibles pour ce rôle.'}, status=status.HTTP_403_FORBIDDEN)
        
        # Optimize with single query using aggregation
        from django.db.models import Sum, Case, When, IntegerField
        
        aggregated = queryset.aggregate(
            total=Count('id'),
            available=Count('id', filter=Q(status='available')),
            under_offer=Count('id', filter=Q(status='under_offer')),
            reserved=Count('id', filter=Q(status='reserved')),
            sold=Count('id', filter=Q(status='sold')),
            rented=Count('id', filter=Q(status='rented')),
            avg_price=Avg('price'),
            total_views=Sum('view_count')
        )
        
        # Get property types distribution
        property_types_dist = dict(
            queryset.values('property_type')
            .annotate(count=Count('id'))
            .values_list('property_type', 'count')
        )
        
        stats = {
            'total_properties': aggregated['total'] or 0,
            'available_properties': aggregated['available'] or 0,
            'under_offer_properties': aggregated['under_offer'] or 0,
            'reserved_properties': aggregated['reserved'] or 0,
            'sold_properties': aggregated['sold'] or 0,
            'rented_properties': aggregated['rented'] or 0,
            'avg_price': float(aggregated['avg_price'] or 0),
            'total_views': aggregated['total_views'] or 0,
            'property_types': property_types_dist
        }
        
        # Cache for 10 minutes
        cache.set(cache_key, stats, 600)
        
        return Response(stats)
    
    @action(detail=False, methods=['get'], permission_classes=[permissions.AllowAny])
    def categories(self, request):
        """Get property categories with counts for filters (public endpoint)."""
        # Check cache first
        cache_key = 'property_categories_public'
        cached_categories = cache.get(cache_key)
        if cached_categories:
            return Response(cached_categories)
        
        # Only count available and public properties for public stats
        queryset = Property.objects.filter(status='available', is_public=True)
        
        # Get total count
        total_count = queryset.count()
        
        # Get counts by property type
        property_types_counts = dict(
            queryset.values('property_type')
            .annotate(count=Count('id'))
            .values_list('property_type', 'count')
        )
        
        # Property type labels mapping with emojis
        property_type_labels = {
            'apartment': {'label': 'Appartements', 'icon': '🏢'},
            'house': {'label': 'Maisons', 'icon': '🏠'},
            'villa': {'label': 'Villas', 'icon': '🏡'},
            'penthouse': {'label': 'Penthouses', 'icon': '🏙️'},
            'loft': {'label': 'Lofts', 'icon': '🏗️'},
            'duplex': {'label': 'Duplex', 'icon': '🏘️'},
            'triplex': {'label': 'Triplex', 'icon': '🏘️'},
            'studio': {'label': 'Studios', 'icon': '🛏️'},
            'commercial': {'label': 'Commerces', 'icon': '🏪'},
            'office': {'label': 'Bureaux', 'icon': '💼'},
            'land': {'label': 'Terrains', 'icon': '🌳'},
            'parking': {'label': 'Parkings', 'icon': '🅿️'},
            'cellar': {'label': 'Caves', 'icon': '📦'},
            'garage': {'label': 'Garages', 'icon': '🚗'},
        }
        
        # Build categories array
        categories = [{
            'id': 'all',
            'label': 'Tous',
            'icon': '🏠',
            'count': total_count
        }]
        
        # Add categories with counts > 0, sorted by count descending
        for property_type, count in sorted(property_types_counts.items(), key=lambda x: x[1], reverse=True):
            if count > 0 and property_type in property_type_labels:
                categories.append({
                    'id': property_type,
                    'label': property_type_labels[property_type]['label'],
                    'icon': property_type_labels[property_type]['icon'],
                    'count': count
                })
        
        # Cache for 15 minutes
        cache.set(cache_key, categories, 900)
        
        return Response(categories)


class PropertyImageViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing property images.
    """
    queryset = PropertyImage.objects.all()
    serializer_class = PropertyImageSerializer
    permission_classes = [permissions.IsAuthenticated, IsPropertyAgentOrOwner]
    
    def get_queryset(self):
        """Filter images by property."""
        property_id = self.request.query_params.get('property')
        if property_id:
            return PropertyImage.objects.filter(property_id=property_id)
        return PropertyImage.objects.all()


class PropertyDocumentViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing property documents.
    """
    queryset = PropertyDocument.objects.all()
    serializer_class = PropertyDocumentSerializer
    permission_classes = [permissions.IsAuthenticated, IsPropertyAgentOrOwner]
    
    def get_queryset(self):
        """Filter documents by property."""
        property_id = self.request.query_params.get('property')
        if property_id:
            return PropertyDocument.objects.filter(property_id=property_id)
        return PropertyDocument.objects.all()


class PropertyVisitViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing property visits.
    """
    queryset = PropertyVisit.objects.select_related('property')
    serializer_class = PropertyVisitSerializer
    permission_classes = [permissions.IsAuthenticated, CanManageVisits]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = {
        'status': ['exact'],
        'scheduled_date': ['gte', 'lte'],
        'property': ['exact'],
        'visit_type': ['exact']
    }
    
    def get_queryset(self):
        """Filter visits based on user permissions."""
        user = self.request.user
        queryset = super().get_queryset()
        
        # Admin and staff see all visits
        if user.is_staff or user.is_superuser:
            return queryset
        
        # Filter by property agent for agents
        return queryset.filter(property__agent=user)
    
    def perform_create(self, serializer):
        """Save the visit."""
        serializer.save()