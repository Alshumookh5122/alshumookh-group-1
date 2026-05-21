from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
import uuid
from decimal import Decimal, ROUND_HALF_UP
from typing import Any
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import desc, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit_service import log_event
from app.config import settings
from app.database import get_db
from app.deps import AdminKey
from app.models import Network, OrderSide, OrderStatus, PaymentOrder, Provider
from app.request_utils import get_client_ip

router = APIRouter(tags=["stripe"])
logger = logging.getLogger(__name__)

ZERO_DECIMAL_CURRENCIES = {
    "bif",
    "clp",
    "djf",
    "gnf",
    "jpy",
    "kmf",
    "krw",
    "mga",
    "pyg",
    "rwf",
    "ugx",
    "vnd",
    "vuv",
    "xaf",
    "xof",
    "xpf",
}


class StripePaymentRequest(BaseModel):
    amount: Decimal = Field(..., gt=0)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    description: str = Field(default="ALSHUMOOKH payment", max_length=180)
    customer_email: EmailStr | None = None
    external_id: str | None = Field(default=None, max_length=128)
    success_url: str | None = Field(default=None, max_length=2048)
    cancel_url: str | None = Field(default=None, max_length=2048)


def _stripe_enabled() -> bool:
    return bool(str(settings.stripe_secret_key or "").strip())


def _stripe_mode() -> str:
    key = str(settings.stripe_secret_key or "")
    if key.startswith("sk_live_"):
        return "live"
    if key.startswith("sk_test_"):
        return "test"
    return "unknown"


def _minor_units(amount: Decimal, currency: str) -> int:
    normalized_currency = currency.lower()
    exponent = Decimal("1") if normalized_currency in ZERO_DECIMAL_CURRENCIES else Decimal("100")
    value = (amount * exponent).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(value)


def _request_base_url(request: Request) -> str:
    forwarded_proto = request.headers.get("x-forwarded-proto")
    forwarded_host = request.headers.get("x-forwarded-host")
    proto = (forwarded_proto.split(",", 1)[0].strip() if forwarded_proto else request.url.scheme) or "https"
    host = (forwarded_host.split(",", 1)[0].strip() if forwarded_host else request.headers.get("host")) or request.url.netloc
    return f"{proto}://{host}".rstrip("/")


def _default_success_url(request: Request) -> str:
    return settings.stripe_success_url or f"{_request_base_url(request)}/pay/success?session_id={{CHECKOUT_SESSION_ID}}"


def _default_cancel_url(request: Request) -> str:
    return settings.stripe_cancel_url or f"{_request_base_url(request)}/login?type=client"


def _invoice_url(request: Request, order_id: str) -> str:
    return f"{_request_base_url(request)}{settings.api_prefix}/admin/orders/{order_id}/documents/invoice"


