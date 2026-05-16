"""
Django WSGI config for digit_hab_crm project.
"""

import os
from django.core.wsgi import get_wsgi_application

# En prod (Gunicorn), préférer settings.prod si la variable n'est pas déjà définie (systemd / .env)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'digit_hab_crm.settings.prod')

application = get_wsgi_application()