"""Notification background tasks."""

import asyncio
import structlog

logger = structlog.get_logger()


def send_daily_admin_summary():
    from app.app.notification_service import NotificationService
    asyncio.run(NotificationService.send_daily_admin_summary())
