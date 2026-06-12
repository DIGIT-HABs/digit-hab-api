"""
Services pour le système de calendrier intelligent
Algorithmes de planification automatique et optimisation
"""

import math
import logging
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, date, time, timedelta
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db.models import Q
from django.utils import timezone
from geopy.distance import geodesic
from geopy.geocoders import Nominatim

from .models import (
    WorkingHours, TimeSlot, ClientAvailability, VisitSchedule,
    CalendarConflict, SchedulingPreference, ScheduleMetrics
)
from apps.reservations.models import Reservation
from apps.properties.models import Property
from apps.crm.models import ClientProfile

User = get_user_model()
logger = logging.getLogger(__name__)


class RouteOptimizationService:
    """Service d'optimisation de route avec algorithmes"""
    
    @staticmethod
    def calculate_distance(point1: Tuple[float, float], point2: Tuple[float, float]) -> float:
        """Calcule la distance entre deux points géographiques en km"""
        return geodesic(point1, point2).kilometers
    
    @staticmethod
    def calculate_travel_time(distance_km: float, speed_kmh: float = 50) -> int:
        """Calcule le temps de trajet en minutes"""
        return int((distance_km / speed_kmh) * 60)
    
    @staticmethod
    def optimize_route_visits(visits: List[Dict[str, Any]], start_point: Tuple[float, float]) -> List[Dict[str, Any]]:
        """Optimise l'ordre des visites pour minimiser la distance totale"""
        if len(visits) <= 1:
            return visits
        
        # Algorithme du nearest neighbor amélioré
        unvisited = visits.copy()
        optimized_route = []
        current_point = start_point
        total_distance = 0
        
        while unvisited:
            # Trouver la visite la plus proche
            nearest_visit = None
            min_distance = float('inf')
            
            for visit in unvisited:
                if 'coordinates' in visit:
                    distance = RouteOptimizationService.calculate_distance(
                        current_point, visit['coordinates']
                    )
                    if distance < min_distance:
                        min_distance = distance
                        nearest_visit = visit
            
            if nearest_visit:
                optimized_route.append(nearest_visit)
                unvisited.remove(nearest_visit)
                
                if 'coordinates' in nearest_visit:
                    current_point = nearest_visit['coordinates']
                    total_distance += min_distance
        
        # Calculer les temps de trajet optimisés
        for i, visit in enumerate(optimized_route):
            if i == 0:
                # Première visite depuis le point de départ
                if 'coordinates' in visit:
                    visit['travel_time_from_previous'] = RouteOptimizationService.calculate_travel_time(
                        RouteOptimizationService.calculate_distance(start_point, visit['coordinates'])
                    )
            else:
                # Visites suivantes
                prev_visit = optimized_route[i-1]
                if 'coordinates' in visit and 'coordinates' in prev_visit:
                    distance = RouteOptimizationService.calculate_distance(
                        prev_visit['coordinates'], visit['coordinates']
                    )
                    visit['travel_time_from_previous'] = RouteOptimizationService.calculate_travel_time(distance)
                    visit['cumulative_travel_time'] = (
                        prev_visit.get('cumulative_travel_time', 0) + 
                        visit['travel_time_from_previous']
                    )
        
        return optimized_route
    
    @staticmethod
    def get_property_coordinates(property_obj: Property) -> Optional[Tuple[float, float]]:
        """Récupère les coordonnées géographiques d'une propriété"""
        try:
            if property_obj.latitude and property_obj.longitude:
                return (property_obj.latitude, property_obj.longitude)
            
            # Géocodage basé sur l'adresse
            if property_obj.address:
                geolocator = Nominatim(user_agent="digit_hab_crm")
                location = geolocator.geocode(str(property_obj.address))
                if location:
                    return (location.latitude, location.longitude)
        except Exception as e:
            logger.error(f"Erreur géocodage propriété {property_obj.id}: {e}")
        
        return None


