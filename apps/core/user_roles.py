"""Helpers for User.role checks (role is on User, not UserProfile)."""

from typing import Optional, Iterable

STAFF_ROLES = frozenset({'agent', 'manager', 'admin'})
MANAGER_ROLES = frozenset({'manager', 'admin'})


def get_user_role(user) -> Optional[str]:
    if not user or not getattr(user, 'is_authenticated', False):
        return None
    return getattr(user, 'role', None)


def user_has_role(user, roles: Iterable[str]) -> bool:
    role = get_user_role(user)
    return role in roles if role else False


def user_is_staff_role(user) -> bool:
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser or user.is_staff:
        return True
    return user_has_role(user, STAFF_ROLES)


def is_platform_admin(user) -> bool:
    """Admin plateforme : voit toutes les agences (role admin ou flags Django staff)."""
    if not user or not getattr(user, 'is_authenticated', False):
        return False
    if getattr(user, 'is_superuser', False) or getattr(user, 'is_staff', False):
        return True
    return get_user_role(user) == 'admin'
