"""
Views pour le système de calendrier intelligent
API REST avec Django REST Framework
"""

from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.db.models import Q
from django.utils import timezone
from datetime import datetime, date, timedelta
import json

from .models import (
    WorkingHours, TimeSlot, ClientAvailability, VisitSchedule,
    CalendarConflict, SchedulingPreference, ScheduleMetrics
)
from .serializers import (
    WorkingHoursSerializer, TimeSlotSerializer, ClientAvailabilitySerializer,
    VisitScheduleSerializer, VisitScheduleCreateSerializer, VisitScheduleUpdateSerializer,
    CalendarConflictSerializer, SchedulingPreferenceSerializer, ScheduleMetricsSerializer,
    CalendarViewSerializer, AutoScheduleRequestSerializer, ScheduleOptimizationSerializer,
    TimeSlotGenerationSerializer
)
from .permissions import (
    CanAccessCalendar, CanScheduleVisits, CanManageOwnSchedule,
    CanViewAgentSchedule, CanManageTimeSlots, CanOverrideSchedules,
    CanOptimizeSchedules, IsClientOrAuthorized, CanAutoSchedule
)
from .services import CalendarService

from django.contrib.auth import get_user_model
User = get_user_model()


class WorkingHoursViewSet(viewsets.ModelViewSet):
    """ViewSet pour la gestion des horaires de travail"""
    
    serializer_class = WorkingHoursSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        """Retourne les horaires de l'utilisateur ou tous si admin"""
        if self.request.user.is_superuser:
            return WorkingHours.objects.all().select_related('user')
        return WorkingHours.objects.filter(user=self.request.user).select_related('user')
    
    def perform_create(self, serializer):
        """Crée les horaires pour l'utilisateur courant"""
        serializer.save(user=self.request.user)
    
    @action(detail=False, methods=['get'])
    def my_hours(self, request):
        """Retourne les horaires de l'utilisateur courant"""
        hours = self.get_queryset().order_by('day_of_week')
        serializer = self.get_serializer(hours, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['post'])
    def set_week_schedule(self, request):
        """Configure les horaires pour toute la semaine"""
        schedule_data = request.data.get('schedule', [])
        
        if len(schedule_data) != 7:
            return Response(
                {'error': 'Le planning doit contenir 7 jours'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        created_hours = []
        for day_data in schedule_data:
            day_of_week = day_data.get('day_of_week')
            if 0 <= day_of_week <= 6:  # Vérifier que c'est un jour valide
                serializer = WorkingHoursSerializer(data={
                    'day_of_week': day_of_week,
                    'start_time': day_data.get('start_time'),
                    'end_time': day_data.get('end_time'),
                    'is_working': day_data.get('is_working', True),
                    'break_start': day_data.get('break_start'),
                    'break_end': day_data.get('break_end'),
                })
                
                if serializer.is_valid():
                    # Mettre à jour ou créer
                    working_hour, created = WorkingHours.objects.update_or_create(
                        user=request.user,
                        day_of_week=day_of_week,
                        defaults=serializer.validated_data
                    )
                    created_hours.append(working_hour)
                else:
                    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        return Response({
            'message': f'{len(created_hours)} horaires mis à jour',
            'schedule': WorkingHoursSerializer(created_hours, many=True).data
        })


class TimeSlotViewSet(viewsets.ModelViewSet):
    """ViewSet pour la gestion des créneaux horaires"""
    
    serializer_class = TimeSlotSerializer
    permission_classes = [IsAuthenticated, CanManageTimeSlots]
    
    def get_queryset(self):
        """Retourne les créneaux de l'utilisateur ou tous si admin"""
        if self.request.user.is_superuser:
            return TimeSlot.objects.all().select_related('user', 'reservation')
        return TimeSlot.objects.filter(user=self.request.user).select_related('user', 'reservation')
    
    @action(detail=False, methods=['get'])
    def available_slots(self, request):
        """Retourne les créneaux disponibles pour une date"""
        date_str = request.query_params.get('date')
        agent_id = request.query_params.get('agent_id')
        
        if not date_str:
            return Response(
                {'error': 'Date requise'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            return Response(
                {'error': 'Format de date invalide (YYYY-MM-DD)'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        query = TimeSlot.objects.filter(
            date=target_date,
            status='available'
        )
        
        if agent_id:
            query = query.filter(user_id=agent_id)
        elif not request.user.is_superuser:
            query = query.filter(user=request.user)
        
        slots = query.order_by('start_time')
        serializer = self.get_serializer(slots, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['post'])
    def book_slot(self, request):
        """Réserve un créneau"""
        slot_id = request.data.get('slot_id')
        reservation_id = request.data.get('reservation_id')
        
        if not slot_id or not reservation_id:
            return Response(
                {'error': 'slot_id et reservation_id requis'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            slot = TimeSlot.objects.get(id=slot_id, status='available')
            reservation = Reservation.objects.get(id=reservation_id)
            
            # Vérifier les permissions (réservation: client = client_profile.user ou created_by)
            reservation_client = None
            if getattr(reservation, 'client_profile', None) and getattr(reservation.client_profile, 'user', None):
                reservation_client = reservation.client_profile.user
            else:
                reservation_client = getattr(reservation, 'created_by', None)
            if (not request.user.is_superuser and 
                not request.user.is_staff and
                slot.user != request.user and
                reservation_client != request.user):
                return Response(
                    {'error': 'Permissions insuffisantes'},
                    status=status.HTTP_403_FORBIDDEN
                )
            
            # Réserver le créneau
            slot.status = 'booked'
            slot.reservation = reservation
            slot.save()
            
            return Response({
                'message': 'Créneau réservé avec succès',
                'slot': TimeSlotSerializer(slot).data
            })
            
        except (TimeSlot.DoesNotExist, Reservation.DoesNotExist) as e:
            return Response(
                {'error': 'Créneau ou réservation introuvable'},
                status=status.HTTP_404_NOT_FOUND
            )
    
    @action(detail=False, methods=['post'])
    def release_slot(self, request):
        """Libère un créneau"""
        slot_id = request.data.get('slot_id')
        
        if not slot_id:
            return Response(
                {'error': 'slot_id requis'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            slot = TimeSlot.objects.get(id=slot_id)
            
            # Vérifier les permissions
            if (not request.user.is_superuser and 
                not request.user.is_staff and
                slot.user != request.user):
                return Response(
                    {'error': 'Permissions insuffisantes'},
                    status=status.HTTP_403_FORBIDDEN
                )
            
            # Libérer le créneau
            slot.status = 'available'
            slot.reservation = None
            slot.save()
            
            return Response({
                'message': 'Créneau libéré avec succès',
                'slot': TimeSlotSerializer(slot).data
            })
            
        except TimeSlot.DoesNotExist:
            return Response(
                {'error': 'Créneau introuvable'},
                status=status.HTTP_404_NOT_FOUND
            )


class ClientAvailabilityViewSet(viewsets.ModelViewSet):
    """ViewSet pour les disponibilités client"""
    
    serializer_class = ClientAvailabilitySerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        """Retourne les disponibilités de l'utilisateur ou de ses clients"""
        user = self.request.user
        
        if user.is_superuser:
            return ClientAvailability.objects.all().select_related('user')
        
        # Agents peuvent voir les disponibilités de leurs clients
        try:
            profile = getattr(user, 'profile', None)
            if profile and getattr(profile, 'role', None) in ['agent', 'manager', 'admin']:
                # Retourner les disponibilités des clients assignés
                return ClientAvailability.objects.filter(
                    user__profile__assigned_agent=user
                ).select_related('user')
        except (AttributeError, Exception):
            pass
        
        return ClientAvailability.objects.filter(user=user).select_related('user')
    
    def perform_create(self, serializer):
        """Crée les disponibilités pour l'utilisateur courant"""
        serializer.save(user=self.request.user)
    
    @action(detail=False, methods=['get'])
    def my_availabilities(self, request):
        """Retourne les disponibilités de l'utilisateur courant"""
        availabilities = self.get_queryset().filter(user=request.user)
        serializer = self.get_serializer(availabilities, many=True)
        return Response(serializer.data)


class VisitScheduleViewSet(viewsets.ModelViewSet):
    """ViewSet pour les planifications de visite"""
    
    def get_serializer_class(self):
        """Retourne le serializer approprié selon l'action"""
        if self.action == 'create':
            return VisitScheduleCreateSerializer
        elif self.action in ['update', 'partial_update']:
            return VisitScheduleUpdateSerializer
        return VisitScheduleSerializer
    
    def get_permissions(self):
        """Configure les permissions selon l'action"""
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            permission_classes = [IsAuthenticated, CanScheduleVisits]
        elif self.action == 'list':
            permission_classes = [IsAuthenticated]
        else:
            permission_classes = [IsAuthenticated]
        
        return [permission() for permission in permission_classes]
    
    def get_queryset(self):
        """Retourne les planifications selon le rôle (pas toute la plateforme par défaut)."""
        from apps.core.user_roles import is_platform_admin, get_user_role
        from apps.crm.services.scope import user_agency

        queryset = VisitSchedule.objects.select_related(
            'client', 'agent', 'property', 'reservation'
        )
        user = self.request.user
        role = get_user_role(user)
        platform_all = self.request.query_params.get('platform') == 'true'

        if platform_all and (user.is_superuser or is_platform_admin(user)):
            qs = queryset
        elif role == 'agent':
            qs = queryset.filter(agent=user)
        elif role == 'manager':
            agency = user_agency(user)
            if agency:
                qs = queryset.filter(agent__profile__agency=agency)
            else:
                qs = queryset.filter(agent=user)
        elif role == 'client':
            qs = queryset.filter(client=user)
        elif role == 'admin':
            qs = queryset.filter(Q(agent=user) | Q(client=user))
        else:
            qs = queryset.filter(Q(client=user) | Q(agent=user))

        start_date = self.request.query_params.get('start_date')
        end_date = self.request.query_params.get('end_date')
        if start_date:
            qs = qs.filter(scheduled_date__gte=start_date)
        if end_date:
            qs = qs.filter(scheduled_date__lte=end_date)

        if self.request.query_params.get('upcoming') == 'true':
            qs = qs.filter(scheduled_date__gte=date.today())
        if self.request.query_params.get('past') == 'true':
            qs = qs.filter(scheduled_date__lt=date.today())

        return qs.order_by('scheduled_date', 'scheduled_start_time')

    def list(self, request, *args, **kwargs):
        platform_wide = request.query_params.get('platform') == 'true'
        try:
            CalendarService.sync_schedules_for_user(
                request.user,
                platform_wide=platform_wide,
            )
        except Exception:
            import logging
            logging.getLogger(__name__).exception('Sync calendrier (list)')
        return super().list(request, *args, **kwargs)
    
    def perform_create(self, serializer):
        """Crée une nouvelle planification"""
        serializer.save()
    
    @action(detail=True, methods=['post'])
    def confirm(self, request, pk=None):
        """Confirme une planification"""
        schedule = self.get_object()
        
        # Vérifier les permissions
        if not (request.user == schedule.client or 
                request.user == schedule.agent or
                request.user.is_superuser or
                request.user.is_staff):
            return Response(
                {'error': 'Permissions insuffisantes'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        schedule.status = 'confirmed'
        schedule.confirmed_at = timezone.now()
        schedule.confirmed_by = request.user
        schedule.save()
        
        return Response({'message': 'Planification confirmée'})
    
    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        """Annule une planification"""
        schedule = self.get_object()
        
        # Vérifier les permissions
        if not (request.user == schedule.client or 
                request.user == schedule.agent or
                request.user.is_superuser or
                request.user.is_staff):
            return Response(
                {'error': 'Permissions insuffisantes'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        schedule.status = 'cancelled'
        schedule.agent_notes = request.data.get('notes', '')
        schedule.save()
        
        # Libérer le créneau associé
        TimeSlot.objects.filter(
            user=schedule.agent,
            date=schedule.scheduled_date,
            start_time=schedule.scheduled_start_time,
            reservation=schedule.reservation
        ).update(status='available', reservation=None)
        
        return Response({'message': 'Planification annulée'})
    
    @action(detail=True, methods=['post'])
    def complete(self, request, pk=None):
        """Marque une visite comme terminée"""
        schedule = self.get_object()
        
        # Seuls l'agent ou un admin peuvent marquer comme terminé
        if not (request.user == schedule.agent or
                request.user.is_superuser or
                request.user.is_staff):
            return Response(
                {'error': 'Permissions insuffisantes'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        schedule.status = 'completed'
        schedule.agent_notes = request.data.get('notes', '')
        schedule.save()
        
        return Response({'message': 'Visite marquée comme terminée'})
    
    @action(detail=False, methods=['get'])
    def today(self, request):
        """Retourne les planifications du jour"""
        today = date.today()
        schedules = self.get_queryset().filter(scheduled_date=today)
        
        page = self.paginate_queryset(schedules.order_by('scheduled_start_time'))
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        
        serializer = self.get_serializer(schedules, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'])
    def upcoming(self, request):
        """Retourne les planifications à venir"""
        today = date.today()
        schedules = self.get_queryset().filter(
            scheduled_date__gte=today,
            status__in=['scheduled', 'confirmed']
        )
        
        page = self.paginate_queryset(schedules.order_by('scheduled_date', 'scheduled_start_time'))
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        
        serializer = self.get_serializer(schedules, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'])
    def calendar_view(self, request):
        """Vue calendrier pour une période donnée"""
        platform_wide = request.query_params.get('platform') == 'true'
        try:
            CalendarService.sync_schedules_for_user(
                request.user,
                platform_wide=platform_wide,
            )
        except Exception:
            import logging
            logging.getLogger(__name__).exception('Sync calendrier (calendar_view)')

        start_date = request.query_params.get('start_date', date.today().isoformat())
        end_date = request.query_params.get('end_date', (date.today() + timedelta(days=30)).isoformat())
        agent_id = request.query_params.get('agent_id')
        
        try:
            start_date = datetime.strptime(start_date, '%Y-%m-%d').date()
            end_date = datetime.strptime(end_date, '%Y-%m-%d').date()
        except ValueError:
            return Response(
                {'error': 'Format de date invalide (YYYY-MM-DD)'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        query = self.get_queryset().filter(
            scheduled_date__range=[start_date, end_date]
        )
        
        if agent_id:
            query = query.filter(agent_id=agent_id)
        
        schedules = query.order_by('scheduled_date', 'scheduled_start_time')
        
        # Organiser par date
        calendar_data = {}
        for schedule in schedules:
            date_str = schedule.scheduled_date.isoformat()
            if date_str not in calendar_data:
                calendar_data[date_str] = []
            
            calendar_data[date_str].append(VisitScheduleSerializer(schedule).data)
        
        return Response({
            'start_date': start_date.isoformat(),
            'end_date': end_date.isoformat(),
            'schedules': calendar_data
        })


class CalendarConflictViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet en lecture seule pour les conflits"""
    
    serializer_class = CalendarConflictSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        """Retourne les conflits selon les permissions"""
        user = self.request.user
        
        if user.is_superuser:
            return CalendarConflict.objects.all().select_related('schedule1', 'schedule2')
        
        # Les agents voient les conflits de leurs planifications
        try:
            if hasattr(user, 'profile') and user.profile:
                if getattr(user, 'role', None) in ['agent', 'manager', 'admin']:
                    return CalendarConflict.objects.filter(
                        Q(schedule1__agent=user) |
                        Q(schedule2__agent=user)
                    ).select_related('schedule1', 'schedule2')
        except AttributeError:
            pass
        
        # Les clients voient les conflits de leurs planifications
        return CalendarConflict.objects.filter(
            Q(schedule1__client=user) |
            Q(schedule2__client=user) |
            Q(schedule1__agent=user) |
            Q(schedule2__agent=user)
        ).select_related('schedule1', 'schedule2')
    
    @action(detail=True, methods=['post'])
    def resolve(self, request, pk=None):
        """Résout un conflit"""
        conflict = self.get_object()
        
        # Vérifier les permissions
        if not (request.user.is_superuser or 
                request.user.is_staff or
                getattr(request.user, 'role', None) in ['agent', 'manager', 'admin']):
            return Response(
                {'error': 'Permissions insuffisantes'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        conflict.status = 'resolved'
        conflict.resolution_notes = request.data.get('resolution_notes', '')
        conflict.resolved_at = timezone.now()
        conflict.resolved_by = request.user
        conflict.save()
        
        return Response({'message': 'Conflit résolu'})


class SchedulingPreferenceViewSet(viewsets.ModelViewSet):
    """ViewSet pour les préférences de planification"""
    
    serializer_class = SchedulingPreferenceSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        """Retourne les préférences de l'utilisateur ou toutes si admin"""
        if self.request.user.is_superuser:
            return SchedulingPreference.objects.all().select_related('user')
        return SchedulingPreference.objects.filter(user=self.request.user).select_related('user')
    
    def get_object(self):
        """Retourne ou crée les préférences de l'utilisateur"""
        if self.request.user.is_superuser and 'pk' in self.kwargs:
            return SchedulingPreference.objects.get(user_id=self.kwargs['pk'])
        
        # Retourner ou créer les préférences de l'utilisateur courant
        preference, created = SchedulingPreference.objects.get_or_create(
            user=self.request.user
        )
        return preference
    
    @action(detail=False, methods=['get'])
    def my_preferences(self, request):
        """Retourne les préférences de l'utilisateur courant"""
        preference = self.get_object()
        serializer = self.get_serializer(preference)
        return Response(serializer.data)


class ScheduleMetricsViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet en lecture seule pour les métriques"""
    
    serializer_class = ScheduleMetricsSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        """Retourne les métriques selon les permissions"""
        user = self.request.user
        
        if user.is_superuser:
            return ScheduleMetrics.objects.all().select_related('agent')
        
        # Les agents voient leurs propres métriques
        try:
            if hasattr(user, 'profile') and user.profile:
                if getattr(user, 'role', None) in ['agent', 'manager', 'admin']:
                    return ScheduleMetrics.objects.filter(agent=user).select_related('agent')
        except AttributeError:
            pass
        
        # Par défaut, essayer de voir ses propres métriques
        return ScheduleMetrics.objects.filter(agent=user).select_related('agent')
    
    @action(detail=False, methods=['get'])
    def my_metrics(self, request):
        """Retourne les métriques de l'utilisateur"""
        # Cette action sera implémentée avec des calculs en temps réel
        return Response({'message': 'Métriques en cours de développement'})


# ============================================================================
# VUES FONCTIONNELLES POUR LA PLANIFICATION AUTOMATIQUE
# ============================================================================

@csrf_exempt
def auto_schedule_view(request):
    """Vue pour la planification automatique"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            serializer = AutoScheduleRequestSerializer(data=data)
            
            if serializer.is_valid():
                schedule = CalendarService.create_smart_schedule(
                    reservation_id=serializer.validated_data['reservation_id'],
                    client_preferences=serializer.validated_data.get('client_preferences'),
                    agent_preferences=serializer.validated_data.get('agent_preferences'),
                    algorithm=serializer.validated_data.get('matching_algorithm', 'best_match')
                )
                
                if schedule:
                    return JsonResponse({
                        'success': True,
                        'schedule': VisitScheduleSerializer(schedule).data
                    })
                else:
                    return JsonResponse({
                        'success': False,
                        'error': 'Impossible de créer la planification'
                    }, status=400)
            else:
                return JsonResponse({
                    'success': False,
                    'errors': serializer.errors
                }, status=400)
                
        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': str(e)
            }, status=500)
    
    return JsonResponse({'error': 'Méthode non autorisée'}, status=405)


@csrf_exempt
def optimize_schedules_view(request):
    """Vue pour l'optimisation des plannings"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            serializer = ScheduleOptimizationSerializer(data=data)
            
            if serializer.is_valid_data():
                result = CalendarService.optimize_existing_schedules(
                    agent_id=serializer.validated_data.get('agent_id', str(request.user.id)),
                    date=serializer.validated_data['date']
                )
                
                return JsonResponse({
                    'success': True,
                    'result': result
                })
            else:
                return JsonResponse({
                    'success': False,
                    'errors': serializer.errors
                }, status=400)
                
        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': str(e)
            }, status=500)
    
    return JsonResponse({'error': 'Méthode non autorisée'}, status=405)


@csrf_exempt
def generate_time_slots_view(request):
    """Vue pour la génération automatique de créneaux"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            serializer = TimeSlotGenerationSerializer(data=data)
            
            if serializer.is_valid():
                slots = CalendarService.generate_time_slots(
                    agent_id=serializer.validated_data['agent_id'],
                    start_date=serializer.validated_data['start_date'],
                    end_date=serializer.validated_data['end_date'],
                    duration_minutes=serializer.validated_data.get('time_slot_duration', 60)
                )
                
                return JsonResponse({
                    'success': True,
                    'created_slots': len(slots),
                    'slots': TimeSlotSerializer(slots, many=True).data
                })
            else:
                return JsonResponse({
                    'success': False,
                    'errors': serializer.errors
                }, status=400)
                
        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': str(e)
            }, status=500)
    
    return JsonResponse({'error': 'Méthode non autorisée'}, status=405)


@csrf_exempt
def calendar_view(request):
    """Vue pour l'affichage du calendrier"""
    if request.method == 'GET':
        try:
            start_date = request.GET.get('start_date', date.today().isoformat())
            end_date = request.GET.get('end_date', (date.today() + timedelta(days=30)).isoformat())
            agent_id = request.GET.get('agent_id')
            
            start_date = datetime.strptime(start_date, '%Y-%m-%d').date()
            end_date = datetime.strptime(end_date, '%Y-%m-%d').date()
            
            # Récupérer les planifications
            query = VisitSchedule.objects.filter(
                scheduled_date__range=[start_date, end_date]
            )
            
            if agent_id:
                query = query.filter(agent_id=agent_id)
            elif request.user.is_authenticated and not request.user.is_superuser:
                # Utilisateur voit ses planifications (comme client ou agent)
                query = query.filter(Q(agent=request.user) | Q(client=request.user))
            
            schedules = query.select_related('client', 'agent', 'property').order_by('scheduled_date', 'scheduled_start_time')
            
            # Organiser les données
            calendar_data = []
            current_date = start_date
            
            while current_date <= end_date:
                day_schedules = schedules.filter(scheduled_date=current_date)
                
                calendar_data.append({
                    'date': current_date.isoformat(),
                    'schedules': VisitScheduleSerializer(day_schedules, many=True).data
                })
                
                current_date += timedelta(days=1)
            
            return JsonResponse({
                'success': True,
                'calendar': calendar_data
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': str(e)
            }, status=500)
    
    return JsonResponse({'error': 'Méthode non autorisée'}, status=405)