"""
Django base configuration.
All configuration lives in this package.
"""

# Build paths inside the project like this: BASE_DIR / 'subdir'.
from pathlib import Path
import os
from decouple import config
from kombu import Queue

BASE_DIR = Path(__file__).resolve().parent.parent

# Security & Debug
SECRET_KEY = config('SECRET_KEY', default='django-insecure-change-me')
DEBUG = config('DEBUG', default=True, cast=bool)
ALLOWED_HOSTS = config('ALLOWED_HOSTS', default='localhost,127.0.0.1,0.0.0.0,192.168.1.35', cast=lambda v: [s.strip() for s in v.split(',')])

# Apps
DJANGO_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.humanize',
    'django.contrib.postgres',
]

THIRD_PARTY_APPS = [
    'rest_framework',
    'rest_framework.authtoken',
    'corsheaders',
    'django_filters',
    'drf_spectacular',
    'django_extensions',
]

LOCAL_APPS = [
    'apps.auth',
    'apps.properties',
    'apps.favorites',
    'apps.crm',
    'apps.reservations',
    'apps.notifications',
    'apps.calendar',
    'apps.commissions',
    'apps.messaging',
    'apps.reviews',
    'apps.core',
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

# Middleware
MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'digit_hab_crm.urls'

# Templates
TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'digit_hab_crm.wsgi.application'

# Database configuration is defined in dev.py or prod.py
# Do not define DATABASES here in base.py

# # Database
# DATABASES = {
#     'default': {
#         'ENGINE': 'django.db.backends.postgresql',
#         'NAME': config('DB_NAME', default='digit_hab_crm'),
#         'USER': config('DB_USER', default='postgres'),
#         'PASSWORD': config('DB_PASSWORD', default='password'),
#         'HOST': config('DB_HOST', default='localhost'),
#         'PORT': config('DB_PORT', default='5432'),
#         'OPTIONS': {
#         },
#         'TEST': {
#             'NAME': 'test_digit_hab_crm',
#         },
#     }
# }

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
        'OPTIONS': {
            'min_length': 8,
        }
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

# Internationalization
LANGUAGE_CODE = 'fr'
TIME_ZONE = 'Europe/Paris'
USE_I18N = True
USE_TZ = True

# Static files
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
_static_dir = BASE_DIR / 'static'
STATICFILES_DIRS = [_static_dir] if _static_dir.is_dir() else []

# Media files
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Custom User Model
AUTH_USER_MODEL = 'custom_auth.User'

# REST Framework Configuration
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework_simplejwt.authentication.JWTAuthentication',
        # Removed SessionAuthentication to avoid UUID/Integer conflicts
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticatedOrReadOnly',  # Allow unauthenticated read access
    ],
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 20,
    'DEFAULT_FILTER_BACKENDS': [
        'django_filters.rest_framework.DjangoFilterBackend',
        'rest_framework.filters.SearchFilter',
        'rest_framework.filters.OrderingFilter',
    ],
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
}

# CORS Configuration
CORS_ALLOWED_ORIGINS = config(
    'CORS_ALLOWED_ORIGINS', 
    default='http://localhost:3000,http://127.0.0.1:3000,http://localhost:8081,http://127.0.0.1:8081', 
    cast=lambda v: [s.strip() for s in v.split(',')]
)

# Configuration CORS pour mobile (Expo/React Native)
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOW_HEADERS = [
    'accept',
    'accept-encoding',
    'authorization',
    'content-type',
    'dnt',
    'origin',
    'user-agent',
    'x-csrftoken',
    'x-requested-with',
]
CORS_ALLOW_METHODS = [
    'DELETE',
    'GET',
    'OPTIONS',
    'PATCH',
    'POST',
    'PUT',
]

# En développement, accepter toutes les origines (plus simple pour mobile)
if DEBUG:
    CORS_ALLOW_ALL_ORIGINS = True

# API Documentation
SPECTACULAR_SETTINGS = {
    'TITLE': 'DIGIT-HAB CRM API',
    'DESCRIPTION': 'API de gestion CRM pour l\'immobilier',
    'VERSION': '1.0.0',
    'SERVE_INCLUDE_SCHEMA': False,
    'COMPONENT_SPLIT_REQUEST': True,
    'COMPONENT_SPLIT_RESPONSE': True,
    'SORT_OPERATIONS': False,
    'COMPONENT_OPERATIONS_SPLIT_REQUEST': True,
    'COMPONENT_OPERATIONS_SPLIT_RESPONSE': True,
}

# Celery Configuration
CELERY_BROKER_URL = config('CELERY_BROKER_URL', default='redis://localhost:6379/0')
CELERY_RESULT_BACKEND = config('CELERY_RESULT_BACKEND', default='redis://localhost:6379/1')
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_ALWAYS_EAGER = DEBUG  # Only for development

