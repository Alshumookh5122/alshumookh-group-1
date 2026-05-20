import asyncio
import logging
from typing import Any

from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import AuditLog

log = logging.getLogger(__name__)


def _is_deadlock(exc: Exception) -> bool:
    return "deadlock detected" in str(exc).lower()


async def log_event(
    db: AsyncSession,
    event_type: str,
    details: dict | None = None,
    order_id=None,
    *,
    client_id=None,
    endpoint: str | None = None,
    method: str | None = None,
    ip: str | None = None,
    user_agent: str | None = None,
    status_code: int | None = None,
    transaction_id: str | None = None,
    request_id: str | None = None,
    error_message: str | None = None,
) -> AuditLog | None:
    record: AuditLog | None = None
    for attempt in range(3):
        record = AuditLog(
            order_id=order_id,
            client_id=client_id,
            event_type=event_type,
            endpoint=endpoint,
            method=method,
            ip=ip,
            user_agent=user_agent,
            status_code=status_code,
            transaction_id=transaction_id,
            request_id=request_id,
            error_message=error_message,
            details=details,
        )
        db.add(record)
        try:
            await db.commit()
            await db.refresh(record)
            return record
        except (DBAPIError, OperationalError) as exc:
            await db.rollback()
            if _is_deadlock(exc) and attempt < 2:
                await asyncio.sleep(0.05 * (attempt + 1))
                continue
            log.warning("Audit log write skipped for %s: %s", event_type, exc)
            return None
        except Exception as exc:
            await db.rollback()
            log.warning("Audit log write skipped for %s: %s", event_type, exc)
            return None
    return record


def safe_details(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if not payload:
        return payload

    blocked = {
        'admin_api_key',
        'api_key',
        'client_api_key',
        'coinbase_secret',
        'coinbase_webhook_secret',
        'moonpay_api_key',
        'moonpay_api_secret',
        'moonpay_webhook_secret',
        'oauth_client_secret',
        'oauth_client_secret_hash',
        'jws_public_key_pem',
        'settlement_jwe_private_key_pem',
        'settlement_jwe_private_key_passphrase',
        'database_url',
        'private_key',
        'secret',
        'x-api-key',
        'x-admin-api-key',
    }

    cleaned: dict[str, Any] = {}
    for key, value in payload.items():
        if key.lower() in blocked or 'secret' in key.lower() or 'private_key' in key.lower():
            cleaned[key] = '[REDACTED]'
        else:
            cleaned[key] = value
    return cleaned
