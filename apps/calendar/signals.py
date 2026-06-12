"""
Signaux pour le système de calendrier intelligent
Automatisation de la planification et gestion des conflits
"""

import logging
from django.db.models.signals import post_save, pre_save, post_delete
from django.dispatch import receiver
from django.contrib.auth import get_user_model
from django.utils import timezone
from datetime import date, timedelta

from .models import VisitSchedule, TimeSlot, CalendarConflict
from .services import CalendarService, ConflictDetectionService

User = get_user_model()
logger = logging.getLogger(__name__)


# ============================================================================
# SIGNALS POUR LES RÉSERVATIONS
# ============================================================================

@receiver(post_save, sender='reservations.Reservation')
def handle_reservation_for_scheduling(sender, instance, created, **kwargs):
    """Gère automatiquement la planification lors de la création de réservation"""
    
    if created and instance.scheduled_date:
        try:
            # Créer automatiquement une planification intelligente
            schedule = CalendarService.create_smart_schedule(
                reservation_id=str(instance.id),
                client_preferences=None,
                algorithm='best_match'
            )
            
            if schedule:
                logger.info(f"Planification automatique créée pour réservation {instance.id}")
            else:
                schedule = CalendarService.ensure_schedule_from_reservation(instance)
                if schedule:
                    logger.info(
                        f"Planification simple créée pour réservation {instance.id}"
                    )
                else:
                    logger.warning(
                        f"Impossible de créer une planification pour {instance.id}"
                    )
                
        except Exception as e:
            logger.error(f"Erreur lors de la planification automatique: {e}")


@receiver(post_save, sender='reservations.Reservation')
def handle_reservation_status_change(sender, instance, created, **kwargs):
    """Met à jour les créneaux selon le statut de la réservation"""
    
    if not created:
        try:
            # Récupérer l'ancienne instance
            old_instance = sender.objects.get(id=instance.id)
            
            if old_instance.status != instance.status:
                # La réservation a été annulée
                if instance.status == 'cancelled':
                    # Libérer tous les créneaux associés
                    TimeSlot.objects.filter(
                        reservation=instance
                    ).update(status='available', reservation=None)
                    
                    # Annuler la planification associée
                    if hasattr(instance, 'schedule'):
                        instance.schedule.status = 'cancelled'
                        instance.schedule.save()
                
                # La réservation a été confirmée
                elif instance.status == 'confirmed':
                    if hasattr(instance, 'schedule'):
                        instance.schedule.status = 'confirmed'
                        instance.schedule.confirmed_at = timezone.now()
                        instance.schedule.save()
                
        except Exception as e:
            logger.error(f"Erreur lors de la mise à jour du statut: {e}")


# ============================================================================
# SIGNALS POUR LES PLANIFICATIONS
# ============================================================================

@receiver(post_save, sender=VisitSchedule)
def handle_schedule_created(sender, instance, created, **kwargs):
    """Gère la création d'une nouvelle planification"""
    
    if created:
        try:
            # Créer le créneau associé
            time_slot, created_slot = TimeSlot.objects.get_or_create(
                user=instance.agent,
                date=instance.scheduled_date,
                start_time=instance.scheduled_start_time,
                end_time=instance.scheduled_end_time,
                defaults={
                    'status': 'booked',
                    'reservation': instance.reservation
                }
            )
            
            if not created_slot:
                # Le créneau existait déjà, le mettre à jour
                time_slot.status = 'booked'
                time_slot.reservation = instance.reservation
                time_slot.save()
            
            # Détecter les conflits
            conflicts = ConflictDetectionService.detect_conflicts(instance)
            if conflicts:
                logger.warning(f"Conflits détectés pour la planification {instance.id}: {len(conflicts)}")
            
        except Exception as e:
            logger.error(f"Erreur lors de la création du créneau: {e}")


@receiver(post_save, sender=VisitSchedule)
def handle_schedule_status_change(sender, instance, created, **kwargs):
    """Gère les changements de statut des planifications"""
    
    if not created:
        try:
            # Récupérer l'ancienne instance
            old_instance = sender.objects.get(id=instance.id)
            
            if old_instance.status != instance.status:
                if instance.status in ['cancelled', 'no_show']:
                    # Libérer le créneau
                    TimeSlot.objects.filter(
                        user=instance.agent,
                        date=instance.scheduled_date,
                        start_time=instance.scheduled_start_time,
                        reservation=instance.reservation
                    ).update(status='available', reservation=None)
                
                elif instance.status == 'completed':
                    # Marquer la visite comme terminée dans le créneau
                    TimeSlot.objects.filter(
                        user=instance.agent,
                        date=instance.scheduled_date,
                        start_time=instance.scheduled_start_time,
                        reservation=instance.reservation
                    ).update(status='blocked')  # Garde la trace de la visite terminée
                
        except Exception as e:
            logger.error(f"Erreur lors du changement de statut: {e}")


