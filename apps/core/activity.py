"""Activity log helper aligned with ActivityLog model fields."""

from typing import Any, Optional


def log_activity(
    *,
    component: str,
    action: str,
    message: str,
    user=None,
    level: str = 'INFO',
    metadata: Optional[dict] = None,
    request=None,
) -> None:
    from apps.core.models import ActivityLog

    ip_address = None
    user_agent = ''
    if request is not None:
        ip_address = request.META.get('REMOTE_ADDR')
        user_agent = (request.META.get('HTTP_USER_AGENT') or '')[:500]

    ActivityLog.objects.create(
        user=user,
        component=component,
        action=action,
        message=message,
        level=level,
        metadata=metadata or {},
        ip_address=ip_address,
        user_agent=user_agent,
    )
