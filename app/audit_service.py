from sqlalchemy.ext.asyncio import AsyncSession
from app.models import AuditLog


async def log_event(db: AsyncSession, event_type: str, details: dict | None = None, order_id=None) -> AuditLog:
    record = AuditLog(order_id=order_id, event_type=event_type, details=details)
    db.add(record)
    await db.commit()
    await db.refresh(record)
    return record
