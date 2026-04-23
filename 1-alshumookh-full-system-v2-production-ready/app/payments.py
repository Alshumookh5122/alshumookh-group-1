from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit_service import log_event
from app.database import get_db
from app.models import PaymentOrder, Provider
from app.provider_service import get_provider
from app.schemas import OrderCreate, OrderRead, WidgetUrlRequest, WidgetUrlResponse

router = APIRouter(prefix='/payments', tags=['payments'])


@router.post('/transak/widget-url', response_model=WidgetUrlResponse)
async def create_transak_widget_url(payload: WidgetUrlRequest):
    provider = await get_provider(Provider.TRANSAK)
    widget_url = await provider.create_widget_url(payload.model_dump(mode='json', exclude_none=True))
    return WidgetUrlResponse(widget_url=widget_url)


@router.post('/orders', response_model=OrderRead)
async def create_order(payload: OrderCreate, db: AsyncSession = Depends(get_db)):
    order = PaymentOrder(
        external_id=payload.external_id,
        provider=payload.provider,
        side=payload.side,
        network=payload.network,
        fiat_currency=payload.fiat_currency,
        crypto_currency=payload.crypto_currency,
        fiat_amount=payload.fiat_amount,
        crypto_amount=payload.crypto_amount,
        user_wallet_address=payload.user_wallet_address,
    )
    db.add(order)
    await db.commit()
    await db.refresh(order)
    await log_event(db, 'ORDER_CREATED', {'external_id': order.external_id}, order.id)
    return OrderRead(
        id=str(order.id),
        external_id=order.external_id,
        provider=order.provider,
        side=order.side,
        status=order.status,
        network=order.network,
        fiat_currency=order.fiat_currency,
        crypto_currency=order.crypto_currency,
        fiat_amount=order.fiat_amount,
        crypto_amount=order.crypto_amount,
        user_wallet_address=order.user_wallet_address,
        created_at=order.created_at,
    )
