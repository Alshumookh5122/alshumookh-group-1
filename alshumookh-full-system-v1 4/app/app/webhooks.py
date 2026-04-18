"""
Webhooks Router — receives and processes events from Alchemy and Stripe.
"""

import json
from decimal import Decimal
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Request, Header
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update

from app.app.config import settings
from app.app.database import get_db
from app.app.models import WebhookEvent, Payment, PaymentStatus, AuditLog, AuditAction
from app.app.matching_service import MatchingService
from app.app.utils import verify_alchemy_signature
import structlog

logger = structlog.get_logger()
router = APIRouter(prefix="/webhooks", tags=["Webhooks"])


async def _save_webhook_event(db, provider: str, event_type: str, event_id: str, payload: dict) -> WebhookEvent:
    existing = await db.execute(
        select(WebhookEvent).where(
            WebhookEvent.provider == provider,
            WebhookEvent.event_id == event_id,
        )
    )
    if existing.scalar_one_or_none():
        raise ValueError(f"Duplicate event: {event_id}")

    event = WebhookEvent(provider=provider, event_type=event_type, event_id=event_id, payload=payload)
    db.add(event)
    await db.flush()
    return event


@router.post("/alchemy")
async def alchemy_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
    x_alchemy_signature: str = Header(None, alias="X-Alchemy-Signature"),
):
    raw_body = await request.body()

    if settings.ALCHEMY_WEBHOOK_SECRET and x_alchemy_signature:
        if not verify_alchemy_signature(raw_body, x_alchemy_signature):
            logger.warning("alchemy.invalid_signature")
            raise HTTPException(status_code=401, detail="Invalid webhook signature")

    payload = json.loads(raw_body)
    event_type = payload.get("type", "unknown")
    event_id = payload.get("id", "")

    try:
        webhook_event = await _save_webhook_event(db, "alchemy", event_type, event_id, payload)
    except ValueError:
        logger.info("alchemy.duplicate_event", event_id=event_id)
        return {"status": "already_processed"}

    try:
        if event_type == "ADDRESS_ACTIVITY":
            await _process_alchemy_address_activity(db, payload)

        await db.execute(
            update(WebhookEvent).where(WebhookEvent.id == webhook_event.id).values(processed=True)
        )
        await db.commit()
        logger.info("alchemy.webhook_processed", event_type=event_type, event_id=event_id)
    except Exception as e:
        logger.error("alchemy.webhook_processing_failed", error=str(e), event_id=event_id)
        await db.execute(
            update(WebhookEvent).where(WebhookEvent.id == webhook_event.id).values(error=str(e))
        )
        await db.commit()
        raise HTTPException(500, "Webhook processing failed")

    return {"status": "ok"}


async def _process_alchemy_address_activity(db: AsyncSession, payload: Dict[str, Any]):
    activities = payload.get("event", {}).get("activity", [])
    network = payload.get("event", {}).get("network", settings.ALCHEMY_NETWORK)

    for activity in activities:
        category = activity.get("category", "")
        if category not in ("external", "erc20", "internal"):
            continue

        to_address = activity.get("toAddress", "").lower()
        from_address = activity.get("fromAddress", "").lower()
        asset = activity.get("asset", "ETH").upper()
        value = Decimal(str(activity.get("value", "0")))
        tx_hash = activity.get("hash", "")
        block_num = activity.get("blockNum")
        if block_num:
            block_num = int(block_num, 16) if isinstance(block_num, str) else int(block_num)

        if not to_address or not tx_hash or value <= 0:
            continue

        await MatchingService.process_incoming_transfer(
            db=db, to_address=to_address, from_address=from_address,
            amount=value, token_symbol=asset, tx_hash=tx_hash,
            block_number=block_num, network=network, raw_data=activity,
        )


@router.post("/stripe")
async def stripe_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
    stripe_signature: str = Header(None, alias="Stripe-Signature"),
):
    import stripe
    stripe.api_key = settings.STRIPE_SECRET_KEY

    raw_body = await request.body()

    try:
        event = stripe.Webhook.construct_event(
            raw_body, stripe_signature, settings.STRIPE_WEBHOOK_SECRET
        )
    except stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=401, detail="Invalid Stripe signature")
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    event_type = event["type"]
    event_id = event["id"]

    try:
        webhook_event = await _save_webhook_event(db, "stripe", event_type, event_id, dict(event))
    except ValueError:
        return {"status": "already_processed"}

    try:
        await _process_stripe_event(db, event)
        await db.execute(
            update(WebhookEvent).where(WebhookEvent.id == webhook_event.id).values(processed=True)
        )
        await db.commit()
    except Exception as e:
        logger.error("stripe.webhook_processing_failed", error=str(e))
        await db.execute(
            update(WebhookEvent).where(WebhookEvent.id == webhook_event.id).values(error=str(e))
        )
        await db.commit()
        raise HTTPException(500, "Webhook processing failed")

    return {"status": "ok"}


async def _process_stripe_event(db: AsyncSession, event: Dict[str, Any]):
    import datetime

    event_type = event["type"]
    data_object = event["data"]["object"]
    pi_id = data_object.get("id", "")

    STATUS_MAP = {
        "payment_intent.succeeded": PaymentStatus.COMPLETED,
        "payment_intent.payment_failed": PaymentStatus.FAILED,
        "payment_intent.canceled": PaymentStatus.CANCELLED,
        "payment_intent.processing": PaymentStatus.PROCESSING,
    }

    new_status = STATUS_MAP.get(event_type)
    if not new_status:
        return

    result = await db.execute(
        select(Payment).where(Payment.provider_payment_id == pi_id)
    )
    payment = result.scalar_one_or_none()
    if not payment:
        logger.info("stripe.payment_not_found", pi_id=pi_id)
        return

    update_values = {"status": new_status}
    if new_status == PaymentStatus.COMPLETED:
        update_values["completed_at"] = datetime.datetime.utcnow()

    await db.execute(update(Payment).where(Payment.id == payment.id).values(**update_values))

    db.add(AuditLog(
        user_id=payment.user_id,
        action=AuditAction.PAYMENT_COMPLETED if new_status == PaymentStatus.COMPLETED else AuditAction.PAYMENT_FAILED,
        resource_type="payment",
        resource_id=payment.id,
        details={"stripe_event": event_type, "pi_id": pi_id},
    ))
    logger.info("stripe.payment_updated", payment_id=payment.id, status=new_status.value)
