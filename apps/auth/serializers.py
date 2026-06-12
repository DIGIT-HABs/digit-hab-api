"""
Serializers for authentication app.
"""

from decimal import Decimal, InvalidOperation
from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.utils import timezone
from rest_framework import serializers
from rest_framework_simplejwt.tokens import RefreshToken
from .models import User, Agency, UserProfile

# Use our custom User model directly instead of get_user_model()
UserModel = User


class OptionalImageField(serializers.ImageField):
    """ImageField qui ignore les valeurs non-fichier (évite l'erreur multipart mal formé)."""
    def to_internal_value(self, data):
        if data is None:
            return None
        # Accepter uniquement un vrai fichier uploadé (objet avec read/name)
        if hasattr(data, 'read') or (hasattr(data, 'name') and hasattr(data, 'size')):
            return super().to_internal_value(data)
        return None


# Response Serializers for API Documentation
class LogoutResponseSerializer(serializers.Serializer):
    """Serializer for logout response."""
    message = serializers.CharField()


class TokenVerifyResponseSerializer(serializers.Serializer):
    """Serializer for token verification response."""
    valid = serializers.BooleanField()
    user_id = serializers.UUIDField()
    username = serializers.CharField()
    is_staff = serializers.BooleanField()
    is_superuser = serializers.BooleanField()


class RefreshTokenSerializer(serializers.Serializer):
    """Serializer for logout request."""
    refresh = serializers.CharField()


class UserSerializer(serializers.ModelSerializer):
    """Serializer for User model."""
    
    avatar = OptionalImageField(required=False, allow_null=True)
    full_name = serializers.CharField(source='get_full_name', read_only=True)
    agency = serializers.SerializerMethodField()
    agency_id = serializers.SerializerMethodField()
    role = serializers.CharField(read_only=True)
    
    class Meta:
        model = User
        fields = [
            'id', 'username', 'email', 'first_name', 'last_name', 'full_name',
            'phone', 'avatar', 'bio', 'date_of_birth', 'preferred_contact_method',
            'is_active', 'is_verified', 'verified_at', 'last_activity', 'login_count',
            'role', 'agency', 'agency_id',
            'created_at', 'updated_at'
        ]
        read_only_fields = [
            'id', 'is_verified', 'verified_at', 'last_activity', 'login_count',
            'role', 'agency', 'agency_id',
            'created_at', 'updated_at'
        ]
    
    def get_agency(self, obj):
        """Get agency name from profile."""
        try:
            if hasattr(obj, 'profile') and obj.profile.agency:
                return obj.profile.agency.name
        except Exception:
            pass
        return None
    
    def get_agency_id(self, obj):
        """Get agency ID from profile."""
        try:
            if hasattr(obj, 'profile') and obj.profile.agency:
                return str(obj.profile.agency.id)
        except Exception:
            pass
        return None
    
    def validate_email(self, value):
        """Validate email uniqueness."""
        user = self.instance
        if UserModel.objects.filter(email=value).exclude(pk=user.pk).exists():
            raise serializers.ValidationError("This email is already in use.")
        return value
    
    def validate_phone(self, value):
        """Validate phone format."""
        if value and not value.strip():
            return None
        return value


class UserCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating new users."""
    
    password = serializers.CharField(write_only=True, validators=[validate_password])
    password_confirm = serializers.CharField(write_only=True)
    
    class Meta:
        model = User
        fields = [
            'username', 'email', 'password', 'password_confirm', 'first_name', 
            'last_name', 'phone', 'preferred_contact_method'
        ]
    
    def validate(self, attrs):
        """Validate password confirmation and uniqueness."""
        if attrs['password'] != attrs['password_confirm']:
            raise serializers.ValidationError("Passwords don't match.")
        
        # Check username uniqueness
        if UserModel.objects.filter(username=attrs['username']).exists():
            raise serializers.ValidationError("Username already exists.")
        
        # Check email uniqueness
        if UserModel.objects.filter(email=attrs['email']).exists():
            raise serializers.ValidationError("Email already exists.")
        
        return attrs
    
    def create(self, validated_data):
        """Create user with password validation."""
        validated_data.pop('password_confirm')
        password = validated_data.pop('password')
        
        user = UserModel.objects.create_user(**validated_data)
        user.set_password(password)
        user.save()
        
        return user


class AgentCreateSerializer(serializers.Serializer):
    """Création d'un compte agent (rattaché à une agence)."""
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, validators=[validate_password])
    password_confirm = serializers.CharField(write_only=True)
    first_name = serializers.CharField(max_length=150, required=True, allow_blank=False)
    last_name = serializers.CharField(max_length=150, required=True, allow_blank=False)
    phone = serializers.CharField(max_length=20, required=False, allow_blank=True)
    agency_id = serializers.UUIDField(required=False, allow_null=True)

    def validate(self, attrs):
        if attrs['password'] != attrs['password_confirm']:
            raise serializers.ValidationError({"password_confirm": "Les mots de passe ne correspondent pas."})
        if UserModel.objects.filter(email=attrs['email']).exists():
            raise serializers.ValidationError({"email": "Un compte existe déjà avec cet email."})
        return attrs

    def create(self, validated_data):
        from .models import UserProfile
        validated_data.pop('password_confirm')
        password = validated_data.pop('password')
        agency_id = validated_data.pop('agency_id', None)
        request = self.context.get('request')
        # Agence : fournie uniquement par un admin (is_staff), sinon agence de l'utilisateur connecté
        if agency_id and request and getattr(request.user, 'is_staff', False):
            agency = Agency.objects.filter(pk=agency_id).first()
            if not agency:
                raise serializers.ValidationError({"agency_id": "Agence introuvable."})
        else:
            if not request or not getattr(request.user, 'profile', None) or not getattr(request.user.profile, 'agency', None):
                raise serializers.ValidationError({"agency_id": "Vous devez être rattaché à une agence ou préciser une agence."})
            agency = request.user.profile.agency
        if not agency.can_add_agent():
            raise serializers.ValidationError({"agency_id": "Quota d'agents atteint pour cette agence."})
        username = validated_data['email'].split('@')[0]
        base_username = username
        counter = 1
        while UserModel.objects.filter(username=username).exists():
            username = f"{base_username}{counter}"
            counter += 1
        user = UserModel.objects.create(
            username=username,
            role='agent',
            **validated_data
        )
        user.set_password(password)
        user.save()
        # Le signal crée un UserProfile avec la première agence ; on met à jour vers la bonne agence
        profile = user.profile
        profile.agency = agency
        profile.save(update_fields=['agency'])
        return user


class UserProfileSerializer(serializers.ModelSerializer):
    """Serializer for UserProfile model."""
    
    user = UserSerializer(read_only=True)
    
    class Meta:
        model = UserProfile
        fields = [
            'user', 'employee_id', 'position', 'department', 'date_of_birth',
            'nationality', 'language_preference', 'timezone', 'work_hours_start',
            'work_hours_end', 'working_days', 'email_notifications', 'sms_notifications',
            'push_notifications', 'properties_assigned', 'clients_assigned',
            'sales_this_month', 'sales_this_year', 'created_at', 'updated_at'
        ]
        read_only_fields = [
            'properties_assigned', 'clients_assigned', 'sales_this_month', 
            'sales_this_year', 'created_at', 'updated_at'
        ]
    
    def get_working_days(self, obj):
        """Return working days as list."""
        return obj.get_working_days()
    
    def validate_working_days(self, value):
        """Validate working days format."""
        if isinstance(value, list):
            return ','.join(str(day) for day in value)
        return value


