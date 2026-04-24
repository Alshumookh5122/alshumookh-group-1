from __future__ import annotations

import jwt
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.alchemy_service import process_alchemy_webhook, verify_alchemy_signature
from app.audit_service import log_event
from app.database import get_db
from app.models import Network, OrderStatus, PaymentOrder, Provider
from app.provider_service import TransakProvider
from app.schemas import WebhookAck
from app.transfer_service import handle_order_completed

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/alchemy", response_model=WebhookAck)
async def alchemy_webhook(
    request: Request,
    x_alchemy_signature: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    raw = await request.body()

    if not verify_alchemy_signature(raw, x_alchemy_signature):
        raise HTTPException(status_code=401, detail="Invalid Alchemy signature")

    payload = await request.json()

    processed = await process_alchemy_webhook(db, payload)

    await log_event(
        db,
        "ALCHEMY_WEBHOOK",
        {
            "processed": processed,
            "payload": payload,
        },
    )

    return WebhookAck()


def _event_data(decoded: dict) -> dict:
    data = decoded.get("eventData") or decoded.get("data") or {}
    return data if isinstance(data, dict) else {}


def _normalize_event_name(decoded: dict) -> str:
    raw = decoded.get("eventName") or decoded.get("eventType") or decoded.get("event") or ""
    return str(raw).upper().replace(" ", "_")


def _normalize_network(value: str | None) -> Network | None:
    if not value:
        return None

    value = value.lower()

    if value in {"ethereum", "eth", "erc20"}:
        return Network.ETHEREUM

    if value in {"tron", "trx", "trc20"}:
        return Network.TRON

    return None


async def _find_order_for_transak_event(
    db: AsyncSession,
    decoded: dict,
) -> PaymentOrder | None:
    event_data = _event_data(decoded)

    candidate_ids = [
        event_data.get("orderId"),
        event_data.get("id"),
        decoded.get("orderId"),
        decoded.get("id"),
        event_data.get("partnerOrderId"),
        decoded.get("partnerOrderId"),
        event_data.get("externalId"),
        decoded.get("externalId"),
    ]

    for external_id in [str(x) for x in candidate_ids if x]:
        result = await db.execute(
            select(PaymentOrder)
            .where(
                PaymentOrder.provider == Provider.TRANSAK,
                PaymentOrder.external_id == external_id,
            )
            .order_by(PaymentOrder.created_at.desc())
            .limit(1)
        )

        order = result.scalar_one_or_none()

        if order:
            return order

    wallet = (
        event_data.get("walletAddress")
        or event_data.get("wallet_address")
        or decoded.get("walletAddress")
    )

    crypto_amount = (
        event_data.get("cryptoAmount")
        or event_data.get("crypto_amount")
        or decoded.get("cryptoAmount")
    )

    network = _normalize_network(
        event_data.get("network")
        or decoded.get("network")
    )

    if wallet:
        result = await db.execute(
            select(PaymentOrder)
            .where(
                PaymentOrder.provider == Provider.TRANSAK,
                PaymentOrder.user_wallet_address == str(wallet),
                PaymentOrder.status.in_(
                    [
                        OrderStatus.CREATED,
                        OrderStatus.PENDING,
                        OrderStatus.PROCESSING,
                    ]
                ),
            )
            .order_by(PaymentOrder.created_at.desc())
        )

        orders = list(result.scalars().all())

        if len(orders) == 1:
            return orders[0]

        for order in orders:
            amount_matches = crypto_amount is None or str(order.crypto_amount) == str(crypto_amount)
            network_matches = network is None or order.network == network

            if amount_matches and network_matches:
                return order

    return None


@router.post("/transak", response_model=WebhookAck)
async def transak_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    payload = await request.json()
    token = payload.get("data")

    if not token:
        raise HTTPException(status_code=400, detail="Missing signed data token")

    partner = TransakProvider()

    try:
        access_token = await partner.refresh_access_token()
        decoded = jwt.decode(
            token,
            access_token,
            algorithms=["HS256", "HS512"],
            options={"verify_aud": False},
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=401,
            detail=f"Invalid Transak webhook token: {exc}",
        ) from exc

    event_type = _normalize_event_name(decoded)
    order = await _find_order_for_transak_event(db, decoded)
    order_id = getattr(order, "id", None)

    await log_event(
        db,
        "TRANSAK_WEBHOOK",
        {
            "eventID": payload.get("eventID"),
            "event_type": event_type,
            "decoded": decoded,
            "matched_order": str(order_id) if order_id else None,
        },
        order_id,
    )

    if not order:
        await log_event(
            db,
            "TRANSAK_ORDER_NOT_FOUND",
            {"decoded": decoded},
            None,
        )
        return WebhookAck()

    order.webhook_payload = decoded

    status_map = {
        "ORDER_CREATED": OrderStatus.CREATED,
        "ORDER_PENDING": OrderStatus.PENDING,
        "ORDER_PROCESSING": OrderStatus.PROCESSING,
        "ORDER_FAILED": OrderStatus.FAILED,
        "ORDER_CANCELLED": OrderStatus.FAILED,
        "ORDER_CANCELED": OrderStatus.FAILED,
        "ORDER_REFUNDED": OrderStatus.REFUNDED,
        "ORDER_EXPIRED": OrderStatus.EXPIRED,
    }

    if event_type == "ORDER_COMPLETED":
        await handle_order_completed(db, order, decoded)
        return WebhookAck()

    if event_type in status_map:
        order.status = status_map[event_type]

        if order.status in {
            OrderStatus.FAILED,
            OrderStatus.REFUNDED,
            OrderStatus.EXPIRED,
        }:
            event_data = _event_data(decoded)
            order.failure_reason = event_data.get("reason") or decoded.get("message")

        await db.commit()

        await log_event(
            db,
            "ORDER_STATUS_SYNCED",
            {"status": order.status.value},
            order.id,
        )

        return WebhookAck()

    await log_event(
        db,
        "TRANSAK_WEBHOOK_UNHANDLED",
        {
            "event_type": event_type,
            "decoded": decoded,
        },
        order.id,
    )

    await db.commit()

    return WebhookAck()
