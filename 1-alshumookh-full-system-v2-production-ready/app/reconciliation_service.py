from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import OrderStatus, PaymentOrder


async def pending_orders(db: AsyncSession) -> list[PaymentOrder]:
    res = await db.execute(select(PaymentOrder).where(PaymentOrder.status.in_([OrderStatus.PENDING, OrderStatus.PROCESSING])))
    return list(res.scalars().all())


async def reconcile(db: AsyncSession) -> dict:
    orders = await pending_orders(db)
    return {'checked': len(orders), 'message': 'Wire provider-specific status sync here'}
