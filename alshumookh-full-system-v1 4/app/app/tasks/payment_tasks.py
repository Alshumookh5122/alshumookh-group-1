"""Payment background tasks — confirmation polling, expiry."""

import asyncio
import datetime
import structlog
from sqlalchemy import select, update

logger = structlog.get_logger()


async def _poll_pending():
    from app.app.database import AsyncSessionLocal
    from app.app.models import Payment, PaymentStatus
    from app.app.alchemy_service import AlchemyService
    from app.app.config import settings

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Payment).where(
                Payment.status == PaymentStatus.CONFIRMING,
                Payment.tx_hash.isnot(None),
            )
        )
        payments = result.scalars().all()

    service = AlchemyService()
    for payment in payments:
        try:
            await service.confirm_transaction(payment.id, payment.tx_hash)
        except Exception as e:
            logger.warning("poll.confirm_failed", payment_id=payment.id, error=str(e))


async def _expire_stale():
    from app.app.database import AsyncSessionLocal
    from app.app.models import Payment, PaymentStatus

    async with AsyncSessionLocal() as db:
        now = datetime.datetime.utcnow()
        await db.execute(
            update(Payment).where(
                Payment.status.in_([PaymentStatus.AWAITING_PAYMENT, PaymentStatus.PENDING]),
                Payment.expires_at.isnot(None),
                Payment.expires_at < now,
            ).values(status=PaymentStatus.EXPIRED)
        )
        await db.commit()
    logger.info("expire.stale_addresses_checked")


def poll_pending_crypto_payments():
    asyncio.run(_poll_pending())


def expire_stale_payment_addresses():
    asyncio.run(_expire_stale())
