"""
Permissions pour le système de calendrier intelligent
"""

from rest_framework import permissions
from apps.core.user_roles import get_user_role, user_has_role, STAFF_ROLES, MANAGER_ROLES


class CanAccessCalendar(permissions.BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated)


class CanScheduleVisits(permissions.BasePermission):
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        return (
            request.user.is_superuser
            or request.user.is_staff
            or user_has_role(request.user, STAFF_ROLES)
        )


class CanManageOwnSchedule(permissions.BasePermission):
    def has_object_permission(self, request, view, obj):
        if not request.user or not request.user.is_authenticated:
            return False
        return obj.agent == request.user or getattr(obj, 'user', None) == request.user


class CanViewAgentSchedule(permissions.BasePermission):
    def has_object_permission(self, request, view, obj):
        if not request.user or not request.user.is_authenticated:
            return False
        if obj.agent == request.user:
            return True
        return (
            request.user.is_superuser
            or request.user.is_staff
            or user_has_role(request.user, MANAGER_ROLES)
        )


class CanManageTimeSlots(permissions.BasePermission):
    def has_object_permission(self, request, view, obj):
        if not request.user or not request.user.is_authenticated:
            return False
        if obj.user == request.user:
            return True
        return request.user.is_superuser or request.user.is_staff


class CanOverrideSchedules(permissions.BasePermission):
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        return (
            request.user.is_superuser
            or request.user.is_staff
            or user_has_role(request.user, MANAGER_ROLES)
        )


class CanOptimizeSchedules(permissions.BasePermission):
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        return (
            request.user.is_superuser
            or request.user.is_staff
            or user_has_role(request.user, STAFF_ROLES)
        )


class CanViewScheduleMetrics(permissions.BasePermission):
    def has_object_permission(self, request, view, obj):
        if not request.user or not request.user.is_authenticated:
            return False
        if obj.agent == request.user:
            return True
        return request.user.is_superuser or request.user.is_staff


class CanManageWorkingHours(permissions.BasePermission):
    def has_object_permission(self, request, view, obj):
        if not request.user or not request.user.is_authenticated:
            return False
        if obj.user == request.user:
            return True
        return request.user.is_superuser or request.user.is_staff


class CanResolveConflicts(permissions.BasePermission):
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        return (
            request.user.is_superuser
            or request.user.is_staff
            or user_has_role(request.user, STAFF_ROLES)
        )


class CanSetSchedulingPreferences(permissions.BasePermission):
    def has_object_permission(self, request, view, obj):
        if not request.user or not request.user.is_authenticated:
            return False
        if obj.user == request.user:
            return True
        return request.user.is_superuser or request.user.is_staff


class IsClientOrAuthorized(permissions.BasePermission):
    def has_object_permission(self, request, view, obj):
        if not request.user or not request.user.is_authenticated:
            return False
        if obj.client == request.user or obj.agent == request.user:
            return True
        return request.user.is_superuser or request.user.is_staff


class CanAutoSchedule(permissions.BasePermission):
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        return (
            request.user.is_superuser
            or request.user.is_staff
            or user_has_role(request.user, STAFF_ROLES)
        )


class CalendarPermissionMixin:
    def get_calendar_permissions(self, user, obj=None):
        if not user or not user.is_authenticated:
            return []
        permissions_list = ['view_calendar', 'view_schedule']
        if user.is_superuser or user.is_staff:
            permissions_list.extend([
                'manage_calendar', 'schedule_visits', 'manage_time_slots',
                'optimize_schedules', 'view_metrics', 'resolve_conflicts',
                'set_preferences', 'override_schedules',
            ])
        else:
            role = get_user_role(user)
            if role in MANAGER_ROLES:
                permissions_list.extend([
                    'schedule_visits', 'optimize_schedules', 'view_metrics',
                    'resolve_conflicts', 'set_preferences', 'override_schedules',
                ])
            elif role == 'agent':
                permissions_list.extend([
                    'schedule_visits', 'optimize_schedules', 'manage_time_slots',
                    'set_preferences', 'view_metrics',
                ])
        return permissions_list
