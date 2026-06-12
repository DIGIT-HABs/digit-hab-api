"""
Serializers pour le système de calendrier intelligent
"""

from rest_framework import serializers
from django.contrib.auth import get_user_model
from django.utils import timezone
from datetime import datetime, date, time, timedelta

from .models import (
    WorkingHours, TimeSlot, ClientAvailability, VisitSchedule,
    CalendarConflict, SchedulingPreference, ScheduleMetrics
)

User = get_user_model()


class UserBasicSerializer(serializers.ModelSerializer):
    """Serializer basique pour les utilisateurs"""
    
    class Meta:
        model = User
        fields = ['id', 'username', 'first_name', 'last_name', 'email']
        read_only_fields = ['id']


class WorkingHoursSerializer(serializers.ModelSerializer):
    """Serializer pour les horaires de travail"""
    
    user = UserBasicSerializer(read_only=True)
    user_id = serializers.UUIDField(write_only=True, required=False)
    
    class Meta:
        model = WorkingHours
        fields = [
            'id', 'user', 'user_id', 'day_of_week', 'start_time', 'end_time',
            'is_working', 'break_start', 'break_end', 'is_active', 'created_at'
        ]
        read_only_fields = ['id', 'created_at']
    
    def validate(self, data):
        """Valide les horaires"""
        if data.get('is_working'):
            if not data.get('start_time') or not data.get('end_time'):
                raise serializers.ValidationError(
                    "Les heures de début et de fin sont requises quand l'agent travaille"
                )
            
            if data.get('start_time') >= data.get('end_time'):
                raise serializers.ValidationError(
                    "L'heure de début doit être avant l'heure de fin"
                )
        
        return data