class SchedulingAlgorithmService:
    """Service des algorithmes de planification intelligente"""
    
    @staticmethod
    def find_first_available_slot(
        agent_id: str,
        preferred_date: Optional[date] = None,
        duration_minutes: int = 60,
        client_preferences: Optional[ClientAvailability] = None
    ) -> Optional[Dict[str, Any]]:
        """Trouve le premier créneau disponible"""
        
        search_date = preferred_date or date.today()
        max_search_days = 30
        
        for _ in range(max_search_days):
            # Vérifier les horaires de travail
            working_hours = WorkingHours.objects.filter(
                user_id=agent_id,
                day_of_week=search_date.weekday(),
                is_working=True,
                is_active=True
            ).first()
            
            if not working_hours:
                search_date += timedelta(days=1)
                continue
            
            # Vérifier les créneaux déjà pris
            occupied_slots = TimeSlot.objects.filter(
                user_id=agent_id,
                date=search_date,
                status__in=['booked', 'blocked']
            )
            
            # Générer les créneaux disponibles
            available_slots = SchedulingAlgorithmService._generate_time_slots(
                working_hours, search_date, duration_minutes, occupied_slots
            )
            
            if available_slots:
                return {
                    'date': search_date,
                    'start_time': available_slots[0]['start_time'],
                    'end_time': available_slots[0]['end_time'],
                    'score': 1.0  # Score parfait pour le premier disponible
                }
            
            search_date += timedelta(days=1)
        
        return None
    
    @staticmethod
    def find_best_match_slot(
        agent_id: str,
        client_availability: ClientAvailability,
        property_obj: Property,
        agent_preferences: Optional[SchedulingPreference] = None
    ) -> List[Dict[str, Any]]:
        """Trouve les meilleurs créneaux selon les préférences"""
        
        candidates = []
        search_start = max(client_availability.preferred_date, date.today())
        search_end = search_start + timedelta(days=14)  # Recherche sur 2 semaines
        
        current_date = search_start
        while current_date <= search_end:
            score = SchedulingAlgorithmService._calculate_match_score(
                current_date, client_availability, property_obj, agent_preferences
            )
            
            if score > 0.5:  # Seuil minimum de correspondance
                slot_info = SchedulingAlgorithmService._get_time_slots_for_date(
                    agent_id, current_date, client_availability.preferred_duration
                )
                
                for slot in slot_info:
                    slot['match_score'] = score
                    slot['match_factors'] = {
                        'date_preference': 1.0 if current_date == client_availability.preferred_date else 0.8,
                        'time_preference': SchedulingAlgorithmService._calculate_time_preference(
                            slot['start_time'], client_availability.preferred_time_slot
                        ),
                        'property_match': SchedulingAlgorithmService._calculate_property_match(
                            property_obj, agent_preferences
                        )
                    }
                    candidates.append(slot)
            
            current_date += timedelta(days=1)
        
        # Trier par score décroissant
        candidates.sort(key=lambda x: x['match_score'], reverse=True)
        return candidates[:3]  # Top 3
    
    @staticmethod
    def find_optimal_route_slots(
        agent_id: str,
        visits: List[Dict[str, Any]],
        date: date
    ) -> Dict[str, Any]:
        """Trouve les créneaux optimaux pour une route"""
        
        if len(visits) <= 1:
            return SchedulingAlgorithmService._get_time_slots_for_date(agent_id, date, 60)[0]
        
        # Obtenir les coordonnées des propriétés
        visit_data = []
        for visit in visits:
            if isinstance(visit, dict) and 'property_id' in visit:
                try:
                    property_obj = Property.objects.get(id=visit['property_id'])
                    coordinates = RouteOptimizationService.get_property_coordinates(property_obj)
                    if coordinates:
                        visit_data.append({
                            'visit': visit,
                            'coordinates': coordinates
                        })
                except Property.DoesNotExist:
                    continue
        
        if not visit_data:
            return None
        
        # Point de départ (bureau ou domicile de l'agent)
        start_point = (48.8566, 2.3522)  # Paris par défaut, devrait être configuré
        
        # Optimiser la route
        optimized_visits = RouteOptimizationService.optimize_route_visits(visit_data, start_point)
        
        # Calculer les créneaux optimaux
        current_time = time(9, 0)  # 9h par défaut
        scheduled_visits = []
        
        for visit in optimized_visits:
            # Durée de la visite
            duration = visit.get('duration_minutes', 60)
            end_time = (datetime.combine(date.today(), current_time) + timedelta(minutes=duration)).time()
            
            # Temps de trajet depuis la visite précédente
            if visit.get('travel_time_from_previous'):
                current_time = (datetime.combine(date.today(), current_time) + 
                              timedelta(minutes=visit['travel_time_from_previous'])).time()
            
            visit_slot = {
                'visit': visit['visit'],
                'start_time': current_time,
                'end_time': end_time,
                'travel_time': visit.get('travel_time_from_previous', 0),
                'cumulative_travel_time': visit.get('cumulative_travel_time', 0)
            }
            
            scheduled_visits.append(visit_slot)
            current_time = end_time
        
        return {
            'visits': scheduled_visits,
            'total_travel_time': sum(v['travel_time'] for v in scheduled_visits),
            'estimated_end_time': current_time
        }
    
    @staticmethod
    def calculate_load_balancing(agent_ids: List[str], new_visits: List[Dict[str, Any]]) -> Dict[str, str]:
        """Répartit la charge entre les agents"""
        
        agent_loads = {}
        for agent_id in agent_ids:
            # Compter les visites du jour
            today_visits = VisitSchedule.objects.filter(
                agent_id=agent_id,
                scheduled_date=date.today(),
                status__in=['scheduled', 'confirmed', 'in_progress']
            ).count()
            agent_loads[agent_id] = today_visits
        
        assignments = {}
        
        for visit in new_visits:
            # Trouver l'agent avec la plus petite charge
            min_load_agent = min(agent_loads.keys(), key=lambda x: agent_loads[x])
            assignments[str(visit.get('id', visit.get('property_id', '')))] = min_load_agent
            agent_loads[min_load_agent] += 1
        
        return assignments
    
    @staticmethod
    def _generate_time_slots(
        working_hours: WorkingHours,
        target_date: date,
        duration_minutes: int,
        occupied_slots: List[TimeSlot]
    ) -> List[Dict[str, Any]]:
        """Génère les créneaux disponibles pour une date donnée"""
        
        slots = []
        current_time = working_hours.start_time
        end_time = working_hours.end_time
        
        while current_time < end_time:
            slot_end = (datetime.combine(date.today(), current_time) + 
                       timedelta(minutes=duration_minutes)).time()
            
            # Vérifier si le créneau dépasse les horaires de travail
            if slot_end > end_time:
                break
            
            # Vérifier les pauses
            if (working_hours.break_start and working_hours.break_end and
                working_hours.break_start <= current_time < working_hours.break_end):
                current_time = working_hours.break_end
                continue
            
            # Vérifier les conflits avec les créneaux occupés
            conflict = False
            for occupied in occupied_slots:
                if not (slot_end <= occupied.start_time or current_time >= occupied.end_time):
                    conflict = True
                    break
            
            if not conflict:
                slots.append({
                    'start_time': current_time,
                    'end_time': slot_end
                })
            
            current_time = slot_end
        
        return slots
    
    @staticmethod
    def _calculate_match_score(
        date: date,
        client_availability: ClientAvailability,
        property_obj: Property,
        agent_preferences: Optional[SchedulingPreference] = None
    ) -> float:
        """Calcule un score de correspondance pour un créneau"""
        
        score = 0.0
        factors = 0
        
        # Score de date préférée
        if date == client_availability.preferred_date:
            score += 1.0
        factors += 1
        
        # Score de temps préféré
        time_preference_score = SchedulingAlgorithmService._calculate_time_preference(
            None, client_availability.preferred_time_slot
        )
        score += time_preference_score
        factors += 1
        
        # Score de propriété
        property_score = SchedulingAlgorithmService._calculate_property_match(
            property_obj, agent_preferences
        )
        score += property_score
        factors += 1
        
        return score / factors if factors > 0 else 0.0
    
    @staticmethod
    def _calculate_time_preference(start_time: Optional[time], time_preference: str) -> float:
        """Calcule le score pour la préférence de temps"""
        
        if time_preference == 'any':
            return 1.0
        
        if not start_time:
            return 0.5  # Score neutre si pas d'heure précise
        
        if time_preference == 'morning' and 8 <= start_time.hour < 12:
            return 1.0
        elif time_preference == 'afternoon' and 12 <= start_time.hour < 17:
            return 1.0
        elif time_preference == 'evening' and 17 <= start_time.hour < 20:
            return 1.0
        else:
            return 0.3  # Score faible pour les créneaux non préférés
    
    @staticmethod
    def _calculate_property_match(property_obj: Property, agent_preferences: Optional[SchedulingPreference]) -> float:
        """Calcule le score de correspondance avec les préférences d'agent"""
        
        if not agent_preferences:
            return 0.5  # Score neutre
        
        score = 0.0
        
        # Type de propriété
        if property_obj.property_type and agent_preferences.preferred_property_types:
            if property_obj.property_type in agent_preferences.preferred_property_types:
                score += 0.3
        
        # Zone géographique
        if agent_preferences.working_radius and property_obj.address:
            # Calculer distance du centre de travail (simplifié)
            score += 0.2  # Score pour zone dans le rayon
        
        return min(score, 1.0)  # Maximum 1.0
    
    @staticmethod
    def _get_time_slots_for_date(agent_id: str, target_date: date, duration_minutes: int) -> List[Dict[str, Any]]:
        """Récupère les créneaux disponibles pour une date"""
        
        working_hours = WorkingHours.objects.filter(
            user_id=agent_id,
            day_of_week=target_date.weekday(),
            is_working=True,
            is_active=True
        ).first()
        
        if not working_hours:
            return []
        
        occupied_slots = TimeSlot.objects.filter(
            user_id=agent_id,
            date=target_date,
            status__in=['booked', 'blocked']
        )
        
        return SchedulingAlgorithmService._generate_time_slots(
            working_hours, target_date, duration_minutes, occupied_slots
        )