async def _stripe_request(
    method: str,
    path: str,
    data: list[tuple[str, str | int]] | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    if not _stripe_enabled():
        raise HTTPException(status_code=503, detail="Stripe is not configured")

    headers = {
        "Authorization": f"Bearer {settings.stripe_secret_key}",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key

    form_data = [(key, str(value)) for key, value in (data or [])]
    encoded_data = urlencode(form_data)
    url = f"{settings.stripe_api_base_url.rstrip('/')}/{path.lstrip('/')}"
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            response = await client.request(method, url, content=encoded_data, headers=headers)
        except (RuntimeError, TypeError, ValueError, httpx.RequestError) as exc:
            raise HTTPException(status_code=502, detail=f"Stripe network error: {exc}") from exc

    if response.status_code >= 400:
        try:
            payload = response.json()
        except ValueError:
            payload = {"error": response.text}
        message = payload.get("error", {}).get("message") if isinstance(payload.get("error"), dict) else None
        raise HTTPException(status_code=response.status_code, detail=message or payload)

    return response.json()


def _base_order(payload: StripePaymentRequest, idempotency_key: str, order_id: str) -> PaymentOrder:
    reference = payload.external_id or f"STR-{uuid.uuid4().hex[:12].upper()}"
    return PaymentOrder(
        id=order_id,
        idempotency_key=idempotency_key,
        external_id=payload.external_id,
        provider=Provider.STRIPE,
        side=OrderSide.BUY,
        status=OrderStatus.CREATED,
        network=Network.ETHEREUM,
        fiat_currency=payload.currency.upper(),
        fiat_amount=payload.amount,
        crypto_currency=payload.currency.upper(),
        crypto_amount=payload.amount,
        payer_email=str(payload.customer_email) if payload.customer_email else None,
        payment_reference=reference,
    )


def _order_payload(order: PaymentOrder) -> dict[str, Any]:
    invoice_path = f"{settings.api_prefix}/admin/orders/{order.id}/documents/invoice"
    return {
        "id": order.id,
        "external_id": order.external_id,
        "provider": order.provider.value if hasattr(order.provider, "value") else str(order.provider),
        "status": order.status.value if hasattr(order.status, "value") else str(order.status),
        "fiat_currency": order.fiat_currency,
        "fiat_amount": str(order.fiat_amount or ""),
        "payer_email": order.payer_email,
        "payment_reference": order.payment_reference,
        "provider_order_id": order.provider_order_id,
        "checkout_url": order.checkout_url,
        "invoice_url": invoice_path,
        "created_at": order.created_at.isoformat() if order.created_at else None,
        "updated_at": order.updated_at.isoformat() if order.updated_at else None,
    }


async def _save_new_order(db: AsyncSession, order: PaymentOrder) -> None:
    try:
        db.add(order)
        await db.commit()
        await db.refresh(order)
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.exception("Stripe order persistence failed before creating provider link")
        raise HTTPException(
            status_code=500,
            detail=f"Stripe order could not be saved before link creation: {type(exc).__name__}",
        ) from exc


async def _mark_order_failed(db: AsyncSession, order: PaymentOrder, exc: Exception) -> None:
    order.status = OrderStatus.FAILED
    order.failure_reason = str(exc)[:2000]
    try:
        await db.commit()
        await db.refresh(order)
    except SQLAlchemyError:
        await db.rollback()
        logger.exception("Failed to persist Stripe failure state for order %s", order.id)


async def _finalize_order(
    db: AsyncSession,
    order: PaymentOrder,
    *,
    provider_order_id: str,
    checkout_url: str,
    quote: dict[str, Any],
) -> None:
    order.provider_order_id = provider_order_id
    order.checkout_url = checkout_url
    order.status = OrderStatus.PENDING
    order.quote_json = jsonable_encoder(quote)
    try:
        await db.commit()
        await db.refresh(order)
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.exception("Stripe provider link created but order update failed")
        raise HTTPException(
            status_code=500,
            detail=f"Stripe link was created but transaction record update failed: {type(exc).__name__}",
        ) from exc


@router.get("/admin/stripe/status")
async def stripe_status(request: Request, _: AdminKey):
    return {
        "configured": _stripe_enabled(),
        "mode": _stripe_mode(),
        "publishable_key_configured": bool(settings.stripe_publishable_key),
        "webhook_configured": bool(settings.stripe_webhook_secret),
        "webhook_url": f"{_request_base_url(request)}{settings.api_prefix}/webhooks/stripe",
        "configured_public_base_url": settings.public_base_url,
    }


@router.get("/admin/stripe/orders")
async def list_stripe_orders(_: AdminKey, db: AsyncSession = Depends(get_db), limit: int = 25):
    result = await db.execute(
        select(PaymentOrder)
        .where(PaymentOrder.provider == Provider.STRIPE)
        .order_by(desc(PaymentOrder.created_at))
        .limit(max(1, min(limit, 100)))
    )
    return {"orders": [_order_payload(order) for order in result.scalars().all()]}


@router.post("/admin/stripe/checkout-sessions")
async def create_checkout_session(
    request: Request,
    payload: StripePaymentRequest,
    _: AdminKey,
    db: AsyncSession = Depends(get_db),
):
    if not _stripe_enabled():
        raise HTTPException(status_code=503, detail="Stripe is not configured. Set STRIPE_SECRET_KEY in Render environment variables.")

    idempotency_key = f"stripe-checkout-{uuid.uuid4()}"
    order_id = str(uuid.uuid4())
    order = _base_order(payload, idempotency_key, order_id)
    await _save_new_order(db, order)

    amount_minor = _minor_units(payload.amount, payload.currency)
    data: list[tuple[str, str | int]] = [
        ("mode", "payment"),
        ("success_url", payload.success_url or _default_success_url(request)),
        ("cancel_url", payload.cancel_url or _default_cancel_url(request)),
        ("client_reference_id", order.id),
        ("metadata[order_id]", order.id),
        ("metadata[payment_reference]", order.payment_reference or order.id),
        ("payment_intent_data[metadata][order_id]", order.id),
        ("payment_intent_data[metadata][payment_reference]", order.payment_reference or order.id),
        ("line_items[0][quantity]", 1),
        ("line_items[0][price_data][currency]", payload.currency.lower()),
        ("line_items[0][price_data][unit_amount]", amount_minor),
        ("line_items[0][price_data][product_data][name]", payload.description),
    ]
    if payload.customer_email:
        data.append(("customer_email", str(payload.customer_email)))

    try:
        session = await _stripe_request(
            "POST",
            "/checkout/sessions",
            data,
            idempotency_key=idempotency_key,
        )
    except HTTPException as exc:
        await _mark_order_failed(db, order, exc)
        raise

    await _finalize_order(
        db,
        order,
        provider_order_id=str(session.get("id") or ""),
        checkout_url=str(session.get("url") or ""),
        quote={"stripe_checkout_session": session},
    )
    await log_event(
        db,
        "STRIPE_CHECKOUT_SESSION_CREATED",
        {
            "provider_order_id": order.provider_order_id,
            "checkout_url": order.checkout_url,
            "invoice_url": _invoice_url(request, order.id),
            "amount": str(payload.amount),
            "currency": payload.currency.upper(),
        },
        order.id,
        endpoint=str(request.url.path),
        method=request.method,
        ip=get_client_ip(request),
        user_agent=request.headers.get("user-agent"),
        status_code=201,
        transaction_id=order.provider_order_id,
        request_id=getattr(request.state, "request_id", None),
    )

    return {
        "order": _order_payload(order),
        "checkout_session": session,
        "invoice_url": _invoice_url(request, order.id),
    }


@router.post("/admin/stripe/payment-links")
async def create_payment_link(
    request: Request,
    payload: StripePaymentRequest,
    _: AdminKey,
    db: AsyncSession = Depends(get_db),
):
    if not _stripe_enabled():
        raise HTTPException(status_code=503, detail="Stripe is not configured. Set STRIPE_SECRET_KEY in Render environment variables.")

    idempotency_key = f"stripe-link-{uuid.uuid4()}"
    order_id = str(uuid.uuid4())
    order = _base_order(payload, idempotency_key, order_id)
    await _save_new_order(db, order)

    amount_minor = _minor_units(payload.amount, payload.currency)
    try:
        link = await _stripe_request(
            "POST",
            "/payment_links",
            [
                ("line_items[0][price_data][product_data][name]", payload.description),
                ("line_items[0][price_data][currency]", payload.currency.lower()),
                ("line_items[0][price_data][unit_amount]", amount_minor),
                ("line_items[0][quantity]", 1),
                ("metadata[order_id]", order.id),
                ("metadata[payment_reference]", order.payment_reference or order.id),
            ],
            idempotency_key=idempotency_key,
        )
    except HTTPException as exc:
        await _mark_order_failed(db, order, exc)
        raise

    await _finalize_order(
        db,
        order,
        provider_order_id=str(link.get("id") or ""),
        checkout_url=str(link.get("url") or ""),
        quote={"stripe_payment_link": link},
    )
    await log_event(
        db,
        "STRIPE_PAYMENT_LINK_CREATED",
        {
            "provider_order_id": order.provider_order_id,
            "checkout_url": order.checkout_url,
            "invoice_url": _invoice_url(request, order.id),
            "amount": str(payload.amount),
            "currency": payload.currency.upper(),
        },
        order.id,
        endpoint=str(request.url.path),
        method=request.method,
        ip=get_client_ip(request),
        user_agent=request.headers.get("user-agent"),
        status_code=201,
        transaction_id=order.provider_order_id,
        request_id=getattr(request.state, "request_id", None),
    )

    return {
        "order": _order_payload(order),
        "payment_link": link,
        "invoice_url": _invoice_url(request, order.id),
    }


def _verify_stripe_signature(body: bytes, signature_header: str | None) -> None:
    secret = str(settings.stripe_webhook_secret or "").strip()
    if not secret:
        raise HTTPException(status_code=503, detail="Stripe webhook secret is not configured")
    if not signature_header:
        raise HTTPException(status_code=400, detail="Missing Stripe-Signature header")

    parts: dict[str, list[str]] = {}
    for item in signature_header.split(","):
        if "=" not in item:
            continue
        key, value = item.split("=", 1)
        parts.setdefault(key, []).append(value)

    timestamp = (parts.get("t") or [""])[0]
    signatures = parts.get("v1") or []
    if not timestamp or not signatures:
        raise HTTPException(status_code=400, detail="Invalid Stripe signature header")

    try:
        timestamp_int = int(timestamp)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid Stripe signature timestamp") from exc

    if abs(int(time.time()) - timestamp_int) > 300:
        raise HTTPException(status_code=400, detail="Expired Stripe webhook signature")

    signed_payload = timestamp.encode() + b"." + body
    expected = hmac.new(secret.encode(), signed_payload, hashlib.sha256).hexdigest()
    if not any(hmac.compare_digest(expected, provided) for provided in signatures):
        raise HTTPException(status_code=400, detail="Invalid Stripe webhook signature")


def _status_for_stripe_event(event_type: str, obj: dict[str, Any]) -> OrderStatus | None:
    if event_type == "checkout.session.completed":
        return OrderStatus.COMPLETED if obj.get("payment_status") == "paid" else OrderStatus.PROCESSING
    if event_type in {"payment_intent.succeeded", "charge.succeeded"}:
        return OrderStatus.COMPLETED
    if event_type == "checkout.session.expired":
        return OrderStatus.EXPIRED
    if event_type in {"payment_intent.payment_failed", "charge.failed"}:
        return OrderStatus.FAILED
    return None


async def _find_stripe_order(db: AsyncSession, obj: dict[str, Any]) -> PaymentOrder | None:
    metadata = obj.get("metadata") if isinstance(obj.get("metadata"), dict) else {}
    order_id = metadata.get("order_id") or obj.get("client_reference_id")
    provider_id = obj.get("id")
    payment_intent_id = obj.get("payment_intent")

    clauses = []
    if order_id:
        clauses.append(PaymentOrder.id == str(order_id))
    if provider_id:
        clauses.append(PaymentOrder.provider_order_id == str(provider_id))
    if payment_intent_id:
        clauses.append(PaymentOrder.provider_order_id == str(payment_intent_id))
    if not clauses:
        return None

    result = await db.execute(
        select(PaymentOrder).where(PaymentOrder.provider == Provider.STRIPE).where(or_(*clauses)).limit(1)
    )
    return result.scalar_one_or_none()


@router.post("/webhooks/stripe")
async def stripe_webhook(
    request: Request,
    stripe_signature: str | None = Header(default=None, alias="Stripe-Signature"),
    db: AsyncSession = Depends(get_db),
):
    body = await request.body()
    _verify_stripe_signature(body, stripe_signature)

    try:
        event = json.loads(body.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid Stripe webhook payload") from exc

    event_type = str(event.get("type") or "")
    obj = event.get("data", {}).get("object", {}) if isinstance(event.get("data"), dict) else {}
    if not isinstance(obj, dict):
        return {"received": True, "updated": False}

    order = await _find_stripe_order(db, obj)
    if not order:
        return {"received": True, "updated": False}

    next_status = _status_for_stripe_event(event_type, obj)
    if next_status:
        order.status = next_status
    if obj.get("id") and not order.provider_order_id:
        order.provider_order_id = str(obj.get("id"))
    if obj.get("url") and not order.checkout_url:
        order.checkout_url = str(obj.get("url"))
    if obj.get("customer_details", {}).get("email"):
        order.payer_email = str(obj["customer_details"]["email"])
    if event_type in {"payment_intent.payment_failed", "charge.failed"}:
        error = obj.get("last_payment_error") or obj.get("failure_message") or "Stripe payment failed"
        order.failure_reason = json.dumps(error) if isinstance(error, dict) else str(error)
    order.webhook_payload = jsonable_encoder(event)
    await db.commit()

    return {"received": True, "updated": True, "order_id": order.id, "status": order.status.value}
