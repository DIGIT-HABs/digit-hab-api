"""
Models for authentication and user management.
"""

from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone
from django.core.validators import RegexValidator
import uuid


class User(AbstractUser):
    """Custom User model with additional fields for CRM."""
    
    groups = models.ManyToManyField(
        'auth.Group',
        related_name='custom_auth_users',
        blank=True,
        help_text='The groups this user belongs to. A user will get all permissions granted to each of their groups.',
        related_query_name='custom_auth_user',
    )
    user_permissions = models.ManyToManyField(
        'auth.Permission',
        related_name='custom_auth_users',
        blank=True,
        help_text='Specific permissions for this user.',
        related_query_name='custom_auth_user',
    )
    
    # Basic information
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True)
    phone = models.CharField(
        max_length=20, 
        blank=True, 
        null=True,
        validators=[RegexValidator(
            regex=r'^\+?1?\d{9,15}$',
            message="Phone number must be entered in the format: '+999999999'. Up to 15 digits allowed."
        )]
    )
    
    # User role in the system
    role = models.CharField(
        max_length=20,
        choices=[
            ('client', 'Client'),
            ('agent', 'Agent'),
            ('manager', 'Manager'),
            ('admin', 'Administrateur'),
        ],
        default='client',
        help_text='User role in the system (client, agent, or admin)'
    )
    
    # Profile information
    avatar = models.ImageField(upload_to='avatars/', blank=True, null=True)
    bio = models.TextField(blank=True)
    date_of_birth = models.DateField(blank=True, null=True)
    
    # Contact preferences
    preferred_contact_method = models.CharField(
        max_length=20,
        choices=[
            ('email', 'Email'),
            ('phone', 'Phone'),
            ('sms', 'SMS'),
        ],
        default='email'
    )
    
    # Account status
    is_active = models.BooleanField(default=True)
    is_verified = models.BooleanField(default=False)
    verified_at = models.DateTimeField(blank=True, null=True)
    
    # Metadata
    last_activity = models.DateTimeField(blank=True, null=True)
    login_count = models.IntegerField(default=0)
    failed_login_attempts = models.IntegerField(default=0)
    locked_until = models.DateTimeField(blank=True, null=True)
    
    # GDPR compliance
    privacy_consent = models.BooleanField(default=False)
    privacy_consent_date = models.DateTimeField(blank=True, null=True)
    marketing_consent = models.BooleanField(default=False)
    marketing_consent_date = models.DateTimeField(blank=True, null=True)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'custom_auth_user'
        verbose_name = 'User'
        verbose_name_plural = 'Users'
        ordering = ['-created_at']
        
    def __str__(self):
        return f"{self.get_full_name()} ({self.username})"
    
    def get_full_name(self):
        """Return full name or username if no name."""
        full_name = f"{self.first_name} {self.last_name}".strip()
        return full_name or self.username
    
    def is_account_locked(self):
        """Check if account is currently locked."""
        if not self.locked_until:
            return False
        return self.locked_until > timezone.now()
    
    def lock_account(self, duration_minutes=30):
        """Lock account for specified duration."""
        self.locked_until = timezone.now() + timezone.timedelta(minutes=duration_minutes)
        self.save(update_fields=['locked_until'])
    
    def unlock_account(self):
        """Unlock account."""
        self.locked_until = None
        self.save(update_fields=['locked_until'])
    
    def update_last_activity(self):
        """Update last activity timestamp."""
        self.last_activity = timezone.now()
        self.login_count += 1
        self.save(update_fields=['last_activity', 'login_count'])
    
    def grant_verification(self):
        """Grant email verification."""
        self.is_verified = True
        self.verified_at = timezone.now()
        self.save(update_fields=['is_verified', 'verified_at'])
    
    def revoke_verification(self):
        """Revoke email verification."""
        self.is_verified = False
        self.verified_at = None
        self.save(update_fields=['is_verified', 'verified_at'])
    
    @property
    def agency(self):
        """
        Get user's agency from profile.
        Returns None if user has no profile or profile has no agency.
        """
        try:
            return self.profile.agency
        except (AttributeError, Exception):
            return None
    
    @property
    def full_name(self):
        """Property version of get_full_name for template compatibility."""
        return self.get_full_name()


