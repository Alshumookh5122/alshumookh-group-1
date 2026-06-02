from __future__ import annotations

import hashlib
import hmac
import time
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy import String, cast, select
from sqlalchemy.ext.asyncio import AsyncSession

from decimal import Decimal

from app.alchemy_service import process_alchemy_webhook, verify_alchemy_signature
from app.audit_service import log_event
from app.config import settings
from app.database import get_db
from app.models import ExternalPayload, OrderStatus, PaymentOrder, PayloadVerificationStatus, Provider
from app.schemas import WebhookAck

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


async def _match_external_payloads(db: AsyncSession, payload: dict) -> int:
    """
    After receiving an Alchemy webhook, try to match pending ExternalPayloads
    by tx_hash, receiver_wallet, amount, asset, and update their status.
    Returns the number of payloads updated.
    """
    from datetime import datetime, timezone

    from app.alchemy_service import (
        _extract_amount,
        _extract_from_address,
        _extract_network,
        _extract_to_address,
        _extract_tx_hash,
        _get_activity_items,
        _normalized_asset,
        _extract_contract_address,
    )

    updated = 0
    items = _get_activity_items(payload)

    for item in items:
        network = _extract_network(payload, item)
        to_address = _extract_to_address(item)
        from_address = _extract_from_address(item)
        contract_address = _extract_contract_address(item)
        tx_hash = _extract_tx_hash(item)
        asset = _normalized_asset(item, contract_address)

        # Try amount as Decimal
        raw_amount = _extract_amount(item)
        amount: Decimal | None = raw_amount

        # Find matching pending ExternalPayloads
        result = await db.execute(
            select(ExternalPayload).where(
                ExternalPayload.verification_status.in_([
                    PayloadVerificationStatus.AWAITING_TX_HASH.value,
                    PayloadVerificationStatus.ALCHEMY_PENDING.value,
                    PayloadVerificationStatus.RECEIVED.value,
                    PayloadVerificationStatus.PARSED.value,
                ])
            )
        )
        candidates = list(result.scalars().all())

        for ep in candidates:
            matched = False

            # Match by tx_hash first (strongest match)
            if tx_hash and ep.tx_hash and tx_hash.lower() == ep.tx_hash.lower():
                matched = True

            # Match by receiver wallet + asset + amount (within 1% tolerance)
            elif to_address and ep.receiver_wallet:
                wallet_match = to_address.lower() == ep.receiver_wallet.lower()
                asset_match = (not ep.asset) or (ep.asset.upper() == asset.upper())
                amount_match = True
                if amount is not None and ep.amount is not None:
                    diff = abs(amount - ep.amount)
                    tolerance = ep.amount * Decimal("0.01")
                    amount_match = diff <= tolerance

                if wallet_match and asset_match and amount_match:
                    matched = True

            if not matched:
                continue

            # Update the payload
            if tx_hash and not ep.tx_hash:
                ep.tx_hash = tx_hash

            ep.verification_status = PayloadVerificationStatus.ALCHEMY_VERIFIED.value
            ep.verified_at = datetime.now(tz=timezone.utc)

            if amount is not None and ep.amount is None:
                ep.amount = amount
            if asset and not ep.asset:
                ep.asset = asset

            await db.commit()
            await db.refresh(ep)
            updated += 1

    return updated


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

    # Also try to match any pending ExternalPayloads (settlement pipeline)
    settlement_matched = await _match_external_payloads(db, payload)

    await log_event(
        db,
        "ALCHEMY_WEBHOOK",
        {
            "processed": processed,
            "settlement_payloads_matched": settlement_matched,
            "payload": payload,
        },
        None,
    )

    return WebhookAck()


@router.get("/alchemy", include_in_schema=False)
async def alchemy_webhook_health():
    return {
        "status": "ok",
        "provider": "alchemy",
        "message": "Alchemy webhook endpoint is ready. Use POST for webhook events.",
    }


# ─────────────────────────────────────────────────────────────────────────────
# Dedicated settlement webhook (also available at /api/v1/webhooks/alchemy)
# This is a second router mounted with the /api/v1 prefix in main.py
# ─────────────────────────────────────────────────────────────────────────────
settlement_webhooks_router = APIRouter(prefix="/webhooks", tags=["settlement-webhooks"])