# Define task routes
CELERY_TASK_ROUTES = {
    'apps.core.tasks.*': {'queue': 'core'},
    'apps.auth.tasks.*': {'queue': 'auth'},
    'apps.properties.tasks.*': {'queue': 'properties'},
    'apps.clients.tasks.*': {'queue': 'clients'},
}

# Define queues
CELERY_TASK_QUEUES = [
    Queue('default'),
    Queue('core'),
    Queue('auth'),
    Queue('properties'),
    Queue('clients'),
]

# Redis Configuration
# REDIS_URL = config('REDIS_URL', default='redis://localhost:6379/2')
# CACHES = {
#     'default': {
#         'BACKEND': 'django_redis.cache.RedisCache',
#         'LOCATION': REDIS_URL,
#         'OPTIONS': {
#             'PARSER_CLASS': 'redis.connection.HiredisParser',
#             'CONNECTION_POOL_KWARGS': {
#                 'max_connections': 50,
#                 'retry_on_timeout': True,
#             }
#         }
#     }
# }

# Session Configuration
SESSION_ENGINE = 'django.contrib.sessions.backends.db'  # Use DB instead of Redis for sessions
SESSION_COOKIE_AGE = 86400  # 1 day
SESSION_SAVE_EVERY_REQUEST = False

# Email Configuration
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = config('EMAIL_HOST', default='smtp.gmail.com')
EMAIL_PORT = config('EMAIL_PORT', default=587, cast=int)
EMAIL_USE_TLS = config('EMAIL_USE_TLS', default=True, cast=bool)
EMAIL_HOST_USER = config('EMAIL_HOST_USER', default='')
EMAIL_HOST_PASSWORD = config('EMAIL_HOST_PASSWORD', default='')

# Logging Configuration
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {process:d} {thread:d} {message}',
            'style': '{',
        },
        'simple': {
            'format': '{levelname} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'file': {
            'level': 'INFO',
            'class': 'logging.FileHandler',
            'filename': BASE_DIR / 'logs/digit_hab_crm.log',
            'formatter': 'verbose',
        },
        'console': {
            'level': 'DEBUG',
            'class': 'logging.StreamHandler',
            'formatter': 'simple',
        },
    },
    'root': {
        'handlers': ['console', 'file'],
        'level': 'INFO',
    },
    'loggers': {
        'django': {
            'handlers': ['console', 'file'],
            'level': 'INFO',
            'propagate': False,
        },
        'digit_hab_crm': {
            'handlers': ['console', 'file'],
            'level': 'DEBUG',
            'propagate': False,
        },
    },
}

# Cloudinary Configuration (for file storage) - DÉSACTIVÉ
# CLOUDINARY_URL = config('CLOUDINARY_URL', default='')
# if CLOUDINARY_URL:
#     DEFAULT_FILE_STORAGE = 'cloudinary_storage.storage.MediaCloudinaryStorage'

# Utilisation du stockage local par défaut
DEFAULT_FILE_STORAGE = 'django.core.files.storage.FileSystemStorage'

# Stripe Configuration (for payments)
STRIPE_PUBLISHABLE_KEY = config('STRIPE_PUBLISHABLE_KEY', default='')
STRIPE_SECRET_KEY = config('STRIPE_SECRET_KEY', default='')
STRIPE_WEBHOOK_SECRET = config('STRIPE_WEBHOOK_SECRET', default='')

# Reservations Configuration
RESERVATION_DEFAULT_DURATION = config('RESERVATION_DEFAULT_DURATION', default=60, cast=int)  # minutes
RESERVATION_AUTO_EXPIRE_HOURS = config('RESERVATION_AUTO_EXPIRE_HOURS', default=24, cast=int)
RESERVATION_REMINDER_HOURS = config('RESERVATION_REMINDER_HOURS', default=24, cast=int)
PAYMENT_PROCESSING_TIMEOUT = config('PAYMENT_PROCESSING_TIMEOUT', default=300, cast=int)  # seconds
MAX_PARTICIPANTS_PER_VISIT = config('MAX_PARTICIPANTS_PER_VISIT', default=10, cast=int)

# Email Configuration
DEFAULT_FROM_EMAIL = config('DEFAULT_FROM_EMAIL', default='noreply@digit-hab.com')
FRONTEND_URL = config('FRONTEND_URL', default='http://localhost:3000')

# Working Hours Configuration
WORKING_HOURS_START = config('WORKING_HOURS_START', default='09:00')
WORKING_HOURS_END = config('WORKING_HOURS_END', default='18:00')
WORKING_DAYS = config('WORKING_DAYS', default='1,2,3,4,5', cast=lambda v: [int(x) for x in v.split(',')])  # 1=Monday, 7=Sunday