class Agency(models.Model):
    """Agency model for real estate companies."""
    
    # Basic information
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200)
    legal_name = models.CharField(max_length=200, blank=True)
    license_number = models.CharField(max_length=100, unique=True)
    vat_number = models.CharField(max_length=50, blank=True)
    
    # Contact information
    email = models.EmailField()
    phone = models.CharField(max_length=20)
    website = models.URLField(blank=True)
    logo = models.ImageField(upload_to='agencies/logos/', blank=True, null=True)
    
    # Address
    address_line1 = models.CharField(max_length=200)
    address_line2 = models.CharField(max_length=200, blank=True)
    city = models.CharField(max_length=100)
    postal_code = models.CharField(max_length=20)
    country = models.CharField(max_length=100, default='Sénégal')
    
    # Business information
    subscription_type = models.CharField(
        max_length=20,
        choices=[
            ('trial', 'Trial'),
            ('basic', 'Basic'),
            ('premium', 'Premium'),
            ('enterprise', 'Enterprise'),
        ],
        default='trial'
    )
    
    # Subscription details
    subscription_start = models.DateTimeField()
    subscription_end = models.DateTimeField()
    max_agents = models.IntegerField(default=5)
    max_properties = models.IntegerField(default=100)
    max_clients = models.IntegerField(default=500)
    
    # Features
    features = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True)
    is_trial = models.BooleanField(default=False)
    
    # Settings
    settings = models.JSONField(default=dict, blank=True)
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'agencies'
        verbose_name = 'Agency'
        verbose_name_plural = 'Agencies'
        ordering = ['-created_at']
        
    def __str__(self):
        return self.name
    
    def is_subscription_active(self):
        """Check if subscription is currently active."""
        now = timezone.now()
        return self.is_active and self.subscription_start <= now <= self.subscription_end
    
    def get_subscription_days_remaining(self):
        """Get remaining days of subscription."""
        if not self.is_subscription_active():
            return 0
        end_date = self.subscription_end
        remaining = (end_date - timezone.now()).days
        return max(0, remaining)
    
    def can_add_agent(self):
        """Check if agency can add more agents (ne compte que les utilisateurs avec role=agent)."""
        from django.contrib.auth import get_user_model
        UserModel = get_user_model()
        agent_count = UserModel.objects.filter(profile__agency=self, role='agent').count()
        return agent_count < self.max_agents
    
    def can_add_property(self):
        """Check if agency can add more properties."""
        from django.apps import apps
        return self.properties.count() < self.max_properties
    
    def can_add_client(self):
        """Check if agency can add more clients."""
        from django.apps import apps
        return self.clients.count() < self.max_clients
    
    def get_feature_enabled(self, feature_name):
        """Check if specific feature is enabled."""
        subscription_features = {
            'trial': [],
            'basic': ['properties', 'clients', 'visits'],
            'premium': ['properties', 'clients', 'visits', 'reservations', 'payments'],
            'enterprise': ['properties', 'clients', 'visits', 'reservations', 'payments', 'analytics', 'api'],
        }
        return feature_name in subscription_features.get(self.subscription_type, [])


class UserProfile(models.Model):
    """Extended user profile linked to User model."""
    
    # Relations
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    agency = models.ForeignKey(Agency, on_delete=models.PROTECT, related_name='users')
    
    # Professional information
    employee_id = models.CharField(max_length=50, blank=True)
    position = models.CharField(max_length=100, blank=True)
    department = models.CharField(max_length=100, blank=True)
    
    # Personal information
    date_of_birth = models.DateField(blank=True, null=True)
    nationality = models.CharField(max_length=100, blank=True)
    language_preference = models.CharField(
        max_length=10,
        choices=[
            ('fr', 'Français'),
            ('en', 'English'),
            ('es', 'Español'),
        ],
        default='fr'
    )
    
    # Work preferences
    timezone = models.CharField(max_length=50, default='Europe/Paris')
    work_hours_start = models.TimeField(blank=True, null=True)
    work_hours_end = models.TimeField(blank=True, null=True)
    working_days = models.CharField(
        max_length=20,
        default='1,2,3,4,5',  # Monday to Friday
        help_text='Comma-separated list of working days (0=Monday, 6=Sunday)'
    )
    
    # Notification preferences
    email_notifications = models.BooleanField(default=True)
    sms_notifications = models.BooleanField(default=False)
    push_notifications = models.BooleanField(default=True)
    
    # Performance tracking
    properties_assigned = models.IntegerField(default=0)
    clients_assigned = models.IntegerField(default=0)
    sales_this_month = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    sales_this_year = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'user_profiles'
        verbose_name = 'User Profile'
        verbose_name_plural = 'User Profiles'
        
    def __str__(self):
        return f"{self.user.get_full_name()} - {self.agency.name}"
    
    def get_working_days(self):
        """Return list of working days."""
        return [int(day) for day in self.working_days.split(',') if day]
    
    def set_working_days(self, days_list):
        """Set working days from list."""
        self.working_days = ','.join(str(day) for day in days_list)
    
    def is_working_today(self):
        """Check if today is a working day."""
        today = timezone.now().weekday()  # Monday=0, Sunday=6
        return str(today) in self.working_days