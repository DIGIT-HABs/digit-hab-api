"""
Services for CRM app (Phase 1 - Post-deployment).
"""

from .reporting import ReportingService
from .scope import (
    client_profiles_for_user,
    leads_for_user,
    reservations_for_user,
    interactions_for_clients,
    user_agency,
)

__all__ = [
    'ReportingService',
    'client_profiles_for_user',
    'leads_for_user',
    'reservations_for_user',
    'interactions_for_clients',
    'user_agency',
]
