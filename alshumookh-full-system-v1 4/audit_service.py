"""Audit Service — structured audit logging helpers."""

from typing import Any, Dict, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.app.models import AuditLog, AuditAction


class AuditService:
    @staticmethod
    async def log(
        db: AsyncSession,
        action: AuditAction,
        user_id: Optional[str] = None,
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> AuditLog:
        entry = AuditLog(
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            details=details,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        db.add(entry)
        await db.flush()
        return entry

    @staticmethod
    async def get_resource_history(
        db: AsyncSession,
        resource_type: str,
        resource_id: str,
        limit: int = 50,
    ):
        from sqlalchemy import select
        result = await db.execute(
            select(AuditLog)
            .where(AuditLog.resource_type == resource_type, AuditLog.resource_id == resource_id)
            .order_by(AuditLog.created_at.desc())
            .limit(limit)
        )
        return result.scalars().all()
