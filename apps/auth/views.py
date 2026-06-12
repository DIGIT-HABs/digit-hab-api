"""
Views for authentication app.
"""

from django.contrib.auth import get_user_model, logout
from django.db.models import Q
from django.contrib.auth.tokens import default_token_generator
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.utils.decorators import method_decorator
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.utils.encoding import force_bytes, force_str
from rest_framework import status, permissions, generics, serializers as drf_serializers
from rest_framework.decorators import api_view, permission_classes, action
from rest_framework.mixins import ListModelMixin, CreateModelMixin
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.parsers import JSONParser, FormParser, MultiPartParser
from rest_framework.viewsets import ModelViewSet, ReadOnlyModelViewSet
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from rest_framework_simplejwt.tokens import RefreshToken
from drf_spectacular.utils import extend_schema, extend_schema_view

from .models import User, Agency, UserProfile
from .serializers import (
    UserSerializer, UserCreateSerializer, UserProfileSerializer,
    AgencySerializer, AgencyCreateSerializer, AgencyUpdateSerializer,
    LoginSerializer, TokenObtainPairSerializer,
    PasswordChangeSerializer, PasswordResetSerializer, PasswordResetConfirmSerializer,
    LogoutResponseSerializer, TokenVerifyResponseSerializer, RefreshTokenSerializer,
    GoogleAuthSerializer, AppleAuthSerializer, RegisterSerializer,
    AgentCreateSerializer, AgencyWithAgentRegisterSerializer,
)
from .permissions import IsOwnerOrReadOnly, IsAdminUser, IsOwner

UserModel = get_user_model()