# Twilio Configuration (for SMS)
TWILIO_ACCOUNT_SID = config('TWILIO_ACCOUNT_SID', default='')
TWILIO_AUTH_TOKEN = config('TWILIO_AUTH_TOKEN', default='')
TWILIO_PHONE_NUMBER = config('TWILIO_PHONE_NUMBER', default='')

# JWT Configuration
from datetime import timedelta
SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=config('JWT_ACCESS_TOKEN_LIFETIME', default=60, cast=int)),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=90),    # ~3 mois    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': True,
    'UPDATE_LAST_LOGIN': True,
    'ALGORITHM': 'HS256',
    'SIGNING_KEY': SECRET_KEY,
    'VERIFYING_KEY': None,
    'AUDIENCE': None,
    'ISSUER': None,
    'USER_ID_FIELD': 'id',  # Use UUID 'id' field
    'USER_ID_CLAIM': 'user_id',  # Claim name in JWT
    'JWK_URL': None,
    'LEEWAY': 0,
    'AUTH_HEADER_TYPES': ('Bearer',),
    'AUTH_HEADER_NAME': 'HTTP_AUTHORIZATION',
    'USER_ID_FIELD': 'id',
    'USER_ID_CLAIM': 'user_id',
    'AUTH_TOKEN_CLASSES': ('rest_framework_simplejwt.tokens.AccessToken',),
    'TOKEN_TYPE_CLAIM': 'token_type',
}

# ============================================================================
# DJANGO CHANNELS CONFIGURATION (WebSockets)
# ============================================================================

ASGI_APPLICATION = 'digit_hab_crm.asgi.application'

# Channels layers (Redis for production, InMemory for development)
# InMemoryChannelLayer accepts no CONFIG; RedisChannelLayer requires "hosts"
CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels.layers.InMemoryChannelLayer' if DEBUG else 'channels_redis.core.RedisChannelLayer',
        'CONFIG': {} if DEBUG else {
            "hosts": [(
                config('REDIS_HOST', default='redis'),
                config('REDIS_PORT', default=6379, cast=int)
            )],
        },
    },
}

# WebSocket settings
WEBSOCKET_PING_INTERVAL = 20
WEBSOCKET_PING_TIMEOUT = 30
WEBSOCKET_CLOSE_TIMEOUT = 10

# ============================================================================
# NOTIFICATION SYSTEM SETTINGS
# ============================================================================

# Notification defaults
NOTIFICATION_CLEANUP_DAYS = 30  # Nettoyage automatique après 30 jours
MAX_NOTIFICATION_ATTEMPTS = 3
DEFAULT_NOTIFICATION_CHANNELS = ['websocket', 'in_app']

# Email settings (déjà configuré plus haut, ajoutons des options spécifiques)
EMAIL_NOTIFICATION_SUBJECT_PREFIX = "[DigitHab CRM] "
EMAIL_NOTIFICATION_BATCH_SIZE = 100

# ============================================================================
# CALENDAR SYSTEM SETTINGS
# ============================================================================

# Calendar defaults
DEFAULT_VISIT_DURATION = 60  # minutes
MAX_DAILY_VISITS = 8
MIN_BREAK_MINUTES = 30
TRAVEL_TIME_BUFFER = 15  # minutes de marge

# Time slot generation
DEFAULT_TIME_SLOT_DURATION = 60  # minutes
TIME_SLOT_BUFFER_MINUTES = 15  # marge entre créneaux

# Route optimization
ROUTE_OPTIMIZATION_ENABLED = True
DEFAULT_SPEED_KMH = 50  # vitesse moyenne pour calcul des trajets

# ============================================================================
# GEOLOCATION SETTINGS
# ============================================================================

# Geocoding service
GEOCODING_SERVICE = 'nominatim'  # 'nominatim', 'google', 'mapbox'
GEOCODING_USER_AGENT = 'digit_hab_crm/1.0'

# Default location (Paris)
DEFAULT_LATITUDE = 48.8566
DEFAULT_LONGITUDE = 2.3522

# ============================================================================
# PERFORMANCE SETTINGS
# ============================================================================

# Cache settings are defined earlier in this file (line ~242)
# Do not redefine CACHES here to avoid conflicts

# ============================================================================
# LOGGING CONFIGURATION
# ============================================================================

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {process:d} {thread:d} {message}',
            'style': '{',
        },
        'simple': {
            'format': '{levelname} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'simple',
        },
        'file': {
            'class': 'logging.FileHandler',
            'filename': 'digit_hab.log',
            'formatter': 'verbose',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'INFO',
    },
    'loggers': {
        'django': {
            'handlers': ['console', 'file'],
            'level': 'INFO',
            'propagate': True,
        },
        'apps.notifications': {
            'handlers': ['console', 'file'],
            'level': 'DEBUG',
            'propagate': True,
        },
        'apps.calendar': {
            'handlers': ['console', 'file'],
            'level': 'DEBUG',
            'propagate': True,
        },
    },
}