"""
Permissions pour le système de notifications
Contrôle d'accès granulaire pour les notifications en temps réel
"""

from rest_framework import permissions
from apps.core.user_roles import get_user_role, user_has_role, STAFF_ROLES, MANAGER_ROLES


class CanSendNotification(permissions.BasePermission):
    """Permission pour envoyer des notifications"""

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        return (
            request.user.is_superuser
            or request.user.is_staff
            or user_has_role(request.user, STAFF_ROLES)
        )


class CanManageNotificationSettings(permissions.BasePermission):
    """Permission pour gérer les paramètres de notification"""

    def has_object_permission(self, request, view, obj):
        if not request.user or not request.user.is_authenticated:
            return False
        if hasattr(obj, 'user') and obj.user == request.user:
            return True
        return request.user.is_superuser or request.user.is_staff


class CanViewNotification(permissions.BasePermission):
    """Permission pour voir les notifications"""

    def has_object_permission(self, request, view, obj):
        if not request.user or not request.user.is_authenticated:
            return False
        if obj.recipient == request.user:
            return True
        return request.user.is_superuser or request.user.is_staff


class CanManageNotificationTemplate(permissions.BasePermission):
    """Permission pour gérer les modèles de notifications"""

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        return request.user.is_superuser


class CanCreateNotification(permissions.BasePermission):
    """Permission pour créer des notifications"""

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        return (
            request.user.is_superuser
            or request.user.is_staff
            or user_has_role(request.user, STAFF_ROLES)
        )


class IsNotificationRecipient(permissions.BasePermission):
    """Permission pour vérifier que l'utilisateur est le destinataire"""

    def has_object_permission(self, request, view, obj):
        if not request.user or not request.user.is_authenticated:
            return False
        return obj.recipient == request.user


class CanManageNotificationGroup(permissions.BasePermission):
    """Permission pour gérer les groupes de notifications"""

    def has_object_permission(self, request, view, obj):
        if not request.user or not request.user.is_authenticated:
            return False
        return (
            request.user.is_superuser
            or request.user.is_staff
            or user_has_role(request.user, MANAGER_ROLES)
        )


class CanViewNotificationLogs(permissions.BasePermission):
    """Permission pour voir les journaux de notifications"""

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        return (
            request.user.is_superuser
            or request.user.is_staff
            or get_user_role(request.user) is not None
        )


class CanSubscribeToChannels(permissions.BasePermission):
    """Permission pour s'abonner aux canaux de notification"""

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated)

    def has_object_permission(self, request, view, obj):
        if not request.user or not request.user.is_authenticated:
            return False
        return obj.user == request.user or request.user.is_superuser


class NotificationPermissionMixin:
    """Mixin pour les permissions communes aux notifications"""

    def get_notification_permissions(self, user, obj=None):
        if not user or not user.is_authenticated:
            return []
        permissions_list = ['view_notification']
        if user.is_superuser or user.is_staff:
            permissions_list.extend([
                'create_notification',
                'edit_notification',
                'delete_notification',
                'send_notification',
                'manage_templates',
                'view_logs',
            ])
        else:
            role = get_user_role(user)
            if role in MANAGER_ROLES:
                permissions_list.extend([
                    'create_notification',
                    'edit_notification',
                    'send_notification',
                    'view_logs',
                ])
            elif role == 'agent':
                permissions_list.extend(['create_notification', 'send_notification'])
        return permissions_list