@settlement_webhooks_router.post("/alchemy", response_model=WebhookAck)
async def settlement_alchemy_webhook(
    request: Request,
    x_alchemy_signature: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    """
    POST /api/v1/webhooks/alchemy
    Alchemy address-activity webhook for the settlement pipeline.
    Verifies Alchemy signature, matches incoming transfers to ExternalPayloads.
    """
    raw = await request.body()

    if not verify_alchemy_signature(raw, x_alchemy_signature):
        raise HTTPException(status_code=401, detail="Invalid Alchemy webhook signature")

    payload = await request.json()

    # Match existing payment orders
    processed = await process_alchemy_webhook(db, payload)

    # Match pending ExternalPayloads (settlement receiver)
    settlement_matched = await _match_external_payloads(db, payload)

    await log_event(
        db,
        "SETTLEMENT_ALCHEMY_WEBHOOK",
        {
            "processed_orders": processed,
            "settlement_payloads_matched": settlement_matched,
        },
        None,
    )

    return WebhookAck()


@settlement_webhooks_router.get("/alchemy", include_in_schema=False)
async def settlement_alchemy_health():
    return {
        "status": "ok",
        "provider": "alchemy",
        "endpoint": "/api/v1/webhooks/alchemy",
        "message": "Settlement Alchemy webhook is ready.",
    }


# ─────────────────────────────────────────────────────────────────────────────
# Circle Programmable Wallets Webhook
# POST /api/v1/webhooks/circle
# ─────────────────────────────────────────────────────────────────────────────

@settlement_webhooks_router.post("/circle", response_model=WebhookAck)
async def circle_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    POST /api/v1/webhooks/circle
    Circle Programmable Wallets webhook — receives transaction and wallet events.
    """
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    notification_type = payload.get("notificationType") or payload.get("Type", "")
    data = payload.get("data") or payload.get("Message") or {}

    await log_event(
        db,
        "CIRCLE_WEBHOOK",
        {
            "notificationType": notification_type,
            "data": data,
        },
        None,
    )

    return WebhookAck()


@settlement_webhooks_router.get("/circle", include_in_schema=False)
async def circle_webhook_health():
    return {
        "status": "ok",
        "provider": "circle",
        "endpoint": "/api/v1/webhooks/circle",
        "message": "Circle webhook is ready.",
    }


def _webhook_secret() -> str | None:
    secret = getattr(settings, "coinbase_webhook_secret", None)

    if not secret:
        return None

    secret = str(secret).strip()

    if not secret:
        return None

    return secret


def _moonpay_webhook_secret() -> str | None:
    secret = getattr(settings, "moonpay_webhook_secret", None)

    if not secret:
        return None

    secret = str(secret).strip()

    if not secret:
        return None

    return secret


def verify_simple_hmac(raw_body: bytes, signature: str | None) -> bool:
    secret = _webhook_secret()

    if not secret:
        return False

    if not signature:
        return False

    signature = signature.removeprefix("sha256=").strip()

    expected = hmac.new(
        secret.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(expected, signature)


def verify_moonpay_signature(
    raw_body: bytes,
    signature: str | None,
    authorization: str | None = None,
) -> bool:
    secret = _moonpay_webhook_secret()

    if not secret:
        return False

    if authorization:
        bearer = authorization.removeprefix("Bearer").strip()

        if bearer and hmac.compare_digest(bearer, secret):
            return True

    if signature:
        signature = signature.removeprefix("sha256=").strip()
        expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)

    return False


def verify_hook0_signature(
    raw_body: bytes,
    signature_header: str | None,
    request_headers: dict[str, str],
    max_age_minutes: int = 5,
) -> bool:
    secret = _webhook_secret()

    if not secret:
        return False

    if not signature_header:
        return False

    try:
        parts = dict(
            item.split("=", 1)
            for item in signature_header.split(",")
            if "=" in item
        )
        timestamp = int(parts["t"])
        header_names = parts["h"]
        provided_signature = parts["v1"]
    except (KeyError, ValueError):
        return False

    age_minutes = (time.time() - timestamp) / 60

    if age_minutes > max_age_minutes:
        return False

    normalized_headers = {
        key.lower(): value
        for key, value in request_headers.items()
    }

    header_values = ".".join(
        normalized_headers.get(name.lower(), "")
        for name in header_names.split(" ")
    )

    signed_payload = (
        f"{timestamp}."
        f"{header_names}."
        f"{header_values}."
        f'{raw_body.decode("utf-8")}'
    )

    expected = hmac.new(
        secret.encode("utf-8"),
        signed_payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(expected, provided_signature)


def verify_coinbase_signature(
    raw_body: bytes,
    hook0_signature: str | None,
    coinbase_signature: str | None,
    webhook_signature: str | None,
    request_headers: dict[str, str],
) -> bool:
    if hook0_signature:
        return verify_hook0_signature(
            raw_body=raw_body,
            signature_header=hook0_signature,
            request_headers=request_headers,
        )

    return verify_simple_hmac(
        raw_body,
        coinbase_signature or webhook_signature,
    )


def _nested_dicts(payload: dict[str, Any]) -> list[dict[str, Any]]:
    nested: list[dict[str, Any]] = [payload]

    for key in ["data", "event", "payload", "resource"]:
        value = payload.get(key)

        if isinstance(value, dict):
            nested.append(value)

    data = payload.get("data")

    if isinstance(data, dict):
        for key in ["event", "payload", "resource"]:
            value = data.get(key)

            if isinstance(value, dict):
                nested.append(value)

    return nested


def extract_coinbase_reference(payload: dict[str, Any]) -> str | None:
    keys = [
        "partnerUserRef",
        "partner_user_ref",
        "partnerUserReference",
        "external_id",
        "externalId",
        "order_id",
        "orderId",
        "id",
    ]

    for item in _nested_dicts(payload):
        for key in keys:
            value = item.get(key)

            if value:
                return str(value)

    return None


def extract_coinbase_provider_order_id(payload: dict[str, Any]) -> str | None:
    keys = [
        "order_id",
        "orderId",
        "transaction_id",
        "transactionId",
        "id",
    ]

    for item in _nested_dicts(payload):
        for key in keys:
            value = item.get(key)

            if value:
                return str(value)

    return None


def extract_coinbase_event_type(payload: dict[str, Any]) -> str:
    keys = [
        "type",
        "event_type",
        "eventType",
        "name",
    ]

    for item in _nested_dicts(payload):
        for key in keys:
            value = item.get(key)

            if value:
                return str(value).lower()

    return ""


def extract_coinbase_status(payload: dict[str, Any]) -> str:
    for item in _nested_dicts(payload):
        value = item.get("status")

        if value:
            return str(value).upper()

    return ""


def extract_coinbase_tx_hash(payload: dict[str, Any]) -> str | None:
    keys = [
        "tx_hash",
        "transaction_hash",
        "transactionHash",
        "hash",
        "txHash",
    ]

    for item in _nested_dicts(payload):
        for key in keys:
            value = item.get(key)

            if value:
                return str(value)

    return None


def extract_moonpay_reference(payload: dict[str, Any]) -> str | None:
    keys = [
        "externalId",
        "external_id",
        "customerId",
        "customer_id",
        "depositCustomerId",
        "deposit_customer_id",
        "paymentId",
        "payment_id",
        "transactionId",
        "transaction_id",
        "id",
    ]

    for item in _nested_dicts(payload):
        metadata = item.get("metadata")

        if isinstance(metadata, dict):
            for key in keys:
                value = metadata.get(key)

                if value:
                    return str(value)

        for key in keys:
            value = item.get(key)

            if value:
                return str(value)

    return None


def extract_moonpay_provider_order_id(payload: dict[str, Any]) -> str | None:
    keys = ["depositCustomerId", "paymentId", "transactionId", "id"]

    for item in _nested_dicts(payload):
        for key in keys:
            value = item.get(key)

            if value:
                return str(value)

    return None


async def find_coinbase_order(
    db: AsyncSession,
    reference: str | None,
) -> PaymentOrder | None:
    if not reference:
        return None

    result = await db.execute(
        select(PaymentOrder)
        .where(
            PaymentOrder.provider == Provider.COINBASE,
            (
                (cast(PaymentOrder.id, String) == str(reference))
                | (PaymentOrder.external_id == reference)
                | (PaymentOrder.payment_reference == reference)
                | (PaymentOrder.provider_order_id == reference)
            ),
        )
        .order_by(PaymentOrder.created_at.desc())
        .limit(1)
    )

    return result.scalar_one_or_none()


async def find_moonpay_order(
    db: AsyncSession,
    reference: str | None,
) -> PaymentOrder | None:
    if not reference:
        return None

    result = await db.execute(
        select(PaymentOrder)
        .where(
            PaymentOrder.provider == Provider.MOONPAY,
            (
                (cast(PaymentOrder.id, String) == str(reference))
                | (PaymentOrder.external_id == reference)
                | (PaymentOrder.payment_reference == reference)
                | (PaymentOrder.provider_order_id == reference)
            ),
        )
        .order_by(PaymentOrder.created_at.desc())
        .limit(1)
    )

    return result.scalar_one_or_none()


def map_coinbase_status(event_type: str, raw_status: str) -> OrderStatus:
    joined = f"{event_type} {raw_status}".lower()

    if any(word in joined for word in ["success", "completed", "complete", "settled"]):
        return OrderStatus.COMPLETED

    if any(word in joined for word in ["failed", "failure", "cancel", "canceled", "expired"]):
        return OrderStatus.FAILED

    if any(word in joined for word in ["pending", "created", "started"]):
        return OrderStatus.PENDING

    if any(word in joined for word in ["processing", "progress", "updated"]):
        return OrderStatus.PROCESSING

    return OrderStatus.PROCESSING


def map_moonpay_status(event_type: str, raw_status: str) -> OrderStatus:
    joined = f"{event_type} {raw_status}".lower()

    if any(word in joined for word in ["success", "successful", "completed", "complete", "confirmed", "paid"]):
        return OrderStatus.COMPLETED

    if any(word in joined for word in ["failed", "failure", "cancel", "canceled", "expired", "rejected"]):
        return OrderStatus.FAILED

    if any(word in joined for word in ["pending", "created", "started", "initiated"]):
        return OrderStatus.PENDING

    if any(word in joined for word in ["processing", "progress", "updated"]):
        return OrderStatus.PROCESSING

    return OrderStatus.PROCESSING


async def handle_coinbase_webhook(
    request: Request,
    x_hook0_signature: str | None,
    x_coinbase_signature: str | None,
    x_webhook_signature: str | None,
    db: AsyncSession,
) -> WebhookAck:
    raw = await request.body()

    if not verify_coinbase_signature(
        raw_body=raw,
        hook0_signature=x_hook0_signature,
        coinbase_signature=x_coinbase_signature,
        webhook_signature=x_webhook_signature,
        request_headers=dict(request.headers),
    ):
        raise HTTPException(status_code=401, detail="Invalid Coinbase webhook signature")

    payload = await request.json()
    event_type = extract_coinbase_event_type(payload)
    raw_status = extract_coinbase_status(payload)
    reference = extract_coinbase_reference(payload)
    provider_order_id = extract_coinbase_provider_order_id(payload)
    tx_hash = extract_coinbase_tx_hash(payload)

    order = await find_coinbase_order(db, reference)

    if not order and provider_order_id:
        order = await find_coinbase_order(db, provider_order_id)

    await log_event(
        db,
        "COINBASE_WEBHOOK",
        {
            "event_type": event_type,
            "raw_status": raw_status,
            "reference": reference,
            "provider_order_id": provider_order_id,
            "tx_hash": tx_hash,
            "matched_order": str(order.id) if order else None,
        },
        str(order.id) if order else None,
        client_id=str(order.client_id) if order and getattr(order, "client_id", None) else None,
    )

    if not order:
        return WebhookAck()

    order.webhook_payload = payload

    if provider_order_id:
        order.provider_order_id = provider_order_id

    if tx_hash:
        order.tx_hash = tx_hash

    order.status = map_coinbase_status(event_type, raw_status)

    if order.status == OrderStatus.FAILED:
        order.failure_reason = event_type or raw_status or "Coinbase payment failed"

    request.state.transaction_id = str(order.id)
    request.state.order_id = str(order.id)

    await db.commit()

    await log_event(
        db,
        "COINBASE_ORDER_STATUS_SYNCED",
        {
            "order_id": str(order.id),
            "status": order.status.value,
            "tx_hash": order.tx_hash,
            "provider_order_id": order.provider_order_id,
        },
        str(order.id),
        client_id=str(order.client_id) if getattr(order, "client_id", None) else None,
    )

    return WebhookAck()


@router.get("/moonpay", include_in_schema=False)
async def moonpay_webhook_health():
    return {
        "status": "ok",
        "provider": "moonpay",
        "message": "MoonPay webhook endpoint is ready. Use POST for webhook events.",
    }


@router.post("/moonpay", response_model=WebhookAck)
async def moonpay_webhook(
    request: Request,
    x_moonpay_signature: str | None = Header(default=None, alias="X-MoonPay-Signature"),
    x_webhook_signature: str | None = Header(default=None, alias="X-Webhook-Signature"),
    x_signature: str | None = Header(default=None, alias="X-Signature"),
    authorization: str | None = Header(default=None, alias="Authorization"),
    db: AsyncSession = Depends(get_db),
):
    raw = await request.body()
    signature = x_moonpay_signature or x_webhook_signature or x_signature

    if not verify_moonpay_signature(raw, signature, authorization):
        raise HTTPException(status_code=401, detail="Invalid MoonPay webhook signature")

    payload = await request.json()
    event_type = extract_coinbase_event_type(payload)
    raw_status = extract_coinbase_status(payload)
    reference = extract_moonpay_reference(payload)
    provider_order_id = extract_moonpay_provider_order_id(payload)
    tx_hash = extract_coinbase_tx_hash(payload)

    order = await find_moonpay_order(db, reference)

    if not order and provider_order_id:
        order = await find_moonpay_order(db, provider_order_id)

    await log_event(
        db,
        "MOONPAY_WEBHOOK",
        {
            "event_type": event_type,
            "raw_status": raw_status,
            "reference": reference,
            "provider_order_id": provider_order_id,
            "tx_hash": tx_hash,
            "matched_order": str(order.id) if order else None,
        },
        str(order.id) if order else None,
        client_id=str(order.client_id) if order and getattr(order, "client_id", None) else None,
    )

    if not order:
        return WebhookAck()

    order.webhook_payload = payload

    if provider_order_id:
        order.provider_order_id = provider_order_id

    if tx_hash:
        order.tx_hash = tx_hash

    order.status = map_moonpay_status(event_type, raw_status)

    if order.status == OrderStatus.FAILED:
        order.failure_reason = event_type or raw_status or "MoonPay payment failed"

    request.state.transaction_id = str(order.id)
    request.state.order_id = str(order.id)

    await db.commit()

    await log_event(
        db,
        "MOONPAY_ORDER_STATUS_SYNCED",
        {
            "order_id": str(order.id),
            "status": order.status.value,
            "tx_hash": order.tx_hash,
            "provider_order_id": order.provider_order_id,
        },
        str(order.id),
        client_id=str(order.client_id) if getattr(order, "client_id", None) else None,
    )

    return WebhookAck()


@router.post("/coinbase", response_model=WebhookAck)
async def coinbase_webhook(
    request: Request,
    x_hook0_signature: str | None = Header(default=None, alias="X-Hook0-Signature"),
    x_coinbase_signature: str | None = Header(default=None, alias="X-Coinbase-Signature"),
    x_webhook_signature: str | None = Header(default=None, alias="X-Webhook-Signature"),
    db: AsyncSession = Depends(get_db),
):
    return await handle_coinbase_webhook(
        request=request,
        x_hook0_signature=x_hook0_signature,
        x_coinbase_signature=x_coinbase_signature,
        x_webhook_signature=x_webhook_signature,
        db=db,
    )


@router.post("/coinbase/onramp", response_model=WebhookAck)
async def coinbase_onramp_webhook(
    request: Request,
    x_hook0_signature: str | None = Header(default=None, alias="X-Hook0-Signature"),
    x_coinbase_signature: str | None = Header(default=None, alias="X-Coinbase-Signature"),
    x_webhook_signature: str | None = Header(default=None, alias="X-Webhook-Signature"),
    db: AsyncSession = Depends(get_db),
):
    return await handle_coinbase_webhook(
        request=request,
        x_hook0_signature=x_hook0_signature,
        x_coinbase_signature=x_coinbase_signature,
        x_webhook_signature=x_webhook_signature,
        db=db,
    )