class ConflictDetectionService:
    """Service de détection et résolution de conflits"""
    
    @staticmethod
    def detect_conflicts(schedule: VisitSchedule) -> List[CalendarConflict]:
        """Détecte les conflits pour une planification"""
        
        conflicts = []
        
        # Conflits temporels - autres visites du même agent
        overlapping_visits = VisitSchedule.objects.filter(
            agent=schedule.agent,
            scheduled_date=schedule.scheduled_date,
            id__in=[schedule.id]  # Exclure la visite elle-même
        ).filter(
            scheduled_start_time__lt=schedule.scheduled_end_time,
            scheduled_end_time__gt=schedule.scheduled_start_time
        )
        
        for other_visit in overlapping_visits:
            conflict = CalendarConflict.objects.create(
                schedule1=schedule,
                schedule2=other_visit,
                conflict_type='time_overlap',
                severity='high',
                description=f"Congestion temporelle entre {schedule.property.title} et {other_visit.property.title}"
            )
            conflicts.append(conflict)
        
        # Conflits de propriété - même propriété au même moment
        property_conflicts = VisitSchedule.objects.filter(
            property=schedule.property,
            scheduled_date=schedule.scheduled_date,
            id__in=[schedule.id]
        ).filter(
            scheduled_start_time__lt=schedule.scheduled_end_time,
            scheduled_end_time__gt=schedule.scheduled_start_time
        )
        
        for other_visit in property_conflicts:
            conflict = CalendarConflict.objects.create(
                schedule1=schedule,
                schedule2=other_visit,
                conflict_type='property_conflict',
                severity='critical',
                description=f"Conflit de propriété : {schedule.property.title} visitée simultanément"
            )
            conflicts.append(conflict)
        
        return conflicts
    
    @staticmethod
    def suggest_resolutions(conflict: CalendarConflict) -> List[Dict[str, Any]]:
        """Suggère des résolutions pour un conflit"""
        
        suggestions = []
        
        if conflict.conflict_type == 'time_overlap':
            # Proposer de déplacer la visite la moins prioritaire
            if conflict.schedule1.priority.value < conflict.schedule2.priority.value:
                primary, secondary = conflict.schedule2, conflict.schedule1
            else:
                primary, secondary = conflict.schedule1, conflict.schedule2
            
            suggestions.append({
                'type': 'reschedule',
                'description': f'Déplacer "{secondary.property.title}"',
                'target_schedule': secondary,
                'priority': 'high'
            })
        
        elif conflict.conflict_type == 'property_conflict':
            # Proposer un créneau alternatif
            suggestions.append({
                'type': 'alternative_slot',
                'description': 'Proposer un créneau alternatif pour la même propriété',
                'target_schedule': conflict.schedule1,
                'priority': 'critical'
            })
        
        return suggestions


