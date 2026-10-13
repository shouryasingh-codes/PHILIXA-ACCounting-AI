from __future__ import annotations

from typing import Optional

from app.core.auth import (  # noqa: F401
    CurrentPrincipal,
    Principal,
    get_current_principal,
    require_admin_or_owner,
    require_owner,
    require_roles,
)
from app.core.config import get_settings
from app.services.notifications.base import NotificationAdapter
from app.services.notifications.email_adapter import EmailAdapter
from app.services.notifications.simulator import SimulatedNotificationAdapter
from app.services.notifications.whatsapp_adapter import WhatsAppAdapter

_notification_adapter: Optional[NotificationAdapter] = None
_email_adapter: Optional[EmailAdapter] = None


def get_email_adapter() -> EmailAdapter:
    """
    Dependency to inject the EmailAdapter for transactional emails (auth verification, password reset, invites).
    Always returns an EmailAdapter configured with SMTP settings, bypassing PHILIXA_NOTIFICATION_MODE.
    """
    global _email_adapter
    if _email_adapter is not None:
        return _email_adapter

    settings = get_settings()
    _email_adapter = EmailAdapter(
        hostname=settings.smtp_hostname,
        port=settings.smtp_port,
        username=settings.smtp_username,
        password=settings.smtp_password,
        use_tls=settings.smtp_use_tls,
        from_address=settings.smtp_from_address,
    )
    return _email_adapter


def get_notification_adapter() -> NotificationAdapter:
    """
    Dependency to inject the NotificationAdapter into routes or services.
    Returns the appropriate adapter based on settings.
    """
    global _notification_adapter
    if _notification_adapter is not None:
        return _notification_adapter

    settings = get_settings()

    if settings.notification_mode == "email":
        _notification_adapter = EmailAdapter(
            hostname=settings.smtp_hostname,
            port=settings.smtp_port,
            username=settings.smtp_username,
            password=settings.smtp_password,
            use_tls=settings.smtp_use_tls,
            from_address=settings.smtp_from_address,
        )
    elif settings.notification_mode == "whatsapp":
        _notification_adapter = WhatsAppAdapter()
    else:
        _notification_adapter = SimulatedNotificationAdapter()

    return _notification_adapter
