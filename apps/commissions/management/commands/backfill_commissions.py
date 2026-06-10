"""
Crée les commissions manquantes pour les réservations déjà terminées.
Usage: python manage.py backfill_commissions [--dry-run]
"""

from django.core.management.base import BaseCommand
from django.db.models import Q

from apps.commissions.models import Commission
from apps.reservations.models import Reservation
from apps.commissions.services import create_commission_for_reservation


class Command(BaseCommand):
    help = 'Génère les commissions pour réservations terminées ou payées sans commission.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Affiche ce qui serait créé sans écrire en base.',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        qs = Reservation.objects.filter(
            Q(status='completed') | Q(payment_status='paid')
        ).select_related(
            'assigned_agent', 'property', 'property__agency'
        ).distinct()
        created = 0
        skipped = 0

        for reservation in qs:
            if dry_run:
                agent = reservation.assigned_agent
                if not agent or not reservation.property_id:
                    skipped += 1
                    self.stdout.write(f'[skip] {reservation.id} — agent ou bien manquant')
                    continue
                from apps.commissions.models import Commission
                if Commission.objects.filter(
                    reservation=reservation, agent=agent
                ).exists():
                    skipped += 1
                    continue
                self.stdout.write(
                    f'[would create] {reservation.id} '
                    f'type={reservation.reservation_type} agent={agent.get_full_name()}'
                )
                created += 1
                continue

            result = create_commission_for_reservation(
                reservation,
                source='backfill',
            )
            if result:
                created += 1
                self.stdout.write(
                    self.style.SUCCESS(
                        f'Commission {result.id} — {result.commission_amount} FCFA '
                        f'({reservation.id})'
                    )
                )
            else:
                skipped += 1

        approved = 0
        if not dry_run:
            for commission in Commission.objects.filter(
                status='pending',
                reservation__payment_status='paid',
            ).select_related('reservation'):
                commission.approve()
                approved += 1

        self.stdout.write(
            self.style.NOTICE(
                f'Terminé: {created} créée(s), {skipped} ignorée(s)'
                + (f', {approved} approuvée(s) (réservation payée)' if approved else '')
                + (' (dry-run)' if dry_run else '')
            )
        )
