"""
Création automatique des commissions liées aux réservations.
"""

from decimal import Decimal
import logging

from django.utils import timezone

from .models import Commission

logger = logging.getLogger(__name__)

DEFAULT_RATE = Decimal('3.00')
DEFAULT_VISIT_FLAT = Decimal('50000')


def _agency_settings(agency):
    return getattr(agency, 'settings', None) or {}


def get_agency_commission_rate(agency, default=DEFAULT_RATE) -> Decimal:
    raw = _agency_settings(agency).get('commission_rate')
    if raw is None:
        return default
    try:
        return Decimal(str(raw))
    except Exception:
        return default


def get_visit_commission_flat(agency, default=DEFAULT_VISIT_FLAT) -> Decimal:
    raw = _agency_settings(agency).get('visit_commission_amount')
    if raw is None:
        return default
    try:
        return Decimal(str(raw))
    except Exception:
        return default


def resolve_commission_type(reservation, contract_type=None) -> str:
    if contract_type == 'sale' or getattr(reservation, 'reservation_type', None) == 'purchase':
        return 'sale'
    if contract_type == 'rent' or getattr(reservation, 'reservation_type', None) == 'rent':
        return 'rental'
    if getattr(reservation, 'reservation_type', None) == 'visit':
        return 'bonus'
    return 'sale'


def resolve_commission_base_and_rate(reservation, agency, contract_type=None):
    """Retourne (base_amount, commission_rate)."""
    rtype = getattr(reservation, 'reservation_type', None)

    if rtype == 'visit':
        return get_visit_commission_flat(agency), Decimal('100')

    base = reservation.purchase_price or reservation.amount
    if base is None and reservation.property and reservation.property.price:
        if rtype in ('rent', 'purchase', 'sale'):
            base = reservation.property.price
    if base is None:
        base = Decimal('0')

    return Decimal(str(base)), get_agency_commission_rate(agency)


def create_commission_for_reservation(reservation, *, source='auto', contract_type=None):
    """
    Crée une commission pending si possible.
    Retourne la Commission ou None.
    """
    agent = getattr(reservation, 'assigned_agent', None)
    prop = getattr(reservation, 'property', None)
    if not agent or not prop or not prop.agency_id:
        return None

    if Commission.objects.filter(reservation=reservation, agent=agent).exists():
        return None

    base_amount, commission_rate = resolve_commission_base_and_rate(
        reservation, prop.agency, contract_type=contract_type
    )
    if base_amount <= 0 and commission_rate < Decimal('100'):
        logger.info(
            'Commission ignorée (montant de base 0) reservation=%s type=%s',
            reservation.id,
            getattr(reservation, 'reservation_type', None),
        )
        return None

    commission = Commission(
        agent=agent,
        agency=prop.agency,
        property=prop,
        reservation=reservation,
        commission_type=resolve_commission_type(reservation, contract_type),
        base_amount=base_amount,
        commission_rate=commission_rate,
        status='pending',
        transaction_date=timezone.now(),
        notes=f"Commission générée automatiquement ({source}).",
    )
    commission.save()
    return commission
