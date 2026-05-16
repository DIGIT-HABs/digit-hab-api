"""
Production settings.
"""

from .base import *
import os
from pathlib import Path

# Basic production settings
DEBUG = False

# Allowed Hosts — fusion .env + défauts (évite DisallowedHost si .env oublie un domaine)
_default_allowed_hosts = [
    'digit-hab.altoppe.sn',
    'api.digit-hab.altoppe.sn',
    'api.digit-hab.wolofdigital.site',
    'localhost',
    '127.0.0.1',
]
allowed_hosts_env = os.environ.get('ALLOWED_HOSTS', '')
_env_hosts = [host.strip() for host in allowed_hosts_env.split(',') if host.strip()]
ALLOWED_HOSTS = list(dict.fromkeys(_env_hosts + _default_allowed_hosts))

# Security settings
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
# Nginx handles SSL redirect, so we disable it in Django to avoid loops
SECURE_SSL_REDIRECT = False
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True

# Session and CSRF security
SESSION_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
CSRF_COOKIE_SECURE = True
CSRF_COOKIE_HTTPONLY = True
CSRF_COOKIE_SAMESITE = 'Lax'

# CSRF Trusted Origins for HTTPS
_default_csrf_origins = [
    'https://digit-hab.altoppe.sn',
    'https://api.digit-hab.altoppe.sn',
    'https://api.digit-hab.wolofdigital.site',
]
_csrf_origins_env = os.environ.get('CSRF_TRUSTED_ORIGINS', '')
_env_csrf = [origin.strip() for origin in _csrf_origins_env.split(',') if origin.strip()]
CSRF_TRUSTED_ORIGINS = list(dict.fromkeys(_env_csrf + _default_csrf_origins))

# Content Security Policy
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_BROWSER_XSS_FILTER = True
X_FRAME_OPTIONS = 'DENY'

# Database - Production (PostgreSQL)
DATABASES = {
    'default': {
        'ENGINE': os.environ.get('DB_ENGINE', 'django.db.backends.postgresql'),
        'NAME': os.environ.get('DB_NAME', 'digit_hab_prod'),
        'USER': os.environ.get('DB_USER', 'digit_hab_user'),
        'PASSWORD': os.environ.get('DB_PASSWORD', 'changeme'),
        'HOST': os.environ.get('DB_HOST', 'db'),
        'PORT': os.environ.get('DB_PORT', '5432'),
        'CONN_MAX_AGE': 60,
    }
}


# Email backend for production
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = os.environ.get('EMAIL_HOST', 'smtp.gmail.com')
EMAIL_PORT = int(os.environ.get('EMAIL_PORT', 587))
EMAIL_USE_TLS = os.environ.get('EMAIL_USE_TLS', 'True').lower() in ['true', 'on', '1']
EMAIL_HOST_USER = os.environ.get('EMAIL_HOST_USER')
EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD')

# Fichiers uploadés — disque local par défaut (VPS).
# Cloudinary uniquement si USE_CLOUDINARY=true ET django-cloudinary-storage installé.
# Ne pas laisser CLOUDINARY_URL seul dans .env : ça provoquait des 500 sur add_image.
USE_CLOUDINARY = os.environ.get('USE_CLOUDINARY', '').lower() in ('true', '1', 'yes')
if USE_CLOUDINARY and os.environ.get('CLOUDINARY_URL'):
    try:
        import cloudinary_storage  # noqa: F401
    except ImportError:
        import logging
        logging.getLogger(__name__).error(
            'USE_CLOUDINARY=true mais django-cloudinary-storage absent — stockage local.'
        )
    else:
        DEFAULT_FILE_STORAGE = 'cloudinary_storage.storage.MediaCloudinaryStorage'

# Celery settings for production
CELERY_TASK_ALWAYS_EAGER = False
CELERY_EAGER_PROPAGATES_EXCEPTIONS = False

# CORS for production
CORS_ALLOW_ALL_ORIGINS = True
_cors_origins_env = os.environ.get('CORS_ALLOWED_ORIGINS', '')
CORS_ALLOWED_ORIGINS = [
    origin.strip()
    for origin in _cors_origins_env.split(',')
    if origin.strip()
] or [
    'https://api.digit-hab.altoppe.sn',
    'https://api.digit-hab.wolofdigital.site',
    'http://localhost:8000',
    'http://127.0.0.1:8000',
]

# Logging for production
# Override logging levels if needed
# Override Cache - Désactiver Redis temporairement
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.dummy.DummyCache',
    }
}

# Static files for production
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'

# Media files for production (/opt/apps/digit-hab-api/media sur le VPS)
MEDIA_URL = '/media/'
_media_root_env = os.environ.get('MEDIA_ROOT', '').strip()
MEDIA_ROOT = Path(_media_root_env) if _media_root_env else (BASE_DIR.parent / 'media')

# Performance optimization
DATA_UPLOAD_MAX_MEMORY_SIZE = 5242880  # 5MB
FILE_UPLOAD_MAX_MEMORY_SIZE = 5242880  # 5MB
DATA_UPLOAD_MAX_NUMBER_FIELDS = 1000
DATA_UPLOAD_MAX_NUMBER_FILES = 10

# Cache configuration for production
CACHE_TTL = 60 * 60  # 1 hour

# JWT settings for production (more restrictive)
SIMPLE_JWT['ACCESS_TOKEN_LIFETIME'] = timedelta(minutes=60)
SIMPLE_JWT['REFRESH_TOKEN_LIFETIME'] = timedelta(days=1)

# API Documentation in production
SPECTACULAR_SETTINGS = {
    'TITLE': 'DIGIT-HAB CRM API',
    'DESCRIPTION': 'API de gestion CRM pour l\'immobilier',
    'VERSION': '1.0.0',
    'SERVE_INCLUDE_SCHEMA': False,
    'COMPONENT_SPLIT_REQUEST': True,
    'COMPONENT_SPLIT_RESPONSE': True,
    'SORT_OPERATIONS': False,
    # Disable interactive features in production
    'SWAGGER_UI_SETTINGS': {
        'persistAuthorization': False,
        'displayRequestDuration': False,
        'filter': True,
        'showExtensions': False,
        'showCommonExtensions': False,
    }
}

# Security headers
SECURE_REFERRER_POLICY = 'strict-origin-when-cross-origin'
SECURE_CROSS_ORIGIN_OPENER_POLICY = 'same-origin'
SECURE_CROSS_ORIGIN_EMBEDDER_POLICY = 'require-corp'