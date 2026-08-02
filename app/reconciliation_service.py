from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import OrderStatus, PaymentOrder, Provider


OPEN_STATUSES = [
    OrderStatus.CREATED,
    OrderStatus.PENDING,
    OrderStatus.PROCESSING,
]


async def pending_orders(db: AsyncSession) -> list[PaymentOrder]:
    result = await db.execute(
        select(PaymentOrder)
        .where(PaymentOrder.status.in_(OPEN_STATUSES))
        .order_by(PaymentOrder.created_at.desc())
    )
    return list(result.scalars().all())


async def reconcile(db: AsyncSession) -> dict:
    orders = await pending_orders(db)

    provider_orders = [
        order for order in orders if order.provider in {Provider.COINBASE, Provider.MOONPAY}
    ]
    ledger_orders = [
        order for order in orders if order.provider == Provider.LEDGER
    ]
    manual_orders = [
        order for order in orders if order.provider == Provider.MANUAL
    ]

    return {
        "checked": len(orders),
        "provider_open": len(provider_orders),
        "ledger_open": len(ledger_orders),
        "manual_open": len(manual_orders),
        "open_order_ids": [str(order.id) for order in orders],
        "message": (
            "MoonPay/Coinbase provider orders are finalized by provider webhooks. "
            "Ledger and manual direct crypto orders are finalized by Alchemy webhook "
            "or manual admin confirmation."
        ),
    }
