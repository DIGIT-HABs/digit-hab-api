"""
Script pour créer un utilisateur admin (role=admin)
"""

import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'digit_hab_crm.settings.prod')
django.setup()

from apps.auth.models import User
from django.utils import timezone

print("=" * 60)
print("🚀 Création de l'utilisateur Administrateur")
print("=" * 60)
print("")

# ════════════════════════════════════════════════════════
# Création de l'utilisateur admin
# ════════════════════════════════════════════════════════

username = "admin"
email = "admin@digit-hab.com"
first_name = "Admin"
last_name = "Principal"
password = "AdminPass123!"

print("🔐 Création de l'utilisateur admin...")

user, created = User.objects.get_or_create(
    username=username,
    defaults={
        'email': email,
        'first_name': first_name,
        'last_name': last_name,
        'role': 'admin',
        'is_staff': True,
        'is_superuser': True,
        'is_active': True,
        'is_verified': True,
        'date_joined': timezone.now(),
    }
)
if created:
    user.set_password(password)
    user.save()
    print(f"✅ Utilisateur admin créé : {user.username} ({user.email})")
else:
    # Mettre à jour le rôle si déjà existant
    user.role = 'admin'
    user.is_staff = True
    user.is_superuser = True
    user.is_active = True
    user.is_verified = True
    user.set_password(password)
    user.save()
    print(f"♻️ Utilisateur existant promu admin : {user.username} ({user.email})")

print("")
print("🔐 Identifiants Admin:")
print(f"   Username: {username}")
print(f"   Password: {password}")
print("")