class CalendarService:
    """Service principal du calendrier intelligent"""

    RESERVATION_STATUS_MAP = {
        'pending': 'pending',
        'confirmed': 'confirmed',
        'cancelled': 'cancelled',
        'completed': 'completed',
        'expired': 'cancelled',
    }

    @staticmethod
    def _reservation_client_user(reservation: Reservation):
        if getattr(reservation, 'client_profile', None) and getattr(
            reservation.client_profile, 'user', None
        ):
            return reservation.client_profile.user
        return getattr(reservation, 'created_by', None)

    @staticmethod
    def ensure_schedule_from_reservation(reservation: Reservation) -> Optional[VisitSchedule]:
        """Crée une planification simple à partir d'une réservation existante."""
        try:
            if hasattr(reservation, 'schedule') and reservation.schedule_id:
                return reservation.schedule
            if not reservation.scheduled_date or not reservation.property_id:
                return None

            client_user = CalendarService._reservation_client_user(reservation)
            agent = reservation.assigned_agent
            if not client_user or not agent:
                return None

            scheduled_dt = reservation.scheduled_date
            if timezone.is_aware(scheduled_dt):
                scheduled_dt = timezone.localtime(scheduled_dt)

            start_time = scheduled_dt.time()
            duration = reservation.duration_minutes or 60
            end_dt = scheduled_dt + timedelta(minutes=duration)
            end_time = end_dt.time()

            return VisitSchedule.objects.create(
                client=client_user,
                agent=agent,
                property=reservation.property,
                reservation=reservation,
                scheduled_date=scheduled_dt.date(),
                scheduled_start_time=start_time,
                scheduled_end_time=end_time,
                matching_algorithm='best_match',
                status=CalendarService.RESERVATION_STATUS_MAP.get(
                    reservation.status, 'scheduled'
                ),
                priority='normal',
            )
        except Exception as e:
            logger.error(f"Erreur création planification depuis réservation {reservation.id}: {e}")
            return None

    @staticmethod
    def sync_schedules_for_user(user) -> int:
        """Synchronise les réservations planifiées sans VisitSchedule."""
        from apps.core.user_roles import is_platform_admin, get_user_role

        reservations = Reservation.objects.filter(
            scheduled_date__isnull=False,
            schedule__isnull=True,
        ).select_related(
            'property',
            'assigned_agent',
            'client_profile__user',
            'created_by',
        )

        role = get_user_role(user)
        if user.is_superuser or is_platform_admin(user):
            pass
        elif role in ('agent', 'manager'):
            reservations = reservations.filter(assigned_agent=user)
        elif role == 'client':
            reservations = reservations.filter(
                Q(client_profile__user=user) | Q(created_by=user)
            )
        else:
            return 0

        created = 0
        for reservation in reservations.iterator():
            if CalendarService.ensure_schedule_from_reservation(reservation):
                created += 1
        return created
    
    @staticmethod
    def create_smart_schedule(
        reservation_id: str,
        client_preferences: Optional[Dict[str, Any]] = None,
        agent_preferences: Optional[Dict[str, Any]] = None,
        algorithm: str = 'best_match'
    ) -> Optional[VisitSchedule]:
        """Crée une planification intelligente"""
        
        try:
            # Récupérer la réservation
            reservation = Reservation.objects.get(id=reservation_id)
            
            # Client User (réservation a client_profile.user ou created_by, pas .client)
            client_user = None
            if getattr(reservation, 'client_profile', None) and getattr(reservation.client_profile, 'user', None):
                client_user = reservation.client_profile.user
            elif getattr(reservation, 'created_by', None):
                client_user = reservation.created_by
            if not client_user:
                logger.warning("Réservation sans utilisateur client, planification intelligente ignorée")
                return None

            # Créer ou récupérer les disponibilités client
            client_availability = None
            if client_preferences:
                client_availability = ClientAvailability.objects.create(
                    user=client_user,
                    preferred_date=client_preferences.get('preferred_date', date.today()),
                    preferred_time_slot=client_preferences.get('preferred_time_slot', 'any'),
                    urgency=client_preferences.get('urgency', 'normal'),
                    preferred_duration=client_preferences.get('preferred_duration', 60)
                )
            
            # Trouver l'agent optimal
            agent = CalendarService._find_optimal_agent(reservation, agent_preferences)
            if not agent:
                logger.error("Aucun agent disponible trouvé")
                return None
            
            # Appliquer l'algorithme de planification
            if algorithm == 'first_available':
                slot_info = SchedulingAlgorithmService.find_first_available_slot(
                    str(agent.id),
                    client_availability.preferred_date if client_availability else None,
                    client_availability.preferred_duration if client_availability else 60
                )
            elif algorithm == 'best_match':
                slot_candidates = SchedulingAlgorithmService.find_best_match_slot(
                    str(agent.id),
                    client_availability,
                    reservation.property,
                    SchedulingPreference.objects.filter(user=agent).first()
                )
                slot_info = slot_candidates[0] if slot_candidates else None
            else:
                slot_info = SchedulingAlgorithmService.find_first_available_slot(str(agent.id))
            
            if not slot_info:
                logger.error("Aucun créneau disponible trouvé")
                return None
            
            # Créer la planification
            schedule = VisitSchedule.objects.create(
                client=client_user,
                agent=agent,
                property=reservation.property,
                reservation=reservation,
                scheduled_date=slot_info['date'],
                scheduled_start_time=slot_info['start_time'],
                scheduled_end_time=slot_info['end_time'],
                matching_algorithm=algorithm,
                status='pending',
                match_score=slot_info.get('match_score', 1.0),
                match_factors=slot_info.get('match_factors', {}),
                priority=client_availability.urgency if client_availability else 'normal'
            )
            
            # Créer le créneau associé
            TimeSlot.objects.create(
                user=agent,
                date=slot_info['date'],
                start_time=slot_info['start_time'],
                end_time=slot_info['end_time'],
                status='booked',
                reservation=reservation
            )
            
            # Détecter les conflits
            ConflictDetectionService.detect_conflicts(schedule)
            
            return schedule
            
        except Exception as e:
            logger.error(f"Erreur création planification intelligente: {e}")
            return None
    
    @staticmethod
    def optimize_existing_schedules(agent_id: str, date: date) -> Dict[str, Any]:
        """Optimise les plannings existants"""
        
        # Récupérer les visites du jour
        schedules = VisitSchedule.objects.filter(
            agent_id=agent_id,
            scheduled_date=date,
            status__in=['scheduled', 'pending']
        ).select_related('property', 'client')
        
        if schedules.count() <= 1:
            return {'optimized': False, 'reason': 'Pas assez de visites à optimiser'}
        
        # Optimiser la route
        visits = [{'property_id': s.property.id, 'duration_minutes': 60} for s in schedules]
        optimized_route = SchedulingAlgorithmService.find_optimal_route_slots(agent_id, visits, date)
        
        if optimized_route:
            # Mettre à jour les planifications
            for i, (schedule, optimized_visit) in enumerate(zip(schedules, optimized_route['visits'])):
                schedule.scheduled_start_time = optimized_visit['start_time']
                schedule.scheduled_end_time = optimized_visit['end_time']
                schedule.travel_time = optimized_visit.get('travel_time', 0)
                schedule.save()
            
            return {
                'optimized': True,
                'total_travel_time_saved': optimized_route.get('total_travel_time', 0),
                'estimated_end_time': optimized_route.get('estimated_end_time'),
                'visits_rescheduled': len(schedules)
            }
        
        return {'optimized': False, 'reason': 'Optimisation impossible'}
    
    @staticmethod
    def _find_optimal_agent(reservation: Reservation, agent_preferences: Optional[Dict[str, Any]]) -> Optional[User]:
        """Trouve l'agent optimal pour une réservation"""
        
        # Agents disponibles (role et is_active sont sur User, pas sur UserProfile)
        available_agents = User.objects.filter(
            role='agent',
            is_active=True
        )
        
        if agent_preferences and agent_preferences.get('agent_id'):
            # Utiliser l'agent spécifié si disponible
            try:
                specified_agent = User.objects.get(id=agent_preferences['agent_id'])
                if specified_agent in available_agents:
                    return specified_agent
            except User.DoesNotExist:
                pass
        
        # Critères de sélection
        scored_agents = []
        
        for agent in available_agents:
            score = 0.0
            
            # Charge de travail actuelle (moins c'est mieux)
            today_load = VisitSchedule.objects.filter(
                agent=agent,
                scheduled_date=date.today(),
                status__in=['scheduled', 'confirmed', 'in_progress']
            ).count()
            score += max(0, 10 - today_load)  # Score de 0 à 10
            
            # Proximité géographique (si disponible)
            agent_pref = SchedulingPreference.objects.filter(user=agent).first()
            if agent_pref and agent_pref.working_radius:
                # Calcul simplifié de distance
                score += 5  # Bonus pour les agents avec préférences géographiques
            
            # Expérience avec le type de propriété
            if hasattr(agent, 'profile') and agent.profile.specialization:
                if (hasattr(reservation.property, 'property_type') and
                    reservation.property.property_type == agent.profile.specialization):
                    score += 3
            
            scored_agents.append((agent, score))
        
        # Retourner l'agent avec le meilleur score
        if scored_agents:
            return max(scored_agents, key=lambda x: x[1])[0]
        
        return None
    
    @staticmethod
    def generate_time_slots(
        agent_id: str,
        start_date: date,
        end_date: date,
        duration_minutes: int = 60
    ) -> List[TimeSlot]:
        """Génère automatiquement les créneaux pour un agent"""
        
        created_slots = []
        current_date = start_date
        
        while current_date <= end_date:
            working_hours = WorkingHours.objects.filter(
                user_id=agent_id,
                day_of_week=current_date.weekday(),
                is_working=True,
                is_active=True
            ).first()
            
            if working_hours:
                # Générer les créneaux pour ce jour
                slots = SchedulingAlgorithmService._generate_time_slots(
                    working_hours, current_date, duration_minutes, []
                )
                
                for slot in slots:
                    time_slot = TimeSlot.objects.create(
                        user_id=agent_id,
                        date=current_date,
                        start_time=slot['start_time'],
                        end_time=slot['end_time'],
                        status='available'
                    )
                    created_slots.append(time_slot)
            
            current_date += timedelta(days=1)
        
        return created_slots