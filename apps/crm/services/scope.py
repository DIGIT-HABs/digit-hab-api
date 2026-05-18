"""
Filtres de périmètre CRM alignés sur les ViewSets (clients, leads, réservations).
"""

from django.db.models import Q

from apps.crm.models import ClientProfile, Lead, ClientInteraction
from apps.reservations.models import Reservation


def user_agency(user):
    return getattr(getattr(user, 'profile', None), 'agency', None)


def client_profiles_for_user(user):
    """
    Même périmètre que ClientProfileViewSet.get_queryset pour un agent.
    """
    qs = ClientProfile.objects.select_related('user')
    role = getattr(user, 'role', None)

    if role == 'admin' or getattr(user, 'is_staff', False):
        return qs

    if role == 'agent':
        agency = user_agency(user)
        if not agency:
            return qs.none()
        reservation_client_ids = Reservation.objects.filter(
            client_profile__isnull=False,
            property__agency=agency,
        ).values_list('client_profile_id', flat=True).distinct()
        return qs.filter(
            Q(user__profile__agency=agency) | Q(id__in=reservation_client_ids)
        ).distinct()

    if role == 'client':
        return qs.filter(user=user)

    return qs.none()


def leads_for_user(user):
    qs = Lead.objects.all()
    role = getattr(user, 'role', None)

    if role == 'admin' or getattr(user, 'is_staff', False):
        return qs

    if role == 'agent':
        agency = user_agency(user)
        if agency:
            return qs.filter(agency=agency)
        return qs.none()

    return qs.none()


def reservations_for_user(user):
    qs = Reservation.objects.all()
    role = getattr(user, 'role', None)

    if getattr(user, 'is_staff', False) or role == 'admin':
        return qs

    if role in ('agent', 'manager'):
        agency = user_agency(user)
        if agency:
            return qs.filter(property__agency=agency)
        return qs.filter(assigned_agent=user)

    return qs.none()


def interactions_for_clients(clients_qs, since=None):
    client_user_ids = clients_qs.values_list('user_id', flat=True)
    qs = ClientInteraction.objects.filter(client_id__in=client_user_ids)
    if since is not None:
        qs = qs.filter(created_at__gte=since)
    return qs