class TimeSlotSerializer(serializers.ModelSerializer):
    """Serializer pour les créneaux horaires"""
    
    user = UserBasicSerializer(read_only=True)
    user_id = serializers.UUIDField(write_only=True, required=False)
    
    class Meta:
        model = TimeSlot
        fields = [
            'id', 'user', 'user_id', 'date', 'start_time', 'end_time',
            'status', 'reservation', 'notes', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']
    
    def validate_date(self, value):
        """Valide que la date n'est pas dans le passé"""
        if value < date.today():
            raise serializers.ValidationError("La date ne peut pas être dans le passé")
        return value
    
    def validate(self, data):
        """Valide les créneaux"""
        if data.get('start_time') and data.get('end_time'):
            if data['start_time'] >= data['end_time']:
                raise serializers.ValidationError(
                    "L'heure de début doit être avant l'heure de fin"
                )
        return data


class ClientAvailabilitySerializer(serializers.ModelSerializer):
    """Serializer pour les disponibilités client"""
    
    user = UserBasicSerializer(read_only=True)
    user_id = serializers.UUIDField(write_only=True, required=False)
    
    class Meta:
        model = ClientAvailability
        fields = [
            'id', 'user', 'user_id', 'preferred_date', 'preferred_time_slot',
            'specific_start_time', 'specific_end_time', 'urgency', 'preferred_duration',
            'notes', 'is_active', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']
    
    def validate_preferred_date(self, value):
        """Valide que la date n'est pas trop ancienne"""
        if value < date.today() - timedelta(days=30):
            raise serializers.ValidationError("La date préférée ne peut pas être trop ancienne")
        return value


class SchedulingPreferenceSerializer(serializers.ModelSerializer):
    """Serializer pour les préférences de planification"""
    
    user = UserBasicSerializer(read_only=True)
    
    class Meta:
        model = SchedulingPreference
        fields = [
            'id', 'user', 'route_optimization', 'client_preference_handling',
            'max_daily_visits', 'min_break_minutes', 'travel_time_buffer',
            'working_radius', 'preferred_areas', 'preferred_property_types',
            'is_active', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']
    
    def validate_max_daily_visits(self, value):
        """Valide le nombre maximum de visites quotidiennes"""
        if value < 1 or value > 20:
            raise serializers.ValidationError(
                "Le nombre de visites quotidiennes doit être entre 1 et 20"
            )
        return value
    
    def validate_preferred_areas(self, value):
        """Valide les zones préférées"""
        if not isinstance(value, list):
            raise serializers.ValidationError("Les zones préférées doivent être une liste")
        return value


class VisitScheduleSerializer(serializers.ModelSerializer):
    """Serializer principal pour les planifications de visite"""
    
    client = UserBasicSerializer(read_only=True)
    agent = UserBasicSerializer(read_only=True)
    
    # Relations pour la création
    client_id = serializers.UUIDField(write_only=True, required=False)
    agent_id = serializers.UUIDField(write_only=True, required=False)
    property_id = serializers.UUIDField(write_only=True, required=False)
    reservation_id = serializers.UUIDField(write_only=True, required=False)
    
    # Propriété
    property_data = serializers.SerializerMethodField()
    
    class Meta:
        model = VisitSchedule
        fields = [
            'id', 'client', 'client_id', 'agent', 'agent_id', 'property', 'property_id',
            'property_data', 'reservation', 'reservation_id', 'scheduled_date',
            'scheduled_start_time', 'scheduled_end_time', 'matching_algorithm',
            'status', 'priority', 'match_score', 'match_factors', 'travel_time',
            'distance', 'client_notes', 'agent_notes', 'system_notes',
            'confirmed_at', 'confirmed_by', 'created_at', 'updated_at'
        ]
        read_only_fields = [
            'id', 'match_score', 'match_factors', 'travel_time', 'distance',
            'confirmed_at', 'confirmed_by', 'created_at', 'updated_at'
        ]
    
    def get_property_data(self, obj):
        """Retourne les données de la propriété"""
        prop = getattr(obj, 'property', None)
        if not prop:
            return None
        try:
            address = prop.get_full_address() if hasattr(prop, 'get_full_address') else ''
        except Exception:
            address = getattr(prop, 'address_line1', '') or ''
        return {
            'id': prop.id,
            'title': getattr(prop, 'title', ''),
            'address': address,
            'type': prop.get_property_type_display() if getattr(prop, 'property_type', None) else '',
        }
    
    def validate_scheduled_date(self, value):
        """Valide que la date de visite n'est pas dans le passé"""
        if value < date.today():
            raise serializers.ValidationError("La date de visite ne peut pas être dans le passé")
        return value
    
    def validate(self, data):
        """Validation globale"""
        # Vérifier que l'heure de début est avant l'heure de fin
        if (data.get('scheduled_start_time') and data.get('scheduled_end_time') and
            data['scheduled_start_time'] >= data['scheduled_end_time']):
            raise serializers.ValidationError(
                "L'heure de début doit être avant l'heure de fin"
            )
        
        return data


class VisitScheduleCreateSerializer(serializers.Serializer):
    """Serializer pour la création de planifications"""
    
    # Identifiants requis
    client_id = serializers.UUIDField(required=True)
    property_id = serializers.UUIDField(required=True)
    reservation_id = serializers.UUIDField(required=True)
    
    # Date et heure
    preferred_date = serializers.DateField(required=False)
    preferred_time_slot = serializers.ChoiceField(
        choices=ClientAvailability.PREFERENCE_CHOICES,
        required=False
    )
    specific_start_time = serializers.TimeField(required=False)
    specific_end_time = serializers.TimeField(required=False)
    
    # Préférences
    urgency = serializers.ChoiceField(
        choices=ClientAvailability.URGENCY_CHOICES,
        default='normal'
    )
    preferred_duration = serializers.IntegerField(default=60, min_value=15, max_value=240)
    
    # Algorithme
    matching_algorithm = serializers.ChoiceField(
        choices=VisitSchedule.MATCHING_ALGORITHMS,
        default='best_match'
    )
    
    # Notes
    client_notes = serializers.CharField(max_length=1000, required=False, allow_blank=True)
    
    def validate_preferred_date(self, value):
        """Valide la date préférée"""
        if value and value < date.today():
            raise serializers.ValidationError("La date préférée ne peut pas être dans le passé")
        return value


class VisitScheduleUpdateSerializer(serializers.Serializer):
    """Serializer pour la mise à jour des planifications"""
    
    scheduled_date = serializers.DateField(required=False)
    scheduled_start_time = serializers.TimeField(required=False)
    scheduled_end_time = serializers.TimeField(required=False)
    status = serializers.ChoiceField(
        choices=VisitSchedule.STATUS_CHOICES,
        required=False
    )
    priority = serializers.ChoiceField(
        choices=VisitSchedule.PRIORITY_CHOICES,
        required=False
    )
    agent_notes = serializers.CharField(max_length=1000, required=False, allow_blank=True)
    
    def validate(self, data):
        """Validation globale"""
        # Vérifier la cohérence des champs de date
        if ('scheduled_start_time' in data and 'scheduled_end_time' in data and
            data['scheduled_start_time'] and data['scheduled_end_time'] and
            data['scheduled_start_time'] >= data['scheduled_end_time']):
            raise serializers.ValidationError(
                "L'heure de début doit être avant l'heure de fin"
            )
        
        return data


class CalendarConflictSerializer(serializers.ModelSerializer):
    """Serializer pour les conflits de calendrier"""
    
    schedule1 = VisitScheduleSerializer(read_only=True)
    schedule2 = VisitScheduleSerializer(read_only=True)
    
    # Résolution
    status = serializers.ChoiceField(choices=CalendarConflict.STATUS_CHOICES, required=False)
    resolution_notes = serializers.CharField(max_length=1000, required=False, allow_blank=True)
    
    class Meta:
        model = CalendarConflict
        fields = [
            'id', 'schedule1', 'schedule2', 'conflict_type', 'severity',
            'description', 'status', 'resolution_notes', 'resolved_at',
            'resolved_by', 'created_at', 'updated_at'
        ]
        read_only_fields = [
            'id', 'schedule1', 'schedule2', 'conflict_type', 'severity',
            'description', 'resolved_at', 'resolved_by', 'created_at', 'updated_at'
        ]


class ScheduleMetricsSerializer(serializers.ModelSerializer):
    """Serializer pour les métriques de planification"""
    
    agent = UserBasicSerializer(read_only=True)
    
    class Meta:
        model = ScheduleMetrics
        fields = [
            'id', 'date', 'agent', 'total_scheduled_visits', 'completed_visits',
            'cancelled_visits', 'no_show_visits', 'average_match_score',
            'total_travel_time', 'total_distance', 'optimization_savings',
            'efficiency_score', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class CalendarViewSerializer(serializers.Serializer):
    """Serializer pour la vue calendrier"""
    
    date = serializers.DateField()
    agent_id = serializers.UUIDField(required=False)
    status = serializers.ChoiceField(
        choices=VisitSchedule.STATUS_CHOICES,
        required=False
    )
    property_type = serializers.CharField(required=False)


class AutoScheduleRequestSerializer(serializers.Serializer):
    """Serializer pour la demande de planification automatique"""
    
    # Réservation
    reservation_id = serializers.UUIDField(required=True)
    
    # Préférences client
    preferred_date = serializers.DateField(required=False)
    preferred_time_slot = serializers.ChoiceField(
        choices=ClientAvailability.PREFERENCE_CHOICES,
        required=False
    )
    specific_start_time = serializers.TimeField(required=False)
    specific_end_time = serializers.TimeField(required=False)
    
    # Contraintes
    urgency = serializers.ChoiceField(
        choices=ClientAvailability.URGENCY_CHOICES,
        default='normal'
    )
    max_alternatives = serializers.IntegerField(default=3, min_value=1, max_value=10)
    
    # Algorithme
    matching_algorithm = serializers.ChoiceField(
        choices=VisitSchedule.MATCHING_ALGORITHMS,
        default='best_match'
    )
    
    def validate_reservation_id(self, value):
        """Valide l'ID de réservation"""
        try:
            from apps.reservations.models import Reservation
            Reservation.objects.get(id=value)
        except Exception:
            raise serializers.ValidationError("Réservation introuvable")
        return value


class ScheduleOptimizationSerializer(serializers.Serializer):
    """Serializer pour l'optimisation de planning"""
    
    date = serializers.DateField(required=True)
    agent_id = serializers.UUIDField(required=False)
    optimization_type = serializers.ChoiceField(
        choices=[
            ('route', 'Optimisation de route'),
            ('time', 'Optimisation de temps'),
            ('load', 'Répartition de charge'),
        ],
        default='route'
    )
    
    def validate_date(self, value):
        """Valide la date"""
        if value < date.today():
            raise serializers.ValidationError("La date ne peut pas être dans le passé")
        return value


class TimeSlotGenerationSerializer(serializers.Serializer):
    """Serializer pour la génération automatique de créneaux"""
    
    agent_id = serializers.UUIDField(required=True)
    start_date = serializers.DateField(required=True)
    end_date = serializers.DateField(required=True)
    time_slot_duration = serializers.IntegerField(
        default=60,
        min_value=15,
        max_value=240
    )
    working_hours_only = serializers.BooleanField(default=True)
    
    def validate(self, data):
        """Valide les dates"""
        if data['start_date'] > data['end_date']:
            raise serializers.ValidationError(
                "La date de début doit être avant la date de fin"
            )
        return data