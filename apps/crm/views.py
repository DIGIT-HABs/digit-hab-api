"""
Views for CRM (Client Relationship Management).
"""

from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.filters import SearchFilter, OrderingFilter
from django_filters.rest_framework import DjangoFilterBackend
from django.utils import timezone
from django.db.models import Q, Count, Avg, Sum
from django.core.cache import cache
from django.http import HttpResponse
from datetime import datetime, timedelta

from apps.auth.models import User, Agency, UserProfile
from apps.properties.models import Property
from .models import ClientProfile, PropertyInterest, ClientInteraction, Lead, ClientNote
from .serializers import (
    ClientProfileSerializer, PropertyInterestSerializer, ClientInteractionSerializer,
    LeadSerializer, LeadConversionSerializer, PropertyMatchSerializer,
    ClientDashboardSerializer, AgentDashboardSerializer,
    ClientNoteSerializer, ClientNoteCreateSerializer, PropertyListSerializer
)
from .permissions import (
    IsClientOrOwner, IsAgentOrAdmin, CanManageClientProfile, CanManageLeads,
    CanCreateLead, CanAssignLeads, CanAccessPropertyInterests, CanManageInteractions,
    CanCreateInteraction, CanAccessMatchingResults, CanViewDashboard, CanConvertLead
)
from .matching import PropertyMatcher, LeadMatcher, auto_match_properties_for_client, auto_assign_leads_to_agents
from apps.reservations.models import Reservation
from apps.reservations.serializers import ReservationSerializer
from .services import ReportingService


class ClientProfileViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing client profiles.
    """
    queryset = ClientProfile.objects.select_related('user')
    serializer_class = ClientProfileSerializer
    permission_classes = [permissions.IsAuthenticated, CanManageClientProfile]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = {
        'status': ['exact'],
        'priority_level': ['exact'],
        'financing_status': ['exact'],
        'conversion_score': ['gte', 'lte']
    }
    search_fields = ['user__username', 'user__email', 'user__first_name', 'user__last_name']
    ordering_fields = ['conversion_score', 'created_at', 'updated_at', 'total_properties_viewed']
    ordering = ['-conversion_score']
    
    def get_queryset(self):
        """Filter queryset based on user role and permissions."""
        user = self.request.user
        queryset = super().get_queryset()
        
        if user.role == 'admin':
            # Admin can see all client profiles
            queryset = queryset
        elif user.role == 'agent':
            # Agent can see:
            # 1) clients whose user profile is already attached to their agency
            # 2) clients linked to reservations on properties of their agency
            #    (even if the client user profile stays in the DEFAULT-CLIENTS agency)
            reservation_client_ids = Reservation.objects.filter(
                client_profile__isnull=False,
                property__agency=user.agency,
            ).values_list('client_profile_id', flat=True).distinct()

            queryset = queryset.filter(
                Q(user__profile__agency=user.agency) | Q(id__in=reservation_client_ids)
            )
        elif user.role == 'client':
            # Client can only see their own profile
            return queryset.filter(user=user)
        else:
            return queryset.none()

        # Quick filters for list (agent dashboard)
        if self.action == 'list':
            if self.request.query_params.get('has_active_reservation') == 'true':
                queryset = queryset.filter(
                    id__in=Reservation.objects.filter(
                        client_profile__isnull=False,
                        status__in=['pending', 'confirmed']
                    ).values_list('client_profile_id', flat=True).distinct()
                )
            if self.request.query_params.get('needs_follow_up') == 'true':
                # ClientInteraction.client is User; ClientProfile.user is User
                queryset = queryset.filter(
                    user__interactions__requires_follow_up=True,
                    user__interactions__follow_up_completed=False
                ).distinct()
        return queryset
    
    def get_permissions(self):
        """Get permissions for different actions."""
        if self.action == 'create':
            permission_classes = [permissions.IsAuthenticated, IsAgentOrAdmin]
        elif self.action in ['update', 'partial_update', 'destroy']:
            permission_classes = [permissions.IsAuthenticated, CanManageClientProfile]
        else:
            permission_classes = [permissions.IsAuthenticated, CanViewDashboard]
        
        return [permission() for permission in permission_classes]
    
    @action(detail=False, methods=['post'], url_path='create_full', permission_classes=[permissions.IsAuthenticated, IsAgentOrAdmin])
    def create_full(self, request):
        """
        Create or update a full client (user + client profile).
        
        Expected payload:
        {
          "user": {
            "first_name": "...",
            "last_name": "...",
            "email": "...",
            "phone": "..."
          },
          "profile": {
            ... fields from ClientProfileSerializer (except user_id) ...
          }
        }
        """
        user_data = request.data.get('user') or {}
        profile_data = request.data.get('profile') or {}

        email = (user_data.get('email') or '').strip().lower()
        first_name = (user_data.get('first_name') or '').strip()
        last_name = (user_data.get('last_name') or '').strip()

        if not email or not first_name or not last_name:
            return Response(
                {'detail': 'Prénom, nom et email sont obligatoires.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Resolve agency (for agents we use their agency via profile)
        agency = None
        if getattr(request.user, 'role', None) == 'agent':
            agency = getattr(getattr(request.user, 'profile', None), 'agency', None)

        # Find or create user
        user = User.objects.filter(email=email).first()
        if user:
            # Ensure user is marked as client
            updated_fields = []
            if user.role != 'client':
                user.role = 'client'
                updated_fields.append('role')
            # Keep names/phone in sync if provided
            if first_name and user.first_name != first_name:
                user.first_name = first_name
                updated_fields.append('first_name')
            if last_name and user.last_name != last_name:
                user.last_name = last_name
                updated_fields.append('last_name')
            phone = user_data.get('phone')
            if phone is not None and phone != user.phone:
                user.phone = phone
                updated_fields.append('phone')
            if updated_fields:
                user.save(update_fields=updated_fields)

            # Ensure profile/agency linkage
            if agency is not None:
                profile = getattr(user, 'profile', None)
                if profile:
                    if profile.agency != agency:
                        profile.agency = agency
                        profile.save(update_fields=['agency'])
                else:
                    UserProfile.objects.create(user=user, agency=agency)
        else:
            # Create a new client user
            base_username = email.split('@')[0] or 'client'
            username = base_username
            counter = 1
            while User.objects.filter(username=username).exists():
                username = f"{base_username}_{counter}"
                counter += 1
            user = User.objects.create_user(
                username=username,
                email=email,
                first_name=first_name,
                last_name=last_name,
                phone=user_data.get('phone', ''),
                role='client',
            )

            # Create profile with agency if available
            if agency is not None:
                UserProfile.objects.create(user=user, agency=agency)

        # Create or update client profile
        if hasattr(user, 'client_profile'):
            client_profile = user.client_profile
            serializer = ClientProfileSerializer(
                client_profile,
                data=profile_data,
                partial=True,
                context={'request': request},
            )
        else:
            profile_payload = profile_data.copy()
            profile_payload['user_id'] = str(user.id)
            serializer = ClientProfileSerializer(
                data=profile_payload,
                context={'request': request},
            )

        if serializer.is_valid():
            client_profile = serializer.save()
            return Response(
                ClientProfileSerializer(client_profile, context={'request': request}).data,
                status=status.HTTP_201_CREATED,
            )

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    @action(detail=True, methods=['get'], permission_classes=[permissions.IsAuthenticated])
    def matching_properties(self, request, pk=None):
        """Get matching properties for a client profile."""
        try:
            client_profile = self.get_object()
            matcher = PropertyMatcher(client_profile)
            properties = matcher.find_matches(limit=10)
            
            # Add match scores to properties
            properties_with_scores = []
            for prop in properties:
                score = matcher.calculate_match_score(prop)
                properties_with_scores.append({
                    'property': prop,
                    'match_score': score,
                    'match_explanation': matcher.get_match_explanation(prop)
                })
            
            results = []
            for prop_data in properties_with_scores:
                prop_serializer = self.get_serializer().Meta.model.__bases__[0].__dict__['Meta'].model
                property_data = {
                    'property': prop_data['property'],
                    'match_score': prop_data['match_score'],
                    'match_explanation': prop_data['match_explanation'],
                    'recommendations': prop_data['match_explanation']['recommendations']
                }
                results.append(property_data)
            
            return Response(results)
            
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
    
    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated])
    def update_activity(self, request, pk=None):
        """Update client activity statistics."""
        try:
            client_profile = self.get_object()
            client_profile.update_activity()
            
            return Response({
                'total_properties_viewed': client_profile.total_properties_viewed,
                'total_inquiries_made': client_profile.total_inquiries_made,
                'conversion_score': client_profile.conversion_score
            })
            
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
    
    @action(detail=True, methods=['get'], permission_classes=[permissions.IsAuthenticated])
    def dashboard(self, request, pk=None):
        """Get client dashboard data."""
        try:
            client_profile = self.get_object()
            client_user = client_profile.user
            
            # Get recent interactions
            recent_interactions = ClientInteraction.objects.filter(
                client=client_user
            ).order_by('-created_at')[:5]
            
            # Get upcoming visits
            upcoming_visits = PropertyInterest.objects.filter(
                client=client_user,
                interaction_type='visit_scheduled',
                status='active'
            ).order_by('interaction_date')[:5]
            
            # Get reservations for this client profile
            reservations = Reservation.objects.filter(
                client_profile=client_profile
            ).order_by('-created_at')[:5]
            
            # Get matching properties and serialize them
            matching_qs = client_profile.get_matching_properties(limit=5)
            matching_properties = PropertyListSerializer(
                matching_qs, many=True, context={'request': request}
            ).data
            
            # Activity summary
            activity_summary = {
                'total_interests': client_profile.total_properties_viewed,
                'total_inquiries': client_profile.total_inquiries_made,
                'conversion_score': client_profile.conversion_score,
                'last_activity': client_profile.last_property_view
            }
            
            dashboard_data = {
                'profile': ClientProfileSerializer(client_profile).data,
                'recent_interactions': ClientInteractionSerializer(recent_interactions, many=True).data,
                'upcoming_visits': PropertyInterestSerializer(upcoming_visits, many=True).data,
                 'reservations': ReservationSerializer(reservations, many=True).data,
                'matching_properties': matching_properties,
                'activity_summary': activity_summary
            }
            
            return Response(dashboard_data)
            
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
    
    @action(detail=True, methods=['get'], permission_classes=[permissions.IsAuthenticated, CanManageInteractions])
    def interactions(self, request, pk=None):
        """Get all interactions for a specific client."""
        try:
            client_profile = self.get_object()
            client_user = client_profile.user
            
            # Get query parameters
            interaction_type = request.query_params.get('interaction_type')
            status_filter = request.query_params.get('status')
            limit = int(request.query_params.get('limit', 50))
            
            # Build queryset
            interactions = ClientInteraction.objects.filter(client=client_user)
            
            if interaction_type:
                interactions = interactions.filter(interaction_type=interaction_type)
            if status_filter:
                interactions = interactions.filter(status=status_filter)
            
            interactions = interactions.order_by('-created_at')[:limit]
            
            serializer = ClientInteractionSerializer(interactions, many=True)
            return Response(serializer.data)
            
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
    
    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated, CanCreateInteraction])
    def add_interaction(self, request, pk=None):
        """Add a new interaction for a client."""
        try:
            client_profile = self.get_object()
            client_user = client_profile.user
            
            # Get agent (default to current user if agent)
            agent_id = request.data.get('agent_id')
            if agent_id:
                agent = User.objects.get(id=agent_id, role='agent')
            elif request.user.role == 'agent':
                agent = request.user
            else:
                return Response(
                    {'error': 'Agent requis pour créer une interaction.'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Create interaction
            interaction_data = {
                'client_id': str(client_user.id),
                'agent_id': str(agent.id),
                'interaction_type': request.data.get('interaction_type', 'call'),
                'channel': request.data.get('channel', 'phone'),
                'subject': request.data.get('subject', ''),
                'content': request.data.get('content', ''),
                'scheduled_date': request.data.get('scheduled_date'),
                'priority': request.data.get('priority', 'medium'),
                'status': request.data.get('status', 'scheduled')
            }
            
            serializer = ClientInteractionSerializer(data=interaction_data)
            if serializer.is_valid():
                interaction = serializer.save()
                return Response(ClientInteractionSerializer(interaction).data, status=status.HTTP_201_CREATED)
            else:
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
            
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
    
    @action(detail=True, methods=['get'], url_path='notes', permission_classes=[permissions.IsAuthenticated, IsAgentOrAdmin])
    def notes(self, request, pk=None):
        """Get all notes for a specific client (Phase 1)."""
        client_profile = self.get_object()
        notes = ClientNote.objects.filter(client_profile=client_profile).select_related('author')
        serializer = ClientNoteSerializer(notes, many=True, context={'request': request})
        return Response(serializer.data)
    
    @action(detail=True, methods=['post'], url_path='notes/add', permission_classes=[permissions.IsAuthenticated, IsAgentOrAdmin])
    def add_note(self, request, pk=None):
        """Add a new note for a client (Phase 1)."""
        client_profile = self.get_object()
        serializer = ClientNoteCreateSerializer(data=request.data, context={'request': request})
        
        if serializer.is_valid():
            serializer.save(client_profile=client_profile)
            return Response(
                ClientNoteSerializer(serializer.instance, context={'request': request}).data,
                status=status.HTTP_201_CREATED
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    @action(detail=True, methods=['patch'], url_path='tags', permission_classes=[permissions.IsAuthenticated, IsAgentOrAdmin])
    def update_tags(self, request, pk=None):
        """Update client tags (Phase 1)."""
        client_profile = self.get_object()
        tags = request.data.get('tags', [])
        
        if not isinstance(tags, list):
            return Response(
                {'error': 'Tags doit être une liste'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        client_profile.tags = tags
        client_profile.save(update_fields=['tags'])
        
        return Response({
            'tags': client_profile.tags,
            'message': 'Tags mis à jour avec succès'
        })
    
    @action(detail=True, methods=['get'], permission_classes=[permissions.IsAuthenticated])
    def stats(self, request, pk=None):
        """Get client statistics."""
        try:
            client_profile = self.get_object()
            client_user = client_profile.user
            
            # Get interactions stats
            total_interactions = ClientInteraction.objects.filter(client=client_user).count()
            completed_interactions = ClientInteraction.objects.filter(
                client=client_user, status='completed'
            ).count()
            
            # Get property interests stats
            total_interests = PropertyInterest.objects.filter(client=client_user).count()
            active_interests = PropertyInterest.objects.filter(
                client=client_user, status='active'
            ).count()
            
            # Get visits stats
            total_visits = PropertyInterest.objects.filter(
                client=client_user, interaction_type__in=['visit_scheduled', 'visit_request']
            ).count()
            
            # Get recent activity (last 30 days)
            from datetime import timedelta
            thirty_days_ago = timezone.now() - timedelta(days=30)
            recent_interactions = ClientInteraction.objects.filter(
                client=client_user, created_at__gte=thirty_days_ago
            ).count()
            
            stats = {
                'profile': {
                    'conversion_score': client_profile.conversion_score,
                    'status': client_profile.status,
                    'priority_level': client_profile.priority_level,
                    'total_properties_viewed': client_profile.total_properties_viewed,
                    'total_inquiries_made': client_profile.total_inquiries_made,
                },
                'interactions': {
                    'total': total_interactions,
                    'completed': completed_interactions,
                    'recent_30_days': recent_interactions,
                },
                'interests': {
                    'total': total_interests,
                    'active': active_interests,
                },
                'visits': {
                    'total': total_visits,
                },
                'last_activity': client_profile.last_property_view,
            }
            
            return Response(stats)
            
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
    
    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated, IsAgentOrAdmin])
    def contact(self, request, pk=None):
        """Initiate contact action with client (call, email, SMS)."""
        try:
            client_profile = self.get_object()
            client_user = client_profile.user
            
            contact_method = request.data.get('method', 'call')  # call, email, sms, whatsapp
            subject = request.data.get('subject', '')
            message = request.data.get('message', '')
            
            # Get agent (current user if agent)
            if request.user.role == 'agent':
                agent = request.user
            else:
                return Response(
                    {'error': 'Seuls les agents peuvent contacter les clients.'},
                    status=status.HTTP_403_FORBIDDEN
                )
            
            # Create interaction record
            interaction = ClientInteraction.objects.create(
                client=client_user,
                agent=agent,
                interaction_type='call' if contact_method == 'call' else 'email',
                channel=contact_method,
                subject=subject or f'Contact {contact_method}',
                content=message,
                status='scheduled',
                priority='medium'
            )
            
            from apps.core.activity import log_activity

            log_activity(
                user=agent,
                component='clients',
                action=f'CLIENT_CONTACT_{contact_method.upper()}',
                message=f'Contact client via {contact_method}',
                metadata={
                    'object_type': 'ClientProfile',
                    'object_id': str(client_profile.id),
                    'method': contact_method,
                    'client': str(client_user),
                },
                request=request,
            )
            
            return Response({
                'message': f'Action de contact ({contact_method}) enregistrée.',
                'interaction': ClientInteractionSerializer(interaction).data
            }, status=status.HTTP_201_CREATED)
            
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)


class PropertyInterestViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing property interests.
    """
    queryset = PropertyInterest.objects.select_related('client', 'property')
    serializer_class = PropertyInterestSerializer
    permission_classes = [permissions.IsAuthenticated, CanAccessPropertyInterests]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = {
        'client': ['exact'],
        'property': ['exact'],
        'interaction_type': ['exact'],
        'interest_level': ['exact'],
        'status': ['exact'],
        'match_score': ['gte', 'lte']
    }
    search_fields = ['client__username', 'client__email', 'property__title']
    ordering_fields = ['match_score', 'interaction_date', 'created_at']
    ordering = ['-interaction_date']
    
    def get_queryset(self):
        """Filter queryset based on user role."""
        user = self.request.user
        queryset = super().get_queryset()
        
        if user.role == 'client':
            return queryset.filter(client=user)
        elif user.role == 'agent':
            return queryset.filter(client__profile__agency=user.agency)
        # Admin sees all
        
        return queryset
    
    def perform_create(self, serializer):
        """Create property interest with proper permissions."""
        client_id = self.request.data.get('client_id')
        property_id = self.request.data.get('property_id')
        
        # Validate client and property
        try:
            client = User.objects.get(id=client_id, role='client')
            property_obj = Property.objects.get(id=property_id)
        except (User.DoesNotExist, Property.DoesNotExist):
            raise serializers.ValidationError("Client ou propriété introuvable.")
        
        # Create interest
        interest = PropertyInterest.create_from_interaction(
            client=client,
            property_obj=property_obj,
            interaction_type=self.request.data.get('interaction_type', 'view'),
            notes=self.request.data.get('notes', '')
        )
        
        return interest
    
    @action(detail=False, methods=['post'], permission_classes=[permissions.IsAuthenticated])
    def track_interaction(self, request):
        """Track a new client interaction with a property."""
        client_id = request.data.get('client_id')
        property_id = request.data.get('property_id')
        interaction_type = request.data.get('interaction_type', 'view')
        notes = request.data.get('notes', '')
        
        try:
            client = User.objects.get(id=client_id, role='client')
            property_obj = Property.objects.get(id=property_id)
        except (User.DoesNotExist, Property.DoesNotExist):
            return Response(
                {'error': 'Client ou propriété introuvable.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Create or update interest
        interest = PropertyInterest.create_from_interaction(
            client=client,
            property_obj=property_obj,
            interaction_type=interaction_type,
            notes=notes
        )
        
        serializer = self.get_serializer(interest)
        return Response(serializer.data, status=status.HTTP_201_CREATED)
    
    @action(detail=True, methods=['get'], permission_classes=[permissions.IsAuthenticated])
    def client_interests(self, request, pk=None):
        """Get all interests for a specific client."""
        try:
            client = User.objects.get(id=pk, role='client')
            
            # Check permissions
            if not CanAccessPropertyInterests().has_object_permission(request, self, client):
                return Response(
                    {'error': 'Accès non autorisé.'},
                    status=status.HTTP_403_FORBIDDEN
                )
            
            interests = PropertyInterest.objects.filter(client=client).order_by('-interaction_date')
            serializer = self.get_serializer(interests, many=True)
            
            return Response(serializer.data)
            
        except User.DoesNotExist:
            return Response(
                {'error': 'Client introuvable.'},
                status=status.HTTP_404_NOT_FOUND
            )


class ClientInteractionViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing client interactions.
    """
    queryset = ClientInteraction.objects.select_related('client', 'agent', 'content_type')
    serializer_class = ClientInteractionSerializer
    permission_classes = [permissions.IsAuthenticated, CanManageInteractions]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = {
        'client': ['exact'],
        'agent': ['exact'],
        'interaction_type': ['exact'],
        'channel': ['exact'],
        'priority': ['exact'],
        'status': ['exact'],
        'scheduled_date': ['gte', 'lte'],
        'requires_follow_up': ['exact']
    }
    search_fields = ['client__username', 'client__email', 'agent__username', 'subject', 'content']
    ordering_fields = ['scheduled_date', 'created_at', 'priority']
    ordering = ['-scheduled_date']
    
    def get_queryset(self):
        """Filter queryset based on user role."""
        user = self.request.user
        queryset = super().get_queryset()
        
        if user.role == 'client':
            return queryset.filter(client=user)
        elif user.role == 'agent':
            return queryset.filter(Q(agent=user) | Q(client__profile__agency=user.agency))
        # Admin sees all
        
        return queryset
    
    def perform_create(self, serializer):
        """Create interaction with proper agent assignment."""
        client_id = self.request.data.get('client_id')
        agent_id = self.request.data.get('agent_id')
        
        # Validate client and agent
        try:
            client = User.objects.get(id=client_id, role='client')
            agent = User.objects.get(id=agent_id, role='agent')
        except User.DoesNotExist:
            raise serializers.ValidationError("Client ou agent introuvable.")
        
        # Ensure agent is from same agency
        if client.agency != agent.agency:
            raise serializers.ValidationError("L'agent doit appartenir à la même agence que le client.")
        
        return ClientInteraction.objects.create(
            client=client, agent=agent, **serializer.validated_data
        )
    
    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated])
    def complete(self, request, pk=None):
        """Mark interaction as completed with outcome."""
        try:
            interaction = self.get_object()
            outcome = request.data.get('outcome')
            notes = request.data.get('notes', '')
            
            if not outcome:
                return Response(
                    {'error': 'Le résultat est requis.'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            interaction.complete_interaction(outcome, notes)
            
            serializer = self.get_serializer(interaction)
            return Response(serializer.data)
            
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
    
    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated])
    def schedule_follow_up(self, request, pk=None):
        """Schedule a follow-up interaction."""
        try:
            interaction = self.get_object()
            follow_up_date = request.data.get('follow_up_date')
            notes = request.data.get('notes', '')
            
            if not follow_up_date:
                return Response(
                    {'error': 'La date de suivi est requise.'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            interaction.schedule_follow_up(follow_up_date, notes)
            
            serializer = self.get_serializer(interaction)
            return Response(serializer.data)
            
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)


class LeadViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing leads.
    """
    queryset = Lead.objects.select_related('assigned_agent', 'agency')
    serializer_class = LeadSerializer
    permission_classes = [permissions.IsAuthenticated, CanManageLeads]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = {
        'source': ['exact'],
        'status': ['exact'],
        'qualification': ['exact'],
        'agency': ['exact'],
        'assigned_agent': ['exact'],
        'score': ['gte', 'lte'],
        'created_at': ['gte', 'lte']
    }
    search_fields = ['first_name', 'last_name', 'email', 'phone', 'company']
    ordering_fields = ['score', 'urgency_score', 'created_at', 'next_action_date']
    ordering = ['-score', '-created_at']
    
    def get_queryset(self):
        """Filter queryset based on user role and permissions."""
        user = self.request.user
        queryset = super().get_queryset()
        
        if user.role == 'admin':
            # Admin can see all leads
            return queryset
        elif user.role == 'agent':
            # Agent can see leads for their agency
            agency = user.agency
            if agency:
                return queryset.filter(agency=agency)
            else:
                # Agent without agency sees no leads
                return queryset.none()
        
        return queryset.none()
    
    def get_permissions(self):
        """Get permissions for different actions."""
        if self.action == 'create':
            permission_classes = [permissions.IsAuthenticated, CanCreateLead]
        elif self.action == 'assign':
            permission_classes = [permissions.IsAuthenticated, CanAssignLeads]
        elif self.action == 'convert':
            permission_classes = [permissions.IsAuthenticated, CanConvertLead]
        else:
            permission_classes = [permissions.IsAuthenticated, CanManageLeads]
        
        return [permission() for permission in permission_classes]
    
    def perform_create(self, serializer):
        """Create lead and calculate initial score."""
        agency_id = self.request.data.get('agency_id')
        agency = Agency.objects.get(id=agency_id)
        
        lead = serializer.save(agency=agency)
        lead.calculate_score()
        lead.save()
        
        return lead
    
    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated, CanAssignLeads])
    def assign(self, request, pk=None):
        """Assign lead to an agent."""
        try:
            lead = self.get_object()
            agent_id = request.data.get('agent_id')
            
            if not agent_id:
                return Response(
                    {'error': 'ID agent requis.'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            try:
                agent = User.objects.get(id=agent_id, role='agent')
            except User.DoesNotExist:
                return Response(
                    {'error': 'Agent introuvable.'},
                    status=status.HTTP_400_BAD_REQUEST
            )
            
            lead.assign_to_agent(agent)
            
            serializer = self.get_serializer(lead)
            return Response(serializer.data)
            
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
    
    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated, CanConvertLead])
    def convert(self, request, pk=None):
        """Convert lead to client. Returns lead data + client_profile_id when converted."""
        try:
            lead = self.get_object()
            serializer = LeadConversionSerializer(lead, data=request.data, partial=True)
            
            if serializer.is_valid():
                serializer.save()
                lead.refresh_from_db()
                response_data = LeadSerializer(lead, context={'request': request}).data
                if lead.converted_to_client:
                    client_profile = ClientProfile.objects.filter(
                        user__email=lead.email, user__role='client'
                    ).first()
                    if client_profile:
                        response_data['client_profile_id'] = str(client_profile.id)
                return Response(response_data)
            else:
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
                
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
    
    @action(detail=False, methods=['post'], permission_classes=[permissions.IsAuthenticated, CanManageLeads])
    def auto_assign(self, request):
        """Automatically assign unassigned leads to agents."""
        try:
            agency_id = request.data.get('agency_id')
            if not agency_id:
                return Response(
                    {'error': 'ID agence requis.'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            agency = Agency.objects.get(id=agency_id)
            assigned_count = auto_assign_leads_to_agents(agency)
            
            return Response({
                'message': f'{assigned_count} leads assignés automatiquement.',
                'assigned_count': assigned_count
            })
            
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
    
    @action(detail=False, methods=['get'], permission_classes=[permissions.IsAuthenticated, CanViewDashboard])
    def statistics(self, request):
        """Get lead statistics."""
        queryset = self.get_queryset()
        
        stats = {
            'total_leads': queryset.count(),
            'by_status': dict(queryset.values_list('status').annotate(count=Count('id')).values_list('status', 'count')),
            'by_source': dict(queryset.values_list('source').annotate(count=Count('id')).values_list('source', 'count')),
            'by_qualification': dict(queryset.values_list('qualification').annotate(count=Count('id')).values_list('qualification', 'count')),
            'avg_score': queryset.aggregate(avg_score=Avg('score'))['avg_score'] or 0,
            'conversion_rate': 0  # Calculate based on won leads
        }
        
        # Calculate conversion rate
        won_leads = queryset.filter(status='won').count()
        if queryset.count() > 0:
            stats['conversion_rate'] = (won_leads / queryset.count()) * 100
        
        return Response(stats)
    
    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated, CanManageLeads])
    def qualify(self, request, pk=None):
        """Qualify a lead (hot, warm, cold, unqualified)."""
        try:
            lead = self.get_object()
            qualification = request.data.get('qualification')
            notes = request.data.get('notes', '')
            
            if not qualification:
                return Response(
                    {'error': 'Qualification requise (hot, warm, cold, unqualified).'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            valid_qualifications = ['hot', 'warm', 'cold', 'unqualified']
            if qualification not in valid_qualifications:
                return Response(
                    {'error': f'Qualification invalide. Valeurs acceptées: {", ".join(valid_qualifications)}'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Update qualification
            lead.qualification = qualification
            if notes:
                lead.notes = f"{lead.notes}\n\n[Qualification] {notes}" if lead.notes else f"[Qualification] {notes}"
            
            # Recalculate score based on qualification
            lead.calculate_score()
            
            # Adjust score based on qualification
            qualification_scores = {'hot': 20, 'warm': 10, 'cold': 5, 'unqualified': 0}
            lead.score = min(lead.score + qualification_scores.get(qualification, 0), 100)
            
            lead.save()
            
            from apps.core.activity import log_activity

            log_activity(
                user=request.user,
                component='clients',
                action='LEAD_QUALIFIED',
                message=f'Lead qualifié: {qualification}',
                metadata={
                    'object_type': 'Lead',
                    'object_id': str(lead.id),
                    'qualification': qualification,
                    'score': lead.score,
                },
                request=request,
            )
            
            serializer = self.get_serializer(lead)
            return Response(serializer.data)
            
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
    
    @action(detail=False, methods=['get'], permission_classes=[permissions.IsAuthenticated, CanViewDashboard])
    def pipeline(self, request):
        """Get leads organized by pipeline stage (Kanban view)."""
        try:
            queryset = self.get_queryset()
            
            # Organize leads by status (pipeline stages)
            pipeline = {
                'new': {
                    'title': 'Nouveaux',
                    'leads': []
                },
                'contacted': {
                    'title': 'Contactés',
                    'leads': []
                },
                'qualified': {
                    'title': 'Qualifiés',
                    'leads': []
                },
                'proposal_sent': {
                    'title': 'Proposition envoyée',
                    'leads': []
                },
                'negotiation': {
                    'title': 'En négociation',
                    'leads': []
                },
                'won': {
                    'title': 'Convertis',
                    'leads': []
                },
                'lost': {
                    'title': 'Perdus',
                    'leads': []
                }
            }
            
            # Get leads for each stage
            for status_key in pipeline.keys():
                stage_leads = queryset.filter(status=status_key).order_by('-score', '-created_at')
                serializer = self.get_serializer(stage_leads, many=True)
                pipeline[status_key]['leads'] = serializer.data
                pipeline[status_key]['count'] = stage_leads.count()
            
            # Calculate pipeline metrics
            total_leads = queryset.count()
            total_value = 0  # Could calculate based on budget_range if available
            conversion_rate = 0
            if total_leads > 0:
                won_count = queryset.filter(status='won').count()
                conversion_rate = (won_count / total_leads) * 100
            
            return Response({
                'pipeline': pipeline,
                'metrics': {
                    'total_leads': total_leads,
                    'conversion_rate': round(conversion_rate, 2),
                    'total_value': total_value
                }
            })
            
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)


class PropertyMatchingViewSet(viewsets.ViewSet):
    """
    ViewSet for property matching operations.
    """
    permission_classes = [permissions.IsAuthenticated, CanAccessMatchingResults]
    
    @action(detail=False, methods=['post'], permission_classes=[permissions.IsAuthenticated])
    def find_matches(self, request):
        """Find matching properties for a client."""
        client_id = request.data.get('client_id')
        limit = request.data.get('limit', 10)
        min_score = request.data.get('min_score', 30)
        
        try:
            client = User.objects.get(id=client_id, role='client')
            if not hasattr(client, 'client_profile'):
                return Response(
                    {'error': 'Profil client non trouvé.'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            matcher = PropertyMatcher(client.client_profile)
            properties = matcher.find_matches(limit=limit, min_score=min_score)
            
            # Create response with detailed information
            results = []
            for property_obj in properties:
                score = matcher.calculate_match_score(property_obj)
                explanation = matcher.get_match_explanation(property_obj)
                
                results.append({
                    'property': property_obj,
                    'match_score': score,
                    'match_explanation': explanation,
                    'recommendations': explanation.get('recommendations', [])
                })
            
            # Serialize results
            serialized_results = []
            from .serializers import PropertyListSerializer
            for result in results:
                property_data = PropertyListSerializer(result['property']).data
                property_data.update({
                    'match_score': result['match_score'],
                    'match_explanation': result['match_explanation'],
                    'recommendations': result['recommendations']
                })
                serialized_results.append(property_data)
            
            return Response(serialized_results)
            
        except User.DoesNotExist:
            return Response(
                {'error': 'Client introuvable.'},
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
    
    @action(detail=False, methods=['post'], permission_classes=[permissions.IsAuthenticated])
    def get_match_score(self, request):
        """Get match score for a specific client-property pair."""
        client_id = request.data.get('client_id')
        property_id = request.data.get('property_id')
        
        try:
            client = User.objects.get(id=client_id, role='client')
            property_obj = Property.objects.get(id=property_id)
            
            if not hasattr(client, 'client_profile'):
                return Response(
                    {'error': 'Profil client non trouvé.'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            matcher = PropertyMatcher(client.client_profile)
            score = matcher.calculate_match_score(property_obj)
            explanation = matcher.get_match_explanation(property_obj)
            
            return Response({
                'match_score': score,
                'match_explanation': explanation
            })
            
        except (User.DoesNotExist, Property.DoesNotExist):
            return Response(
                {'error': 'Client ou propriété introuvable.'},
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)


class DashboardViewSet(viewsets.ViewSet):
    """
    ViewSet for dashboard data.
    """
    permission_classes = [permissions.IsAuthenticated, CanViewDashboard]
    
    @action(detail=False, methods=['get'])
    def client_dashboard(self, request):
        """Get client dashboard data."""
        if request.user.role != 'client':
            return Response(
                {'error': 'Seuls les clients peuvent accéder à ce tableau de bord.'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        try:
            client_profile = request.user.client_profile
            
            # Get recent interactions
            recent_interactions = ClientInteraction.objects.filter(
                client=request.user
            ).order_by('-created_at')[:5]
            
            # Get upcoming visits
            upcoming_visits = PropertyInterest.objects.filter(
                client=request.user,
                interaction_type='visit_scheduled'
            ).order_by('interaction_date')[:5]
            
            # Get matching properties
            matching_properties = client_profile.get_matching_properties(limit=5)
            
            dashboard_data = {
                'profile': ClientProfileSerializer(client_profile).data,
                'recent_interactions': ClientInteractionSerializer(recent_interactions, many=True).data,
                'upcoming_visits': PropertyInterestSerializer(upcoming_visits, many=True).data,
                'matching_properties': matching_properties,
                'activity_summary': {
                    'total_interests': client_profile.total_properties_viewed,
                    'total_inquiries': client_profile.total_inquiries_made,
                    'conversion_score': client_profile.conversion_score
                }
            }
            
            return Response(dashboard_data)
            
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
    
    @action(detail=False, methods=['get'])
    def agent_dashboard(self, request):
        """Get agent dashboard data."""
        if request.user.role not in ['agent', 'admin']:
            return Response(
                {'error': 'Seuls les agents et administrateurs peuvent accéder à ce tableau de bord.'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        try:
            # Get clients for this agent/agency
            if request.user.role == 'admin':
                clients = User.objects.filter(role='client')
            else:
                clients = User.objects.filter(role='client', profile__agency=request.user.agency)
            
            # Get leads
            if request.user.role == 'admin':
                leads = Lead.objects.all()
            else:
                leads = Lead.objects.filter(agency=request.user.agency)
            
            # Get recent interactions
            recent_interactions = ClientInteraction.objects.filter(
                agent=request.user
            ).order_by('-created_at')[:5]
            
            # Get upcoming visits
            upcoming_visits = PropertyInterest.objects.filter(
                agent=request.user,
                interaction_type='visit_scheduled'
            ).order_by('interaction_date')[:5]
            
            # Performance statistics
            performance_stats = {
                'total_clients': clients.count(),
                'pending_leads': leads.filter(status__in=['new', 'contacted']).count(),
                'completed_interactions': ClientInteraction.objects.filter(
                    agent=request.user, status='completed'
                ).count(),
                'avg_client_satisfaction': 0  # Placeholder for future implementation
            }
            
            dashboard_data = {
                'profile': {
                    'agent_name': request.user.get_full_name(),
                    'agency': request.user.agency.name,
                    'role': request.user.role
                },
                'recent_interactions': ClientInteractionSerializer(recent_interactions, many=True).data,
                'upcoming_visits': PropertyInterestSerializer(upcoming_visits, many=True).data,
                'performance_stats': performance_stats
            }
            
            return Response(dashboard_data)
            
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)


class ClientNoteViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing client notes (Phase 1 - Post-deployment).
    Only accessible by agents and admins.
    """
    
    queryset = ClientNote.objects.select_related('client_profile__user', 'author')
    serializer_class = ClientNoteSerializer
    permission_classes = [permissions.IsAuthenticated, IsAgentOrAdmin]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = {
        'client_profile': ['exact'],
        'author': ['exact'],
        'note_type': ['exact'],
        'is_important': ['exact'],
        'is_pinned': ['exact'],
    }
    search_fields = ['title', 'content']
    ordering_fields = ['created_at', 'updated_at', 'is_important', 'is_pinned']
    ordering = ['-is_pinned', '-is_important', '-created_at']
    
    def get_queryset(self):
        """Filter notes based on user permissions."""
        user = self.request.user
        queryset = super().get_queryset()
        
        if user.is_staff or user.is_superuser:
            return queryset
        
        # Agents see notes for their agency's clients
        if user.role in ['agent', 'manager']:
            user_agency = getattr(user.profile, 'agency', None) if hasattr(user, 'profile') else None
            if user_agency:
                return queryset.filter(
                    client_profile__user__profile__agency=user_agency
                )
        
        return queryset.none()
    
    def get_serializer_class(self):
        """Return appropriate serializer."""
        if self.action == 'create':
            return ClientNoteCreateSerializer
        return ClientNoteSerializer
    
    @action(detail=True, methods=['post'], url_path='toggle-pin')
    def toggle_pin(self, request, pk=None):
        """Pin/unpin a note."""
        note = self.get_object()
        note.is_pinned = not note.is_pinned
        note.save(update_fields=['is_pinned'])
        
        return Response({
            'is_pinned': note.is_pinned,
            'message': 'Note épinglée' if note.is_pinned else 'Note désépinglée'
        })
    
    @action(detail=True, methods=['post'], url_path='toggle-important')
    def toggle_important(self, request, pk=None):
        """Mark/unmark note as important."""
        note = self.get_object()
        note.is_important = not note.is_important
        note.save(update_fields=['is_important'])
        
        return Response({
            'is_important': note.is_important,
            'message': 'Note marquée importante' if note.is_important else 'Note démarquée'
        })


class ReportingViewSet(viewsets.ViewSet):
    """
    ViewSet for generating and exporting reports (Phase 1 - Post-deployment).
    """
    
    permission_classes = [permissions.IsAuthenticated, IsAgentOrAdmin]
    
    @action(detail=False, methods=['get'], url_path='client-pdf/(?P<client_id>[^/.]+)')
    def client_pdf(self, request, client_id=None):
        """
        Generate PDF report for a specific client.
        
        Query params:
            - include_interactions: bool (default: true)
            - include_notes: bool (default: true)
        """
        include_interactions = request.query_params.get('include_interactions', 'true').lower() == 'true'
        include_notes = request.query_params.get('include_notes', 'true').lower() == 'true'
        
        try:
            # Generate PDF
            pdf_buffer = ReportingService.generate_client_report_pdf(
                client_id=client_id,
                include_interactions=include_interactions,
                include_notes=include_notes
            )
            
            # Get client name for filename
            try:
                client_profile = ClientProfile.objects.select_related('user').get(id=client_id)
                filename = f"rapport_client_{client_profile.user.get_full_name().replace(' ', '_')}_{datetime.now().strftime('%Y%m%d')}.pdf"
            except ClientProfile.DoesNotExist:
                filename = f"rapport_client_{client_id}_{datetime.now().strftime('%Y%m%d')}.pdf"
            
            # Return PDF response
            response = HttpResponse(pdf_buffer.read(), content_type='application/pdf')
            response['Content-Disposition'] = f'attachment; filename="{filename}"'
            return response
            
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
    
    @action(detail=False, methods=['get'], url_path='agent-performance/(?P<agent_id>[^/.]+)')
    def agent_performance(self, request, agent_id=None):
        """
        Generate Excel report for agent performance.
        
        Query params:
            - start_date: YYYY-MM-DD
            - end_date: YYYY-MM-DD
        """
        # Parse dates
        start_date_str = request.query_params.get('start_date')
        end_date_str = request.query_params.get('end_date')
        
        start_date = None
        end_date = None
        
        if start_date_str:
            try:
                start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
            except ValueError:
                return Response({'error': 'Invalid start_date format. Use YYYY-MM-DD'}, 
                              status=status.HTTP_400_BAD_REQUEST)
        
        if end_date_str:
            try:
                end_date = datetime.strptime(end_date_str, '%Y-%m-%d')
            except ValueError:
                return Response({'error': 'Invalid end_date format. Use YYYY-MM-DD'}, 
                              status=status.HTTP_400_BAD_REQUEST)
        
        try:
            # Generate Excel
            excel_buffer = ReportingService.generate_agent_performance_excel(
                agent_id=agent_id,
                start_date=start_date,
                end_date=end_date
            )
            
            # Get agent name for filename
            try:
                agent = User.objects.get(id=agent_id)
                filename = f"performance_agent_{agent.get_full_name().replace(' ', '_')}_{datetime.now().strftime('%Y%m%d')}.xlsx"
            except User.DoesNotExist:
                filename = f"performance_agent_{agent_id}_{datetime.now().strftime('%Y%m%d')}.xlsx"
            
            # Return Excel response
            response = HttpResponse(
                excel_buffer.read(),
                content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            )
            response['Content-Disposition'] = f'attachment; filename="{filename}"'
            return response
            
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
    
    @action(detail=False, methods=['get'], url_path='agency-overview/(?P<agency_id>[^/.]+)')
    def agency_overview(self, request, agency_id=None):
        """
        Generate Excel report for agency-wide overview.
        
        Query params:
            - start_date: YYYY-MM-DD
            - end_date: YYYY-MM-DD
        """
        # Parse dates
        start_date_str = request.query_params.get('start_date')
        end_date_str = request.query_params.get('end_date')
        
        start_date = None
        end_date = None
        
        if start_date_str:
            try:
                start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
            except ValueError:
                return Response({'error': 'Invalid start_date format. Use YYYY-MM-DD'}, 
                              status=status.HTTP_400_BAD_REQUEST)
        
        if end_date_str:
            try:
                end_date = datetime.strptime(end_date_str, '%Y-%m-%d')
            except ValueError:
                return Response({'error': 'Invalid end_date format. Use YYYY-MM-DD'}, 
                              status=status.HTTP_400_BAD_REQUEST)
        
        try:
            # Generate Excel
            excel_buffer = ReportingService.generate_agency_overview_excel(
                agency_id=agency_id,
                start_date=start_date,
                end_date=end_date
            )
            
            # Get agency name for filename
            try:
                agency = Agency.objects.get(id=agency_id)
                filename = f"vue_agence_{agency.name.replace(' ', '_')}_{datetime.now().strftime('%Y%m%d')}.xlsx"
            except Agency.DoesNotExist:
                filename = f"vue_agence_{agency_id}_{datetime.now().strftime('%Y%m%d')}.xlsx"
            
            # Return Excel response
            response = HttpResponse(
                excel_buffer.read(),
                content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            )
            response['Content-Disposition'] = f'attachment; filename="{filename}"'
            return response
            
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)


class CrmAnalyticsView(APIView):
    """Analytics agrégées pour le tableau de bord agent (mobile)."""

    permission_classes = [permissions.IsAuthenticated, IsAgentOrAdmin]

    STATUS_LABELS = {
        'prospect': 'Prospects',
        'active': 'Actifs',
        'client': 'Clients',
        'inactive': 'Inactifs',
    }

    INTERACTION_LABELS = {
        'call': 'Appel',
        'email': 'Email',
        'visit': 'Visite',
        'meeting': 'Réunion',
        'sms': 'SMS',
        'whatsapp': 'WhatsApp',
        'note': 'Note',
    }

    def _clients_for_agent(self, user):
        """ClientProfile n'a pas assigned_agent : clients liés via interactions ou réservations."""
        interaction_user_ids = ClientInteraction.objects.filter(
            agent=user
        ).values_list('client_id', flat=True)
        reservation_profile_ids = Reservation.objects.filter(
            assigned_agent=user,
            client_profile_id__isnull=False,
        ).values_list('client_profile_id', flat=True)
        return ClientProfile.objects.filter(
            Q(user_id__in=interaction_user_ids) | Q(id__in=reservation_profile_ids)
        ).distinct()

    def _clients_over_time(self, clients_qs, period, since, labels):
        data = []
        now = timezone.now()
        if period == 'week':
            for i in range(len(labels)):
                day = (now - timedelta(days=len(labels) - 1 - i)).date()
                data.append(clients_qs.filter(created_at__date=day).count())
        elif period == 'year':
            ref = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            for i in range(len(labels)):
                m = ref.month - (len(labels) - 1 - i)
                y = ref.year
                while m < 1:
                    m += 12
                    y -= 1
                month_start = ref.replace(year=y, month=m, day=1)
                if m == 12:
                    month_end = month_start.replace(year=y + 1, month=1, day=1)
                else:
                    month_end = month_start.replace(month=m + 1, day=1)
                data.append(
                    clients_qs.filter(
                        created_at__gte=month_start,
                        created_at__lt=month_end,
                    ).count()
                )
        else:
            for i in range(len(labels)):
                week_start = since + timedelta(days=7 * i)
                week_end = week_start + timedelta(days=7)
                data.append(
                    clients_qs.filter(
                        created_at__gte=week_start,
                        created_at__lt=week_end,
                    ).count()
                )
        return data

    def get(self, request):
        try:
            return self._build_analytics_response(request)
        except Exception as e:
            import logging
            logging.getLogger(__name__).exception('Erreur CRM analytics')
            return Response(
                {'error': 'Impossible de charger les analytics.', 'detail': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    def _build_analytics_response(self, request):
        period = request.query_params.get('period', 'month')
        now = timezone.now()
        if period == 'week':
            since = now - timedelta(days=6)
            labels = ['Lun', 'Mar', 'Mer', 'Jeu', 'Ven', 'Sam', 'Dim']
        elif period == 'year':
            since = now - timedelta(days=365)
            labels = ['Jan', 'Fév', 'Mar', 'Avr', 'Mai', 'Juin', 'Jul', 'Aoû', 'Sep', 'Oct', 'Nov', 'Déc']
        else:
            since = now - timedelta(days=28)
            labels = ['S1', 'S2', 'S3', 'S4']

        clients_qs = ClientProfile.objects.all()
        leads_qs = Lead.objects.all()
        interactions_qs = ClientInteraction.objects.filter(created_at__gte=since)
        reservations_qs = Reservation.objects.filter(created_at__gte=since)

        user = request.user
        role = getattr(user, 'role', None)
        is_agent = role == 'agent'
        if is_agent:
            clients_qs = self._clients_for_agent(user)
            leads_qs = leads_qs.filter(assigned_agent=user)
            interactions_qs = interactions_qs.filter(agent=user)
            reservations_qs = reservations_qs.filter(assigned_agent=user)

        clients_by_status = clients_qs.values('status').annotate(count=Count('id'))
        status_colors = {
            'prospect': '#3b82f6',
            'active': '#10b981',
            'client': '#D95724',
            'inactive': '#6b7280',
        }
        clients_by_status_chart = [
            {
                'name': self.STATUS_LABELS.get(row['status'], row['status'] or 'Autre'),
                'population': row['count'],
                'color': status_colors.get(row['status'], '#94a3b8'),
                'legendFontColor': '#384242',
                'legendFontSize': 12,
            }
            for row in clients_by_status
            if row['count'] > 0
        ]

        interaction_types = interactions_qs.values('interaction_type').annotate(count=Count('id'))
        type_labels = []
        type_data = []
        for row in interaction_types[:6]:
            key = row['interaction_type'] or 'autre'
            type_labels.append(self.INTERACTION_LABELS.get(key, key.capitalize()))
            type_data.append(row['count'])

        total_leads = leads_qs.count()
        qualified = leads_qs.filter(qualification__in=['hot', 'warm']).count()
        converted = clients_qs.filter(status='client').count()
        active_clients = clients_qs.filter(status='active').count()
        conversion_rate = round((converted / total_leads * 100), 1) if total_leads > 0 else 0.0

        commissions_summary = {}
        if is_agent:
            try:
                from apps.commissions.models import Commission
                comm_qs = Commission.objects.filter(agent=user)
                commissions_summary = {
                    'total_amount': float(
                        comm_qs.aggregate(t=Sum('commission_amount'))['t'] or 0
                    ),
                    'pending_amount': float(
                        comm_qs.filter(status='pending').aggregate(t=Sum('commission_amount'))['t'] or 0
                    ),
                    'paid_amount': float(
                        comm_qs.filter(status='paid').aggregate(t=Sum('commission_amount'))['t'] or 0
                    ),
                }
            except Exception:
                commissions_summary = {}

        return Response({
            'clientsOverTime': {
                'labels': labels,
                'data': self._clients_over_time(clients_qs, period, since, labels),
            },
            'interactionsByType': {
                'labels': type_labels or ['—'],
                'data': type_data or [0],
            },
            'conversionFunnel': {
                'labels': ['Leads', 'Qualifiés', 'Actifs', 'Convertis'],
                'data': [
                    total_leads,
                    qualified,
                    active_clients,
                    converted,
                ],
            },
            'clientsByStatus': clients_by_status_chart or [
                {
                    'name': 'Aucun client',
                    'population': 1,
                    'color': '#e5e7eb',
                    'legendFontColor': '#384242',
                    'legendFontSize': 12,
                }
            ],
            'summary': {
                'total_clients': clients_qs.count(),
                'active_clients': active_clients,
                'total_leads': total_leads,
                'total_interactions': interactions_qs.count(),
                'conversion_rate': conversion_rate,
                'reservations': {
                    'total': reservations_qs.count(),
                    'completed': reservations_qs.filter(status='completed').count(),
                    'pending': reservations_qs.filter(status='pending').count(),
                    'confirmed': reservations_qs.filter(status='confirmed').count(),
                },
                'commissions': commissions_summary,
            },
        })