@receiver(post_save, sender=VisitSchedule)
def handle_schedule_modification(sender, instance, created, **kwargs):
    """Gère les modifications de planification"""
    
    if not created:
        try:
            # Vérifier si les horaires ont changé
            old_instance = sender.objects.get(id=instance.id)
            
            if (old_instance.scheduled_date != instance.scheduled_date or
                old_instance.scheduled_start_time != instance.scheduled_start_time or
                old_instance.scheduled_end_time != instance.scheduled_end_time):
                
                # Ancien créneau
                old_slot = TimeSlot.objects.filter(
                    user=instance.agent,
                    date=old_instance.scheduled_date,
                    start_time=old_instance.scheduled_start_time,
                    reservation=instance.reservation
                ).first()
                
                if old_slot:
                    old_slot.status = 'available'
                    old_slot.reservation = None
                    old_slot.save()
                
                # Nouveau créneau
                new_slot, created_slot = TimeSlot.objects.get_or_create(
                    user=instance.agent,
                    date=instance.scheduled_date,
                    start_time=instance.scheduled_start_time,
                    end_time=instance.scheduled_end_time,
                    defaults={
                        'status': 'booked',
                        'reservation': instance.reservation
                    }
                )
                
                if not created_slot and new_slot.status != 'booked':
                    new_slot.status = 'booked'
                    new_slot.reservation = instance.reservation
                    new_slot.save()
                
                # Détecter les nouveaux conflits
                conflicts = ConflictDetectionService.detect_conflicts(instance)
                if conflicts:
                    logger.warning(f"Nouveaux conflits détectés après modification: {len(conflicts)}")
        
        except Exception as e:
            logger.error(f"Erreur lors de la modification de planification: {e}")


# ============================================================================
# SIGNALS POUR LES CRÉNEAUX
# ============================================================================

@receiver(post_save, sender=TimeSlot)
def handle_time_slot_creation(sender, instance, created, **kwargs):
    """Gère la création de créneaux"""
    
    if created and instance.status == 'available':
        try:
            # Vérifier les conflits avec les planifications existantes
            conflicts = VisitSchedule.objects.filter(
                agent=instance.user,
                scheduled_date=instance.date,
                status__in=['scheduled', 'confirmed']
            ).filter(
                scheduled_start_time__lt=instance.end_time,
                scheduled_end_time__gt=instance.start_time
            )
            
            if conflicts.exists():
                # Créer un conflit
                conflict = CalendarConflict.objects.create(
                    schedule1=conflicts.first(),  # Prendre la première planification en conflit
                    schedule2=None,  # Conflit avec un créneau libre
                    conflict_type='slot_overlap',
                    severity='medium',
                    description=f"Créneau disponible en conflit avec planification existante"
                )
                
                logger.info(f"Conflit de créneau détecté: {conflict.id}")
        
        except Exception as e:
            logger.error(f"Erreur lors de la vérification des conflits de créneau: {e}")


# ============================================================================
# NETTOYAGE AUTOMATIQUE
# ============================================================================

@receiver(post_save, sender=VisitSchedule)
def cleanup_expired_schedules(sender, instance, **kwargs):
    """Nettoie automatiquement les planifications expirées"""
    
    try:
        from django.utils import timezone
        from datetime import timedelta
        
        # Marquer comme "no_show" les visites non confirmées qui sont passées
        cutoff_time = timezone.now() - timedelta(hours=2)  # 2h de marge
        
        expired_schedules = VisitSchedule.objects.filter(
            scheduled_date__lt=date.today(),
            status__in=['scheduled', 'pending']
        )
        
        if expired_schedules.exists():
            expired_count = expired_schedules.update(status='no_show')
            logger.info(f"{expired_count} planifications expirées marquées comme 'no_show'")
    
    except Exception as e:
        logger.error(f"Erreur lors du nettoyage des planifications expirées: {e}")


@receiver(post_delete, sender=VisitSchedule)
def handle_schedule_deletion(sender, instance, **kwargs):
    """Gère la suppression d'une planification"""
    
    try:
        # Libérer le créneau associé
        TimeSlot.objects.filter(
            user=instance.agent,
            date=instance.scheduled_date,
            start_time=instance.scheduled_start_time,
            reservation=instance.reservation
        ).update(status='available', reservation=None)
        
        # Supprimer les conflits liés
        CalendarConflict.objects.filter(
            schedule1=instance
        ).delete()
        
        CalendarConflict.objects.filter(
            schedule2=instance
        ).delete()
    
    except Exception as e:
        logger.error(f"Erreur lors de la suppression de planification: {e}")


# ============================================================================
# OPTIMISATION AUTOMATIQUE
# ============================================================================