@extend_schema_view(
    list=extend_schema(
        summary="Liste des utilisateurs",
        description="Retourne la liste de tous les utilisateurs accessibles."
    ),
    retrieve=extend_schema(
        summary="Détail d'un utilisateur",
        description="Retourne les détails d'un utilisateur spécifique."
    ),
    create=extend_schema(
        summary="Création d'un utilisateur",
        description="Crée un nouvel utilisateur dans le système."
    ),
    update=extend_schema(
        summary="Mise à jour d'un utilisateur",
        description="Met à jour toutes les données d'un utilisateur."
    ),
    partial_update=extend_schema(
        summary="Mise à jour partielle d'un utilisateur",
        description="Met à jour partiellement les données d'un utilisateur."
    ),
    destroy=extend_schema(
        summary="Suppression d'un utilisateur",
        description="Supprime définitivement un utilisateur."
    )
)
class UserViewSet(ModelViewSet):
    """
    API endpoint for users management.
    
    - list: Get all users (admin only)
    - retrieve: Get user details
    - create: Create new user (admin only)
    - update: Update user (admin or self)
    - destroy: Delete user (admin only)
    """
    
    queryset = UserModel.objects.all()
    serializer_class = UserSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        """Return users based on permissions."""
        user = self.request.user
        if user.is_staff or user.is_superuser:
            return UserModel.objects.all()
        else:
            # Return only current user for non-admin users
            return UserModel.objects.filter(pk=user.pk)
    
    def get_serializer_class(self):
        """Return appropriate serializer."""
        if self.action == 'create':
            return UserCreateSerializer
        return UserSerializer
    
    def get_permissions(self):
        """Return permissions based on action."""
        if self.action == 'create':
            permission_classes = [IsAuthenticated, IsAdminUser]
        elif self.action in ['update', 'partial_update', 'destroy']:
            permission_classes = [IsAuthenticated, IsOwnerOrReadOnly]
        else:
            permission_classes = [IsAuthenticated]
        
        return [permission() for permission in permission_classes]
    
    @action(detail=False, methods=['get'])
    def me(self, request):
        """Get current user profile."""
        serializer = self.get_serializer(request.user)
        return Response(serializer.data)
    
    @action(detail=False, methods=['post'])
    def change_password(self, request):
        """Change user password."""
        serializer = PasswordChangeSerializer(
            data=request.data,
            context={'request': request}
        )
        if serializer.is_valid():
            serializer.save()
            return Response(
                {"message": "Password changed successfully."},
                status=status.HTTP_200_OK
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    @action(detail=False, methods=['post'])
    def request_password_reset(self, request):
        """Request password reset."""
        import logging
        from django.conf import settings
        from django.core.mail import send_mail

        logger = logging.getLogger(__name__)
        serializer = PasswordResetSerializer(data=request.data)
        if serializer.is_valid():
            email = serializer.validated_data['email']
            user = UserModel.objects.get(email=email)
            token = default_token_generator.make_token(user)
            uid = urlsafe_base64_encode(force_bytes(user.pk))
            frontend = getattr(settings, 'FRONTEND_URL', 'https://api.digit-hab.wolofdigital.site')
            reset_link = f'{frontend}/reset-password?uid={uid}&token={token}'
            subject = 'Réinitialisation de votre mot de passe DIGIT-HAB'
            body = (
                f'Bonjour,\n\n'
                f'Pour réinitialiser votre mot de passe, utilisez ce lien :\n{reset_link}\n\n'
                f'Si vous n\'êtes pas à l\'origine de cette demande, ignorez ce message.'
            )
            if settings.EMAIL_HOST_USER:
                send_mail(subject, body, settings.EMAIL_HOST_USER, [email], fail_silently=False)
            else:
                logger.warning('Password reset (email non configuré): %s', reset_link)
            return Response(
                {"message": "Password reset email sent."},
                status=status.HTTP_200_OK
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    @action(detail=False, methods=['post'])
    def confirm_password_reset(self, request):
        """Confirm password reset."""
        serializer = PasswordResetConfirmSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(
                {"message": "Password reset successfully."},
                status=status.HTTP_200_OK
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class UserProfileViewSet(ReadOnlyModelViewSet):
    """
    API endpoint for user profiles.
    """
    
    serializer_class = UserProfileSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        user = self.request.user
        if user.is_superuser or getattr(user, 'role', None) == 'admin':
            return UserProfile.objects.select_related('user').all()
        return UserProfile.objects.select_related('user').filter(user=user)


@extend_schema_view(
    list=extend_schema(
        summary="Liste des agences",
        description="Retourne la liste de toutes les agences."
    ),
    retrieve=extend_schema(
        summary="Détail d'une agence",
        description="Retourne les détails d'une agence spécifique."
    )
)
class AgencyViewSet(ReadOnlyModelViewSet):
    """
    API endpoint for agencies (read-only for most users).
    """
    
    queryset = Agency.objects.all()
    serializer_class = AgencySerializer
    permission_classes = [IsAuthenticated]
    
    @action(detail=True, methods=['get', 'post'])
    def users(self, request, pk=None):
        """Get or manage agency users."""
        agency = self.get_object()
        if request.method == 'GET':
            users = UserModel.objects.filter(profile__agency=agency).select_related('profile')
            serializer = UserSerializer(users, many=True, context={'request': request})
            return Response(serializer.data)

        # POST would be for creating users for the agency
        # This is typically handled through the UserViewSet

    @action(detail=True, methods=['get'])
    def agents(self, request, pk=None):
        """Liste des agents immobiliers rattachés à l'agence."""
        agency = self.get_object()
        agents_qs = UserModel.objects.filter(
            profile__agency=agency,
            role='agent',
        ).select_related('profile').order_by('-date_joined')
        serializer = UserSerializer(agents_qs, many=True, context={'request': request})
        return Response(serializer.data)

    @action(
        detail=True,
        methods=['post'],
        url_path=r'agents/(?P<user_id>[^/.]+)/toggle-active',
    )
    def toggle_agent_active(self, request, pk=None, user_id=None):
        """Activer / désactiver un agent de l'agence (admin)."""
        actor = request.user
        if not (
            actor.is_staff
            or actor.is_superuser
            or getattr(actor, 'role', None) == 'admin'
        ):
            return Response(
                {'detail': 'Seuls les administrateurs peuvent modifier le statut des agents.'},
                status=status.HTTP_403_FORBIDDEN,
            )
        agency = self.get_object()
        agent = UserModel.objects.filter(
            pk=user_id,
            profile__agency=agency,
            role='agent',
        ).first()
        if not agent:
            return Response({'detail': 'Agent introuvable pour cette agence.'}, status=status.HTTP_404_NOT_FOUND)

        raw_active = request.data.get('is_active')
        if raw_active is None:
            agent.is_active = not agent.is_active
        else:
            agent.is_active = bool(raw_active)
        agent.save(update_fields=['is_active', 'updated_at'])
        serializer = UserSerializer(agent, context={'request': request})
        return Response(serializer.data)

    @action(detail=True, methods=['patch'])
    def update_settings(self, request, pk=None):
        """Mise à jour agence (admin)."""
        actor = request.user
        if not (
            actor.is_staff
            or actor.is_superuser
            or getattr(actor, 'role', None) == 'admin'
        ):
            return Response(
                {'detail': 'Seuls les administrateurs peuvent modifier une agence.'},
                status=status.HTTP_403_FORBIDDEN,
            )
        agency = self.get_object()
        serializer = AgencyUpdateSerializer(
            agency,
            data=request.data,
            partial=True,
            context={'request': request},
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        out = AgencySerializer(agency, context={'request': request})
        return Response(out.data)

    @action(detail=True, methods=['get'])
    def statistics(self, request, pk=None):
        """Get agency statistics."""
        agency = self.get_object()
        stats = {
            'total_users': agency.users.count(),
            'active_users': UserModel.objects.filter(profile__agency=agency, is_active=True).count(),
            'total_properties': agency.properties.count() if hasattr(agency, 'properties') else 0,
            'total_clients': agency.clients.count() if hasattr(agency, 'clients') else 0,
            'subscription_days_remaining': agency.get_subscription_days_remaining(),
            'subscription_active': agency.is_subscription_active(),
        }
        return Response(stats)

    @action(detail=False, methods=['get', 'patch'])
    def me(self, request):
        """Get or update current user's agency (for agents)."""
        if not hasattr(request.user, 'profile') or not getattr(request.user.profile, 'agency', None):
            return Response(
                {'detail': 'Vous n\'êtes pas rattaché à une agence.'},
                status=status.HTTP_404_NOT_FOUND
            )
        agency = request.user.profile.agency
        if request.method == 'GET':
            serializer = AgencySerializer(agency, context={'request': request})
            return Response(serializer.data)
        if request.method == 'PATCH':
            serializer = AgencyUpdateSerializer(agency, data=request.data, partial=True, context={'request': request})
            serializer.is_valid(raise_exception=True)
            serializer.save()
            # Return full agency with logo_url
            out = AgencySerializer(agency, context={'request': request})
            return Response(out.data)
        return Response(status=status.HTTP_405_METHOD_NOT_ALLOWED)


class AgencyCreateView(CreateModelMixin, generics.GenericAPIView):
    """
    API endpoint for creating agencies.
    """
    
    queryset = Agency.objects.all()
    serializer_class = AgencyCreateSerializer
    permission_classes = [AllowAny]  # Allow registration without authentication
    
    def post(self, request, *args, **kwargs):
        """Create new agency; return full agency with logo_url."""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        agency = serializer.save()
        out = AgencySerializer(agency, context={'request': request})
        return Response(out.data, status=status.HTTP_201_CREATED)


class AgencyWithAgentRegisterView(generics.GenericAPIView):
    """
    Inscription publique : agence + compte agent fondateur (sans connexion préalable).
    """

    permission_classes = [AllowAny]
    serializer_class = AgencyWithAgentRegisterSerializer

    @extend_schema(
        summary="Inscription agence + agent",
        description="Crée une agence et le compte agent du responsable, puis retourne les tokens JWT.",
    )
    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = serializer.save()
        agency = result['agency']
        user = result['user']
        refresh = RefreshToken.for_user(user)
        agency_data = AgencySerializer(agency, context={'request': request}).data
        return Response(
            {
                'message': 'Agence et compte agent créés avec succès.',
                'agency': agency_data,
                'user': {
                    'id': str(user.id),
                    'username': user.username,
                    'email': user.email,
                    'first_name': user.first_name,
                    'last_name': user.last_name,
                    'role': user.role,
                    'agency_id': str(agency.id),
                },
                'refresh': str(refresh),
                'access': str(refresh.access_token),
            },
            status=status.HTTP_201_CREATED,
        )


class CustomTokenObtainPairView(TokenObtainPairView):
    """
    Custom JWT token obtain view.
    """
    
    serializer_class = TokenObtainPairSerializer
    
    @extend_schema(
        summary="Connexion utilisateur",
        description="Obtenir les tokens JWT pour un utilisateur authentifié."
    )
    def post(self, request, *args, **kwargs):
        """Override to add custom response."""
        serializer = self.get_serializer(data=request.data)
        
        try:
            serializer.is_valid(raise_exception=True)
        except ValidationError as e:
            return Response(e.detail, status=status.HTTP_400_BAD_REQUEST)
        
        # Get the authenticated user
        user = serializer.validated_data['user']
        
        # Generate tokens
        refresh = serializer.get_token(user)
        
        # Update user activity
        if hasattr(user, 'update_last_activity') and callable(user.update_last_activity):
            try:
                user.update_last_activity()
            except:
                pass
        
        # Build response
        response_data = {
            'refresh': str(refresh),
            'access': str(refresh.access_token),
            'user': {
                'id': str(user.id),
                'username': user.username,
                'email': user.email,
                'first_name': user.first_name,
                'last_name': user.last_name,
                'role': getattr(user, 'role', 'client'),
                'is_verified': getattr(user, 'is_verified', True),
                'phone': getattr(user, 'phone', None),
            }
        }
        
        return Response(response_data, status=status.HTTP_200_OK)


class LogoutView(APIView):
    """
    API endpoint for user logout.
    """
    
    permission_classes = [IsAuthenticated]
    serializer_class = LogoutResponseSerializer
    
    @extend_schema(
        summary="Déconnexion utilisateur",
        description="Déconnecter l'utilisateur et invalider les tokens.",
        request=RefreshTokenSerializer,
        responses={200: LogoutResponseSerializer}
    )
    def post(self, request):
        """Blacklist the refresh token and logout."""
        try:
            refresh_token = request.data["refresh"]
            token = RefreshToken(refresh_token)
            token.blacklist()
        except Exception as e:
            return Response(
                {"error": "Invalid token"}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        return Response(
            {"message": "Successfully logged out."}, 
            status=status.HTTP_200_OK
        )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
@extend_schema(
    summary="Vérification du token",
    description="Vérifier la validité du token JWT.",
    responses={200: TokenVerifyResponseSerializer}
)
def verify_token(request):
    """
    Verify JWT token validity.
    """
    return Response({
        "valid": True,
        "user_id": request.user.id,
        "username": request.user.username,
        "is_staff": request.user.is_staff,
        "is_superuser": request.user.is_superuser,
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@extend_schema(
    summary="Actualisation du profil utilisateur",
    description="Actualiser les données du profil utilisateur.",
    request=UserSerializer,
    responses={200: UserSerializer}
)
def update_profile(request):
    """
    Update user profile.
    """
    user = request.user
    serializer = UserSerializer(user, data=request.data, partial=True)
    
    if serializer.is_valid():
        serializer.save()
        return Response(serializer.data, status=status.HTTP_200_OK)
    
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class UserListView(generics.ListAPIView):
    """
    Simple list view for users (admin only).
    """
    
    queryset = UserModel.objects.all()
    serializer_class = UserSerializer
    permission_classes = [IsAuthenticated, IsAdminUser]
    pagination_class = None  # Disable pagination for admin list


class UserDetailView(generics.RetrieveUpdateDestroyAPIView):
    """
    Detailed view for a specific user.
    """
    
    queryset = UserModel.objects.all()
    serializer_class = UserSerializer
    permission_classes = [IsAuthenticated, IsOwnerOrReadOnly]
    
    def get_serializer_class(self):
        """Return appropriate serializer for update."""
        if self.request.method in ['PUT', 'PATCH']:
            return UserCreateSerializer if self.request.user.is_staff else UserSerializer
        return UserSerializer


# ============================================
# OAuth Views (Google & Apple) - V2
# ============================================

class RegisterView(generics.CreateAPIView):
    """
    API endpoint for user registration with email.
    """
    
    queryset = UserModel.objects.all()
    serializer_class = RegisterSerializer
    permission_classes = [AllowAny]
    
    @extend_schema(
        summary="Inscription utilisateur",
        description="Créer un nouveau compte utilisateur avec email et mot de passe."
    )
    def post(self, request, *args, **kwargs):
        """Register new user."""
        serializer = self.get_serializer(data=request.data)
        if serializer.is_valid():
            user = serializer.save()
            
            # Generate tokens for the new user
            refresh = RefreshToken.for_user(user)
            
            return Response({
                'message': 'User registered successfully.',
                'user': {
                    'id': str(user.id),
                    'username': user.username,
                    'email': user.email,
                    'first_name': user.first_name,
                    'last_name': user.last_name,
                },
                'refresh': str(refresh),
                'access': str(refresh.access_token),
            }, status=status.HTTP_201_CREATED)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class CreateAgentView(APIView):
    """
    Création d'un compte agent (rattaché à l'agence de l'utilisateur ou à une agence fournie pour les admins).
    """
    permission_classes = [IsAuthenticated]
    serializer_class = AgentCreateSerializer

    def post(self, request):
        serializer = AgentCreateSerializer(data=request.data, context={'request': request})
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        try:
            user = serializer.save()
        except drf_serializers.ValidationError as e:
            return Response(e.detail, status=status.HTTP_400_BAD_REQUEST)
        return Response({
            'message': 'Agent créé avec succès.',
            'user': {
                'id': str(user.id),
                'username': user.username,
                'email': user.email,
                'first_name': user.first_name,
                'last_name': user.last_name,
                'role': user.role,
            },
        }, status=status.HTTP_201_CREATED)


class CurrentUserView(APIView):
    """
    API endpoint to get current authenticated user profile.
    """
    
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser, FormParser, MultiPartParser]

    def _serializer(self, request, partial=False):
        return UserSerializer(
            request.user,
            data=request.data,
            partial=partial,
            context={'request': request},
        )
    
    @extend_schema(
        summary="Profil utilisateur actuel",
        description="Retourne les informations du profil de l'utilisateur actuellement connecté.",
        responses={200: UserSerializer}
    )
    def get(self, request):
        """Get current user profile."""
        serializer = UserSerializer(request.user, context={'request': request})
        return Response(serializer.data)
    
    @extend_schema(
        summary="Mise à jour du profil",
        description="Met à jour les informations du profil de l'utilisateur connecté.",
        request=UserSerializer,
        responses={200: UserSerializer}
    )
    def put(self, request):
        """Update current user profile."""
        serializer = self._serializer(request, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    @extend_schema(
        summary="Mise à jour partielle du profil",
        description="Met à jour partiellement les informations du profil de l'utilisateur connecté.",
        request=UserSerializer,
        responses={200: UserSerializer}
    )
    def patch(self, request):
        """Partially update current user profile."""
        serializer = self._serializer(request, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class GoogleAuthView(APIView):
    """
    API endpoint for Google OAuth authentication.
    """
    
    permission_classes = [AllowAny]
    
    @extend_schema(
        summary="Connexion Google OAuth",
        description="Authentification via Google Sign-In.",
        request=GoogleAuthSerializer,
        responses={200: TokenObtainPairSerializer}
    )
    def post(self, request):
        """Authenticate with Google."""
        serializer = GoogleAuthSerializer(data=request.data)
        
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            # Get or create user from Google data
            user = serializer.create_or_get_user(serializer.validated_data)
            
            # Generate JWT tokens
            refresh = RefreshToken.for_user(user)
            
            # Add custom claims
            refresh['user_id'] = str(user.id)
            refresh['username'] = user.username
            refresh['email'] = user.email
            refresh['role'] = user.role if hasattr(user, 'role') else 'client'
            
            return Response({
                'message': 'Successfully authenticated with Google.',
                'refresh': str(refresh),
                'access': str(refresh.access_token),
                'user': {
                    'id': str(user.id),
                    'username': user.username,
                    'email': user.email,
                    'first_name': user.first_name,
                    'last_name': user.last_name,
                    'role': user.role if hasattr(user, 'role') else 'client',
                }
            }, status=status.HTTP_200_OK)
        
        except Exception as e:
            return Response({
                'error': 'Google authentication failed.',
                'detail': str(e)
            }, status=status.HTTP_400_BAD_REQUEST)


class AppleAuthView(APIView):
    """
    API endpoint for Apple Sign In authentication.
    """
    
    permission_classes = [AllowAny]
    
    @extend_schema(
        summary="Connexion Apple Sign In",
        description="Authentification via Apple Sign In.",
        request=AppleAuthSerializer,
        responses={200: TokenObtainPairSerializer}
    )
    def post(self, request):
        """Authenticate with Apple."""
        serializer = AppleAuthSerializer(data=request.data)
        
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            # Get or create user from Apple data
            user = serializer.create_or_get_user(serializer.validated_data)
            
            # Generate JWT tokens
            refresh = RefreshToken.for_user(user)
            
            # Add custom claims
            refresh['user_id'] = str(user.id)
            refresh['username'] = user.username
            refresh['email'] = user.email
            refresh['role'] = user.role if hasattr(user, 'role') else 'client'
            
            return Response({
                'message': 'Successfully authenticated with Apple.',
                'refresh': str(refresh),
                'access': str(refresh.access_token),
                'user': {
                    'id': str(user.id),
                    'username': user.username,
                    'email': user.email,
                    'first_name': user.first_name,
                    'last_name': user.last_name,
                    'role': user.role if hasattr(user, 'role') else 'client',
                }
            }, status=status.HTTP_200_OK)
        
        except Exception as e:
            return Response({
                'error': 'Apple authentication failed.',
                'detail': str(e)
            }, status=status.HTTP_400_BAD_REQUEST)


class AdminAgentsListView(APIView):
    """Liste de tous les agents immobiliers (admin plateforme)."""

    permission_classes = [IsAuthenticated]

    @extend_schema(summary="Liste globale des agents (admin)")
    def get(self, request):
        from apps.core.user_roles import is_platform_admin
        if not is_platform_admin(request.user):
            return Response(
                {'detail': 'Accès réservé aux administrateurs plateforme.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        qs = UserModel.objects.filter(role='agent').select_related('profile__agency')
        agency_id = request.query_params.get('agency')
        if agency_id:
            qs = qs.filter(profile__agency_id=agency_id)
        is_active = request.query_params.get('is_active')
        if is_active is not None:
            qs = qs.filter(is_active=is_active.lower() in ('true', '1', 'yes'))

        search = (request.query_params.get('search') or '').strip()
        if search:
            qs = qs.filter(
                Q(email__icontains=search)
                | Q(first_name__icontains=search)
                | Q(last_name__icontains=search)
                | Q(username__icontains=search)
            )

        serializer = UserSerializer(
            qs.order_by('-date_joined'),
            many=True,
            context={'request': request},
        )
        return Response(serializer.data)


class AdminAgentDetailView(APIView):
    """Fiche agent + statistiques (admin plateforme)."""

    permission_classes = [IsAuthenticated]

    @extend_schema(summary="Détail agent et statistiques (admin)")
    def get(self, request, agent_id):
        from django.db.models import Sum, Count
        from apps.core.user_roles import is_platform_admin
        from apps.reservations.models import Reservation
        from apps.commissions.models import Commission
        from apps.crm.models import Lead

        if not is_platform_admin(request.user):
            return Response(
                {'detail': 'Accès réservé aux administrateurs plateforme.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        agent = (
            UserModel.objects.filter(role='agent', id=agent_id)
            .select_related('profile__agency')
            .first()
        )
        if not agent:
            return Response({'detail': 'Agent introuvable.'}, status=status.HTTP_404_NOT_FOUND)

        reservations_qs = Reservation.objects.filter(assigned_agent=agent)
        reservations_by_status = {
            row['status']: row['count']
            for row in reservations_qs.values('status').annotate(count=Count('id'))
        }
        revenue = reservations_qs.filter(payment_status='paid').aggregate(
            total=Sum('amount')
        )['total'] or 0

        leads_qs = Lead.objects.filter(assigned_agent=agent)
        commissions_qs = Commission.objects.filter(agent=agent)

        client_ids = reservations_qs.filter(
            client_profile__isnull=False
        ).values_list('client_profile_id', flat=True).distinct()

        commissions_pending = commissions_qs.filter(status='pending').aggregate(
            amount=Sum('commission_amount'),
        )
        commissions_paid = commissions_qs.filter(status='paid').aggregate(
            amount=Sum('commission_amount'),
        )

        return Response({
            'agent': UserSerializer(agent, context={'request': request}).data,
            'stats': {
                'reservations': {
                    'total': reservations_qs.count(),
                    'pending': reservations_by_status.get('pending', 0),
                    'confirmed': reservations_by_status.get('confirmed', 0),
                    'completed': reservations_by_status.get('completed', 0),
                    'cancelled': reservations_by_status.get('cancelled', 0),
                },
                'leads': {
                    'total': leads_qs.count(),
                    'qualified': leads_qs.filter(
                        qualification__in=['hot', 'warm']
                    ).count(),
                },
                'clients': len(set(client_ids)),
                'commissions': {
                    'total_count': commissions_qs.count(),
                    'pending_amount': float(commissions_pending['amount'] or 0),
                    'paid_amount': float(commissions_paid['amount'] or 0),
                },
                'revenue': float(revenue),
            },
        })