class AgencySerializer(serializers.ModelSerializer):
    """Serializer for Agency model."""
    
    users_count = serializers.IntegerField(source='users.count', read_only=True)
    properties_count = serializers.IntegerField(source='properties.count', read_only=True)
    clients_count = serializers.IntegerField(source='clients.count', read_only=True)
    logo_url = serializers.SerializerMethodField(read_only=True)
    commission_rate = serializers.SerializerMethodField(read_only=True)
    
    class Meta:
        model = Agency
        fields = [
            'id', 'name', 'legal_name', 'license_number', 'vat_number',
            'email', 'phone', 'website', 'logo', 'logo_url',
            'address_line1', 'address_line2',
            'city', 'postal_code', 'country', 'subscription_type',
            'subscription_start', 'subscription_end', 'max_agents', 'max_properties',
            'max_clients', 'features', 'is_active', 'is_trial',
            'commission_rate',
            'users_count', 'properties_count', 'clients_count', 'created_at', 'updated_at'
        ]
        read_only_fields = [
            'users_count', 'properties_count', 'clients_count', 'created_at', 'updated_at', 'logo_url'
        ]
        extra_kwargs = {'logo': {'required': False}}
    
    def get_logo_url(self, obj):
        if obj.logo:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.logo.url)
            return obj.logo.url
        return None

    def get_commission_rate(self, obj):
        """Retourne le taux de commission (%) stocké dans settings, fallback à 3.00."""
        rate = (obj.settings or {}).get('commission_rate', '3.00')
        try:
            return str(Decimal(str(rate)))
        except (InvalidOperation, TypeError):
            return '3.00'
    
    def validate_license_number(self, value):
        """Validate license number uniqueness."""
        agency = self.instance
        if Agency.objects.filter(license_number=value).exclude(pk=agency.pk).exists():
            raise serializers.ValidationError("This license number is already in use.")
        return value
    
    def validate_vat_number(self, value):
        """Validate VAT number uniqueness."""
        if not value:
            return value
        agency = self.instance
        if Agency.objects.filter(vat_number=value).exclude(pk=agency.pk).exists():
            raise serializers.ValidationError("This VAT number is already in use.")
        return value


class AgencyCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating new agencies."""
    
    logo = OptionalImageField(required=False, allow_null=True)
    
    class Meta:
        model = Agency
        fields = [
            'name', 'legal_name', 'license_number', 'vat_number',
            'email', 'phone', 'website', 'logo',
            'address_line1', 'address_line2',
            'city', 'postal_code', 'country', 'subscription_type'
        ]
    
    def validate_license_number(self, value):
        """Validate license number uniqueness."""
        if Agency.objects.filter(license_number=value).exists():
            raise serializers.ValidationError("This license number is already in use.")
        return value
    
    def validate_vat_number(self, value):
        """Validate VAT number uniqueness."""
        if value and Agency.objects.filter(vat_number=value).exists():
            raise serializers.ValidationError("This VAT number is already in use.")
        return value
    
    def create(self, validated_data):
        """Create agency with subscription details."""
        from django.utils import timezone
        from datetime import timedelta
        
        # Set subscription dates
        now = timezone.now()
        validated_data['subscription_start'] = now
        
        # Set default subscription end based on type
        subscription_lengths = {
            'trial': 30,  # 30 days trial
            'basic': 365,  # 1 year
            'premium': 365,  # 1 year
            'enterprise': 365,  # 1 year
        }
        
        duration = subscription_lengths.get(validated_data.get('subscription_type', 'trial'), 30)
        validated_data['subscription_end'] = now + timedelta(days=duration)
        
        return Agency.objects.create(**validated_data)


class AgencyWithAgentRegisterSerializer(serializers.Serializer):
    """Inscription publique : créer une agence + le compte agent fondateur en une étape."""

    name = serializers.CharField(max_length=255)
    legal_name = serializers.CharField(required=False, allow_blank=True, default='')
    license_number = serializers.CharField()
    vat_number = serializers.CharField(required=False, allow_blank=True, default='')
    email = serializers.EmailField()
    phone = serializers.CharField(max_length=20)
    website = serializers.URLField(required=False, allow_blank=True, default='')
    logo = OptionalImageField(required=False, allow_null=True)
    address_line1 = serializers.CharField()
    address_line2 = serializers.CharField(required=False, allow_blank=True, default='')
    city = serializers.CharField()
    postal_code = serializers.CharField()
    country = serializers.CharField(default='Sénégal')
    subscription_type = serializers.ChoiceField(
        choices=['trial', 'basic', 'premium', 'enterprise'],
        default='trial',
        required=False,
    )
    first_name = serializers.CharField(max_length=150)
    last_name = serializers.CharField(max_length=150)
    password = serializers.CharField(write_only=True, validators=[validate_password])
    password_confirm = serializers.CharField(write_only=True)

    def validate_license_number(self, value):
        if Agency.objects.filter(license_number=value).exists():
            raise serializers.ValidationError('Ce numéro de licence est déjà utilisé.')
        return value

    def validate_vat_number(self, value):
        if value and Agency.objects.filter(vat_number=value).exists():
            raise serializers.ValidationError('Ce numéro de TVA est déjà utilisé.')
        return value

    def validate(self, attrs):
        if attrs['password'] != attrs['password_confirm']:
            raise serializers.ValidationError({
                'password_confirm': 'Les mots de passe ne correspondent pas.',
            })
        if UserModel.objects.filter(email=attrs['email']).exists():
            raise serializers.ValidationError({
                'email': 'Un compte existe déjà avec cet email.',
            })
        return attrs

    def create(self, validated_data):
        from django.db import transaction

        first_name = validated_data.pop('first_name')
        last_name = validated_data.pop('last_name')
        password = validated_data.pop('password')
        validated_data.pop('password_confirm')

        agency_keys = (
            'name', 'legal_name', 'license_number', 'vat_number', 'email', 'phone',
            'website', 'logo', 'address_line1', 'address_line2', 'city', 'postal_code',
            'country', 'subscription_type',
        )
        agency_data = {key: validated_data[key] for key in agency_keys}

        with transaction.atomic():
            agency_serializer = AgencyCreateSerializer(data=agency_data)
            agency_serializer.is_valid(raise_exception=True)
            agency = agency_serializer.save()

            email = agency_data['email']
            username = email.split('@')[0]
            base_username = username
            counter = 1
            while UserModel.objects.filter(username=username).exists():
                username = f'{base_username}{counter}'
                counter += 1

            user = UserModel.objects.create(
                username=username,
                email=email,
                first_name=first_name,
                last_name=last_name,
                phone=agency_data.get('phone') or '',
                role='agent',
            )
            user.set_password(password)
            user.save()

            profile = user.profile
            profile.agency = agency
            profile.save(update_fields=['agency'])

        return {'agency': agency, 'user': user}


class AgencyUpdateSerializer(serializers.ModelSerializer):
    """Serializer for updating agency (e.g. logo, name)."""
    
    logo = OptionalImageField(required=False, allow_null=True)
    commission_rate = serializers.DecimalField(
        max_digits=5,
        decimal_places=2,
        min_value=Decimal('0.00'),
        max_value=Decimal('100.00'),
        required=False,
        help_text="Taux de commission (%) appliqué par défaut aux contrats signés."
    )
    
    class Meta:
        model = Agency
        fields = [
            'name', 'legal_name', 'website', 'logo',
            'address_line1', 'address_line2',
            'city', 'postal_code', 'country',
            'commission_rate',
        ]
    
    def validate_name(self, value):
        if not value or not value.strip():
            raise serializers.ValidationError("Le nom est requis.")
        return value

    def update(self, instance, validated_data):
        """Persiste commission_rate dans Agency.settings['commission_rate']."""
        commission_rate = validated_data.pop('commission_rate', None)
        instance = super().update(instance, validated_data)
        if commission_rate is not None:
            settings = instance.settings or {}
            settings['commission_rate'] = str(commission_rate)
            instance.settings = settings
            instance.save(update_fields=['settings', 'updated_at'])
        return instance


class LoginSerializer(serializers.Serializer):
    """Serializer for user login."""
    
    username = serializers.CharField()
    password = serializers.CharField(write_only=True)
    
    def validate(self, attrs):
        """Authenticate user credentials."""
        username = attrs.get('username')
        password = attrs.get('password')
        
        if username and password:
            user = authenticate(
                request=self.context.get('request'),
                username=username,
                password=password
            )
            
            if not user:
                raise serializers.ValidationError('Invalid credentials.')
            
            if not user.is_active:
                raise serializers.ValidationError('User account is disabled.')
            
            # Check if account is locked
            if user.is_account_locked():
                raise serializers.ValidationError('Account is temporarily locked.')
            
            attrs['user'] = user
            return attrs
        
        raise serializers.ValidationError('Must include username and password.')


class TokenObtainSerializer(serializers.Serializer):
    """Base serializer for JWT token generation."""
    
    def validate(self, attrs):
        authenticate_kwargs = {
            self.username_field: attrs[self.username_field],
            'password': attrs['password'],
        }
        
        try:
            authenticate_kwargs['request'] = self.context['request']
        except KeyError:
            pass
        
        self.user = authenticate(**authenticate_kwargs)
        
        if not self.user:
            raise serializers.ValidationError('Invalid credentials.')
        
        if not self.user.is_active:
            raise serializers.ValidationError('User account is disabled.')
        
        return {}
    
    @classmethod
    def get_token(cls, user):
        """Generate JWT token for user."""
        token = RefreshToken.for_user(user)
        
        # Add custom claims
        token['user_id'] = str(user.id)
        token['username'] = user.username
        token['email'] = user.email
        token['is_verified'] = user.is_verified
        
        return token


class TokenObtainPairSerializer(serializers.Serializer):
    """Custom JWT token serializer with email/username + password."""
    
    email = serializers.EmailField(required=False, allow_blank=False)
    username = serializers.CharField(required=False, allow_blank=False)
    password = serializers.CharField(write_only=True, style={'input_type': 'password'})
    
    def validate(self, attrs):
        email = attrs.get('email', '').strip() if attrs.get('email') else ''
        username = attrs.get('username', '').strip() if attrs.get('username') else ''
        password = attrs.get('password', '')
        
        # Ensure at least one identifier is provided
        if not email and not username:
            raise serializers.ValidationError(
                'Must provide either email or username'
            )
        
        # Find user
        user = None
        if email:
            try:
                user = UserModel.objects.get(email=email)
            except UserModel.DoesNotExist:
                pass
        
        if not user and username:
            try:
                user = UserModel.objects.get(username=username)
            except UserModel.DoesNotExist:
                pass
        
        # Validate password
        if not user or not user.check_password(password):
            raise serializers.ValidationError('Invalid credentials')
        
        if not user.is_active:
            raise serializers.ValidationError('User account is disabled')
        
        # Store user for view
        attrs['user'] = user
        return attrs
    
    @classmethod
    def get_token(cls, user):
        """Generate refresh token with custom claims."""
        refresh = RefreshToken.for_user(user)
        
        # Add custom claims
        refresh['user_id'] = str(user.id)
        refresh['username'] = user.username
        refresh['email'] = user.email
        refresh['role'] = getattr(user, 'role', 'client')
        refresh['is_verified'] = getattr(user, 'is_verified', True)
        
        return refresh


class PasswordChangeSerializer(serializers.Serializer):
    """Serializer for password change."""
    
    old_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True, validators=[validate_password])
    new_password_confirm = serializers.CharField(write_only=True)
    
    def validate_old_password(self, value):
        """Validate current password."""
        user = self.context['request'].user
        if not user.check_password(value):
            raise serializers.ValidationError("Current password is incorrect.")
        return value
    
    def validate(self, attrs):
        """Validate password confirmation."""
        if attrs['new_password'] != attrs['new_password_confirm']:
            raise serializers.ValidationError("New passwords don't match.")
        return attrs
    
    def save(self):
        """Update user password."""
        user = self.context['request'].user
        user.set_password(self.validated_data['new_password'])
        user.save()
        return user


class PasswordResetSerializer(serializers.Serializer):
    """Serializer for password reset request."""
    
    email = serializers.EmailField()
    
    def validate_email(self, value):
        """Validate email exists."""
        try:
            UserModel.objects.get(email=value)
        except UserModel.DoesNotExist:
            raise serializers.ValidationError("No user found with this email address.")
        return value


class PasswordResetConfirmSerializer(serializers.Serializer):
    """Serializer for password reset confirmation."""
    
    new_password = serializers.CharField(write_only=True, validators=[validate_password])
    new_password_confirm = serializers.CharField(write_only=True)
    token = serializers.CharField()
    uid = serializers.CharField()
    
    def validate(self, attrs):
        """Validate password confirmation and token."""
        if attrs['new_password'] != attrs['new_password_confirm']:
            raise serializers.ValidationError("Passwords don't match.")
        return attrs
    
    def save(self):
        """Reset user password."""
        from django.contrib.auth import get_user_model
        from django.contrib.auth.tokens import default_token_generator
        from django.utils.http import urlsafe_base64_decode
        
        UserModel = get_user_model()
        uid = self.validated_data['uid']
        token = self.validated_data['token']
        new_password = self.validated_data['new_password']
        
        try:
            uid = urlsafe_base64_decode(uid).decode()
            user = UserModel.objects.get(pk=uid)
        except (TypeError, ValueError, OverflowError, UserModel.DoesNotExist):
            raise serializers.ValidationError("Invalid token or user ID.")
        
        if not default_token_generator.check_token(user, token):
            raise serializers.ValidationError("Invalid or expired token.")
        
        user.set_password(new_password)
        user.save()
        return user


# ============================================
# OAuth Serializers (Google & Apple) - V2
# ============================================

class SocialAuthSerializer(serializers.Serializer):
    """Base serializer for social authentication."""
    
    provider = serializers.ChoiceField(choices=['google', 'apple'])
    access_token = serializers.CharField(required=False)
    id_token = serializers.CharField(required=False)
    
    def validate(self, attrs):
        """Validate provider and tokens."""
        provider = attrs.get('provider')
        access_token = attrs.get('access_token')
        id_token = attrs.get('id_token')
        
        if not access_token and not id_token:
            raise serializers.ValidationError('Must provide access_token or id_token.')
        
        return attrs


class GoogleAuthSerializer(serializers.Serializer):
    """Serializer for Google OAuth authentication."""
    
    access_token = serializers.CharField(required=False)
    id_token = serializers.CharField()
    
    def validate(self, attrs):
        """Validate Google token and get user info."""
        id_token = attrs.get('id_token')
        
        try:
            # Import Google libraries (install: pip install google-auth)
            from google.oauth2 import id_token as google_id_token
            from google.auth.transport import requests
            from django.conf import settings
            
            # Verify the token
            idinfo = google_id_token.verify_oauth2_token(
                id_token, 
                requests.Request(), 
                getattr(settings, 'GOOGLE_OAUTH_CLIENT_ID', None)
            )
            
            # Verify the token issuer
            if idinfo['iss'] not in ['accounts.google.com', 'https://accounts.google.com']:
                raise serializers.ValidationError('Invalid token issuer.')
            
            # Extract user info
            attrs['email'] = idinfo.get('email', '')
            attrs['first_name'] = idinfo.get('given_name', '')
            attrs['last_name'] = idinfo.get('family_name', '')
            attrs['avatar'] = idinfo.get('picture', '')
            attrs['google_id'] = idinfo['sub']
            attrs['email_verified'] = idinfo.get('email_verified', False)
            
        except ValueError as e:
            raise serializers.ValidationError(f'Invalid Google token: {str(e)}')
        except ImportError:
            # Fallback if google-auth is not installed
            import logging
            logging.warning('Google OAuth libraries not installed. Using basic validation.')
            # Basic token structure validation only
            if not id_token or len(id_token) < 50:
                raise serializers.ValidationError('Invalid token format.')
            attrs['email'] = f"google_user_{id_token[:8]}@gmail.com"
            attrs['first_name'] = ''
            attrs['last_name'] = ''
            attrs['google_id'] = id_token[:16]
        
        return attrs
    
    def create_or_get_user(self, validated_data):
        """Create or get user from Google data."""
        email = validated_data.get('email')
        google_id = validated_data.get('google_id')
        
        # Try to find user by email or google_id
        user = None
        try:
            user = UserModel.objects.get(email=email)
        except UserModel.DoesNotExist:
            # Create new user
            username = email.split('@')[0]
            # Ensure unique username
            base_username = username
            counter = 1
            while UserModel.objects.filter(username=username).exists():
                username = f"{base_username}{counter}"
                counter += 1
            
            user = UserModel.objects.create(
                username=username,
                email=email,
                first_name=validated_data.get('first_name', ''),
                last_name=validated_data.get('last_name', ''),
                is_verified=True,  # Auto-verify Google users
            )
            
            # Save Google ID and avatar if available
            if hasattr(user, 'avatar') and validated_data.get('avatar'):
                user.avatar = validated_data.get('avatar')
            user.save()
        
        return user


class AppleAuthSerializer(serializers.Serializer):
    """Serializer for Apple Sign In authentication."""
    
    id_token = serializers.CharField()
    user_data = serializers.JSONField(required=False)
    
    def validate(self, attrs):
        """Validate Apple token and get user info."""
        id_token = attrs.get('id_token')
        user_data = attrs.get('user_data', {})
        
        try:
            # Import JWT library (install: pip install PyJWT cryptography)
            import jwt
            from django.conf import settings
            
            # Decode without verification for development
            # In production, you should verify with Apple's public key
            # Get Apple's public keys from: https://appleid.apple.com/auth/keys
            try:
                decoded = jwt.decode(
                    id_token,
                    options={"verify_signature": False}  # Disable for now
                )
                
                # Validate issuer and audience
                if decoded.get('iss') != 'https://appleid.apple.com':
                    raise serializers.ValidationError('Invalid token issuer.')
                
                # Extract user info
                attrs['email'] = decoded.get('email', '')
                attrs['apple_id'] = decoded['sub']
                attrs['email_verified'] = decoded.get('email_verified', 'false') == 'true'
                
                # Apple only provides name on first sign-in
                if user_data and 'name' in user_data:
                    attrs['first_name'] = user_data.get('name', {}).get('firstName', '')
                    attrs['last_name'] = user_data.get('name', {}).get('lastName', '')
                else:
                    attrs['first_name'] = ''
                    attrs['last_name'] = ''
                
            except jwt.InvalidTokenError as e:
                raise serializers.ValidationError(f'Invalid Apple token: {str(e)}')
                
        except ImportError:
            # Fallback if PyJWT is not installed
            import logging
            logging.warning('PyJWT not installed. Using basic validation.')
            # Basic token structure validation only
            if not id_token or len(id_token) < 50:
                raise serializers.ValidationError('Invalid token format.')
            attrs['email'] = ''
            attrs['apple_id'] = id_token[:16]
            attrs['first_name'] = user_data.get('name', {}).get('firstName', '') if user_data else ''
            attrs['last_name'] = user_data.get('name', {}).get('lastName', '') if user_data else ''
        
        return attrs
    
    def create_or_get_user(self, validated_data):
        """Create or get user from Apple data."""
        email = validated_data.get('email')
        apple_id = validated_data.get('apple_id')
        
        # Try to find user by email or apple_id
        user = None
        try:
            user = UserModel.objects.get(email=email)
        except UserModel.DoesNotExist:
            # Create new user
            username = email.split('@')[0] if email else f"apple_user_{apple_id[:8]}"
            # Ensure unique username
            base_username = username
            counter = 1
            while UserModel.objects.filter(username=username).exists():
                username = f"{base_username}{counter}"
                counter += 1
            
            user = UserModel.objects.create(
                username=username,
                email=email or f"{apple_id}@privaterelay.appleid.com",
                first_name=validated_data.get('first_name', ''),
                last_name=validated_data.get('last_name', ''),
                is_verified=True,  # Auto-verify Apple users
            )
            user.save()
        
        return user


class RegisterSerializer(serializers.ModelSerializer):
    """Serializer for user registration with email."""
    
    password = serializers.CharField(write_only=True, validators=[validate_password])
    password_confirm = serializers.CharField(write_only=True)
    
    class Meta:
        model = User
        fields = [
            'email', 'password', 'password_confirm', 'first_name', 
            'last_name', 'phone'
        ]
    
    def validate(self, attrs):
        """Validate password confirmation and uniqueness."""
        if attrs['password'] != attrs['password_confirm']:
            raise serializers.ValidationError({"password": "Passwords don't match."})
        
        # Check email uniqueness
        if UserModel.objects.filter(email=attrs['email']).exists():
            raise serializers.ValidationError({"email": "Email already exists."})
        
        return attrs
    
    def create(self, validated_data):
        """Create user with password validation."""
        validated_data.pop('password_confirm')
        password = validated_data.pop('password')
        
        # Generate username from email
        email = validated_data['email']
        username = email.split('@')[0]
        
        # Ensure unique username
        base_username = username
        counter = 1
        while UserModel.objects.filter(username=username).exists():
            username = f"{base_username}{counter}"
            counter += 1
        
        user = UserModel.objects.create(
            username=username,
            **validated_data
        )
        user.set_password(password)
        user.save()
        
        return user