@receiver(post_save, sender=VisitSchedule)
def auto_optimize_on_schedule(sender, instance, created, **kwargs):
    """Optimise automatiquement les plannings lors de la création"""
    
    if created and instance.status == 'scheduled':
        try:
            # Optimisation légère pour éviter de surcharger le système
            # Ne pas optimiser si c'est une modification mineure
            
            # Pour l'instant, on se contente de logger
            # L'optimisation sera déclenchée manuellement ou par tâche
            logger.debug(f"Nouvelle planification créée: {instance.id}")
        
        except Exception as e:
            logger.error(f"Erreur lors de l'auto-optimisation: {e}")


# ============================================================================
# NOTIFICATIONS AUTOMATIQUES
# ============================================================================

@receiver(post_save, sender=VisitSchedule)
def send_schedule_notifications(sender, instance, created, **kwargs):
    """Envoie des notifications automatiques pour les planifications"""
    
    try:
        # Importer le service de notifications (éviter l'import circulaire)
        from apps.notifications.services import NotificationService
        from django.contrib.contenttypes.models import ContentType
        
        if created:
            # Notification de nouvelle planification
            NotificationService.create_notification(
                recipient_ids=[str(instance.client.id)],
                title="Nouvelle visite planifiée",
                message=f"Votre visite pour {instance.property.title} est planifiée le {instance.scheduled_date} à {instance.scheduled_start_time}",
                notification_type='info',
                priority='normal',
                content_type_id=ContentType.objects.get_for_model(instance).id,
                object_id=instance.id,
                channels=['websocket', 'in_app', 'email']
            )
            
            # Notification à l'agent
            if instance.agent != instance.client:
                NotificationService.create_notification(
                    recipient_ids=[str(instance.agent.id)],
                    title="Nouvelle visite assignée",
                    message=f"Une nouvelle visite vous a été assignée: {instance.property.title} le {instance.scheduled_date}",
                    notification_type='info',
                    priority='normal',
                    content_type_id=ContentType.objects.get_for_model(instance).id,
                    object_id=instance.id,
                    channels=['websocket', 'in_app']
                )
        
        elif not created:
            # Vérifier les changements importants
            old_instance = sender.objects.get(id=instance.id)
            
            if old_instance.scheduled_date != instance.scheduled_date:
                # Date modifiée
                NotificationService.create_notification(
                    recipient_ids=[str(instance.client.id)],
                    title="Visite reportée",
                    message=f"Votre visite pour {instance.property.title} a été reportée au {instance.scheduled_date}",
                    notification_type='warning',
                    priority='high',
                    content_type_id=ContentType.objects.get_for_model(instance).id,
                    object_id=instance.id,
                    channels=['websocket', 'in_app', 'email']
                )
            
            elif old_instance.status != instance.status:
                # Statut modifié
                if instance.status == 'confirmed':
                    message = "Votre visite a été confirmée"
                elif instance.status == 'cancelled':
                    message = "Votre visite a été annulée"
                elif instance.status == 'completed':
                    message = "Votre visite a été marquée comme terminée"
                else:
                    message = f"Statut de votre visite mis à jour: {instance.get_status_display()}"
                
                NotificationService.create_notification(
                    recipient_ids=[str(instance.client.id)],
                    title="Mise à jour de votre visite",
                    message=message,
                    notification_type='info',
                    priority='normal',
                    content_type_id=ContentType.objects.get_for_model(instance).id,
                    object_id=instance.id,
                    channels=['websocket', 'in_app', 'email']
                )
    
    except Exception as e:
        logger.error(f"Erreur lors de l'envoi des notifications de planification: {e}")


# ============================================================================
# VALIDATION ET VÉRIFICATIONS
# ============================================================================

@receiver(post_save, sender=VisitSchedule)
def validate_schedule(sender, instance, **kwargs):
    """Valide les planifications"""
    
    try:
        # Vérifier que l'agent travaille ce jour-là
        working_hours = instance.agent.working_hours.filter(
            day_of_week=instance.scheduled_date.weekday(),
            is_working=True
        ).first()
        
        if not working_hours:
            logger.warning(f"Planification {instance.id} en dehors des horaires de travail")
            return
        
        # Vérifier que l'horaire est dans les heures de travail
        if (instance.scheduled_start_time < working_hours.start_time or
            instance.scheduled_end_time > working_hours.end_time):
            logger.warning(f"Planification {instance.id} en dehors des heures de travail")
        
        # Vérifier les pauses
        if (working_hours.break_start and working_hours.break_end and
            working_hours.break_start <= instance.scheduled_start_time < working_hours.break_end):
            logger.warning(f"Planification {instance.id} pendant une pause")
    
    except Exception as e:
        logger.error(f"Erreur lors de la validation de planification: {e}")