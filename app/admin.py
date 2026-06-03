import base64
import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import httpx
from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel
from fastapi.responses import HTMLResponse, Response
from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import (
    create_api_key,
    create_hmac_secret,
    create_oauth_client_id,
    create_oauth_client_secret,
    hash_api_key,
    hash_oauth_secret,
)
from app.audit_service import log_event
from app.config import settings
from app.database import get_db
from app.deps import AdminKey
from app.document_service import document_summary, render_order_document
from app.models import (
    ApiClient,
    AuditLog,
    ClientAccount,
    ExternalPayload,
    M1TokenizationJob,
    M1TokenizationStatus,
    Network,
    OrderSide,
    OrderStatus,
    OutboundTransfer,
    OutboundTransferStatus,
    PaymentOrder,
    Provider,
    TransactionFile,
    TreasuryWallet,
)
from app.provider_service import get_provider, OnramperProvider
from app.reconciliation_service import reconcile
from app.request_utils import get_client_ip
from app.security import runtime_security_snapshot
from app.schemas import ApiClientCreate, ApiClientCreated, ApiClientRead, ApiClientUpdate
from app.transfer_service import (
    approve_outbound_transfer,
    broadcast_outbound_transfer,
    cancel_outbound_transfer,
    create_outbound_transfer,
    estimate_usdt_transfer_fee,
)
from app.tokenization_service import (
    create_tokenization_job,
    fetch_live_eur_usd,
    get_job_summary,
    process_tokenization_job,
)
from app.notification_service import (
    notify_transfer_completed,
    notify_transfer_failed,
    notify_m1_job_ready,
)

router = APIRouter(prefix="/admin", tags=["admin"])

ETHEREUM_LEDGER_WALLET = "0xBD682cfD8382a90adfDd6745780D3D7959c4d939"
TRON_LEDGER_WALLET = "TLARV2U9NzuK9QfzV3PQjwabQTGiEEqjTn"


def _request_ip(request: Request) -> str | None:
    return get_client_ip(request)


def _ledger_address(network: Network) -> str:
    try:
        return settings.get_treasury_address(network.value)
    except ValueError:
        if network == Network.ETHEREUM:
            return ETHEREUM_LEDGER_WALLET
        if network == Network.TRON:
            return TRON_LEDGER_WALLET

        raise HTTPException(
            status_code=400,
            detail=f"Treasury wallet address is not configured for {network.value}",
        )


def _order_response(order: PaymentOrder) -> dict:
    return {
        "transaction_id": str(order.id),
        "id": str(order.id),
        "external_id": order.external_id,
        "status": order.status.value,
        "provider": order.provider.value,
        "network": order.network.value,
        "fiat_currency": order.fiat_currency,
        "crypto_currency": order.crypto_currency,
        "fiat_amount": str(order.fiat_amount) if order.fiat_amount is not None else None,
        "crypto_amount": str(order.crypto_amount) if order.crypto_amount is not None else None,
        "destination_address": getattr(order, "treasury_wallet_address", None)
        or order.user_wallet_address,
        "checkout_url": getattr(order, "checkout_url", None)
        or getattr(order, "coinbase_session_url", None),
        "payment_url": getattr(order, "checkout_url", None)
        or getattr(order, "coinbase_session_url", None),
        "provider_order_id": getattr(order, "provider_order_id", None),
        "quote": order.quote_json,
        "created_at": order.created_at,
    }


def serialize_log(log: AuditLog) -> dict:
    return {
        "id": str(log.id),
        "order_id": str(log.order_id) if log.order_id else None,
        "client_id": str(getattr(log, "client_id", None))
        if getattr(log, "client_id", None)
        else None,
        "event_type": log.event_type,
        "endpoint": getattr(log, "endpoint", None),
        "method": getattr(log, "method", None),
        "ip": getattr(log, "ip", None),
        "user_agent": getattr(log, "user_agent", None),
        "status_code": getattr(log, "status_code", None),
        "transaction_id": getattr(log, "transaction_id", None),
        "request_id": getattr(log, "request_id", None),
        "error_message": getattr(log, "error_message", None),
        "details": log.details,
        "created_at": log.created_at,
    }


def _client_security_posture(client: ApiClient) -> tuple[str, int]:
    score = 0
    if client.allowed_ips:
        score += 1
    if client.hmac_required:
        score += 1
    if client.oauth_required:
        score += 1
    if client.mtls_required and client.mtls_cert_fingerprint:
        score += 1
    if client.jws_required:
        score += 1
    if client.jwe_required:
        score += 1

    if score >= 5:
        return "institutional", score
    if score >= 3:
        return "strong", score
    if score >= 1:
        return "basic", score
    return "compatibility", score


@router.get("/orders")
async def list_orders(_: AdminKey, db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(PaymentOrder).order_by(PaymentOrder.created_at.desc()))
    orders = res.scalars().all()

    return [
        {
            "id": str(order.id),
            "external_id": order.external_id,
            "status": order.status,
            "provider": order.provider,
            "side": order.side,
            "network": order.network,
            "fiat_currency": order.fiat_currency,
            "fiat_amount": str(order.fiat_amount) if order.fiat_amount is not None else None,
            "crypto_currency": order.crypto_currency,
            "crypto_amount": str(order.crypto_amount) if order.crypto_amount is not None else None,
            "wallet": order.user_wallet_address,
            "treasury_wallet_address": getattr(order, "treasury_wallet_address", None),
            "payer_email": getattr(order, "payer_email", None),
            "payment_reference": getattr(order, "payment_reference", None),
            "checkout_url": getattr(order, "checkout_url", None)
            or getattr(order, "coinbase_session_url", None),
            "provider_order_id": getattr(order, "provider_order_id", None),
            "tx_hash": getattr(order, "tx_hash", None),
            "failure_reason": order.failure_reason,
            "created_at": order.created_at,
            "updated_at": order.updated_at,
        }
        for order in orders
    ]


@router.get("/summary")
async def summary(_: AdminKey, db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(PaymentOrder).order_by(PaymentOrder.created_at.desc()))
    orders = list(res.scalars().all())

    by_status = {status.value: 0 for status in OrderStatus}
    fiat_total = 0.0
    crypto_total = 0.0
    completed = 0
    failed = 0
    pending = 0

    for order in orders:
        by_status[order.status.value] += 1

        if order.status == OrderStatus.COMPLETED:
            completed += 1

            if order.fiat_amount is not None:
                fiat_total += float(order.fiat_amount)

            if order.crypto_amount is not None:
                crypto_total += float(order.crypto_amount)

        if order.status in {
            OrderStatus.CREATED,
            OrderStatus.PENDING,
            OrderStatus.PROCESSING,
        }:
            pending += 1

        if order.status == OrderStatus.FAILED:
            failed += 1

    return {
        "orders_total": len(orders),
        "total_orders": len(orders),
        "orders_completed": completed,
        "completed_orders": completed,
        "pending_orders": pending,
        "failed_orders": failed,
        "fiat_completed_total": round(fiat_total, 2),
        "total_fiat_amount": round(fiat_total, 2),
        "total_crypto_amount": round(crypto_total, 8),
        "by_status": by_status,
        "latest_orders": [
            {
                "id": str(order.id),
                "external_id": order.external_id,
                "status": order.status,
                "fiat_amount": str(order.fiat_amount) if order.fiat_amount is not None else None,
                "fiat_currency": order.fiat_currency,
                "crypto_amount": str(order.crypto_amount) if order.crypto_amount is not None else None,
                "crypto_currency": order.crypto_currency,
                "network": order.network,
                "wallet": order.user_wallet_address,
                "treasury_wallet_address": getattr(order, "treasury_wallet_address", None),
                "created_at": order.created_at,
            }
            for order in orders[:10]
        ],
    }


@router.get("/system/readiness")
async def system_readiness(_: AdminKey, db: AsyncSession = Depends(get_db)):
    clients_result = await db.execute(select(ApiClient).order_by(ApiClient.created_at.desc()))
    clients = list(clients_result.scalars().all())

    payload_counts_result = await db.execute(
        select(
            func.count(ExternalPayload.id),
            func.count().filter(ExternalPayload.verification_status == "MANUAL_REVIEW"),
            func.count().filter(ExternalPayload.verification_status == "FAILED"),
            func.count().filter(ExternalPayload.verification_status == "ALCHEMY_PENDING"),
            func.count().filter(ExternalPayload.verification_status == "RECONCILED"),
        )
    )
    (
        payload_total,
        manual_review_total,
        failed_total,
        pending_total,
        reconciled_total,
    ) = payload_counts_result.one()

    posture_counts = {
        "institutional": 0,
        "strong": 0,
        "basic": 0,
        "compatibility": 0,
    }
    weak_clients: list[dict] = []
    for client in clients:
        posture, score = _client_security_posture(client)
        posture_counts[posture] += 1
        if posture in {"compatibility", "basic"}:
            weak_clients.append(
                {
                    "client_id": client.id,
                    "name": client.name,
                    "posture": posture,
                    "score": score,
                    "allowed_ip_count": len(client.allowed_ips or []),
                }
            )

    warnings = list(settings.readiness_warnings())
    if posture_counts["compatibility"]:
        warnings.append(
            f"{posture_counts['compatibility']} counterparties are still in compatibility mode and should be hardened before high-value onboarding."
        )
    if manual_review_total:
        warnings.append(
            f"{manual_review_total} settlement payloads are currently awaiting manual review."
        )
    if failed_total:
        warnings.append(
            f"{failed_total} settlement payloads are currently in FAILED state and require operational follow-up."
        )

    return {
        "status": "ok",
        "warning_count": len(warnings),
        "warnings": warnings,
        "metrics": {
            "counterparties_total": len(clients),
            "institutional_ready": posture_counts["institutional"],
            "strong_counterparties": posture_counts["strong"],
            "basic_counterparties": posture_counts["basic"],
            "compatibility_counterparties": posture_counts["compatibility"],
            "payloads_total": payload_total or 0,
            "manual_review_payloads": manual_review_total or 0,
            "failed_payloads": failed_total or 0,
            "pending_payloads": pending_total or 0,
            "reconciled_payloads": reconciled_total or 0,
        },
        "weak_counterparties": weak_clients[:10],
    }


@router.get("/security-events")
async def security_events(_: AdminKey, db: AsyncSession = Depends(get_db), limit: int = 150):
    result = await db.execute(
        select(AuditLog).order_by(AuditLog.created_at.desc()).limit(max(50, min(limit, 500)))
    )
    logs = list(result.scalars().all())
    relevant: list[AuditLog] = []
    for log in logs:
        event_type = str(log.event_type or "")
        if event_type.startswith("SECURITY_") or event_type in {
            "CLIENT_LOGIN_FAILED",
            "CLIENT_LOGIN_RATE_LIMITED",
            "CLIENT_LOGIN_SUCCESS",
            "API_REQUEST",
        }:
            relevant.append(log)

    snapshot = runtime_security_snapshot()
    request_frequency: dict[str, int] = {}
    failed_logins: dict[str, int] = {}
    suspicious_geo: dict[str, dict] = {}

    for log in relevant:
        ip = str(getattr(log, "ip", None) or "")
        if ip:
            request_frequency[ip] = request_frequency.get(ip, 0) + 1
        if log.event_type in {"CLIENT_LOGIN_FAILED", "SECURITY_CLIENT_LOGIN_FAILED", "SECURITY_ADMIN_LOGIN_FAILED"} and ip:
            failed_logins[ip] = failed_logins.get(ip, 0) + 1
        details = log.details if isinstance(log.details, dict) else {}
        country = details.get("country")
        if ip and country and ip not in suspicious_geo:
            suspicious_geo[ip] = {"country": country}

    summary = {
        "blocked_ip_count": len(snapshot["blocked_ips"]),
        "suspicious_ip_count": len(snapshot["suspicious_ips"]),
        "security_event_count": len([log for log in relevant if str(log.event_type or "").startswith("SECURITY_")]),
        "failed_login_count": sum(failed_logins.values()),
    }

    top_requesters = [
        {
            "ip": ip,
            "requests": count,
            "failed_logins": failed_logins.get(ip, 0),
            "country": suspicious_geo.get(ip, {}).get("country"),
        }
        for ip, count in sorted(request_frequency.items(), key=lambda item: (-item[1], item[0]))[:25]
    ]

    return {
        "summary": summary,
        "blocked_ips": snapshot["blocked_ips"],
        "suspicious_ips": [
            {
                **item,
                "country": suspicious_geo.get(item["ip"], {}).get("country"),
            }
            for item in snapshot["suspicious_ips"]
        ],
        "suspicious_paths": snapshot["suspicious_paths"],
        "request_frequency": top_requesters,
        "recent_alerts": snapshot["recent_alerts"],
        "recent_events": [serialize_log(log) for log in relevant[:50]],
    }


@router.post("/transactions")
async def create_admin_transaction(
    request: Request,
    _: AdminKey,
    db: AsyncSession = Depends(get_db),
    payload: dict = Body(default_factory=dict),
):
    if payload.get("fiat_amount") is not None and payload.get("crypto_amount") is not None:
        raise HTTPException(status_code=400, detail="Use fiat_amount or crypto_amount, not both")

    if payload.get("fiat_amount") is None and payload.get("crypto_amount") is None:
        raise HTTPException(status_code=400, detail="fiat_amount or crypto_amount is required")

    try:
        network = Network(str(payload.get("network") or Network.ETHEREUM.value).lower())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Unsupported network") from exc

    external_id = str(payload.get("external_id") or f"ADMIN-MP-{uuid.uuid4().hex[:10]}")
    fiat_currency = str(payload.get("fiat_currency") or "USD").upper()
    crypto_currency = str(payload.get("crypto_currency") or "USDC").upper()
    destination_address = _ledger_address(network)

    provider = await get_provider(Provider.MOONPAY)
    provider_payload = {
        "walletAddress": destination_address,
        "cryptoCurrency": crypto_currency,
        "network": network.value,
        "fiatCurrency": fiat_currency,
        "fiatAmount": payload.get("fiat_amount"),
        "cryptoAmount": payload.get("crypto_amount"),
        "country": payload.get("country"),
        "subdivision": payload.get("subdivision"),
        "redirectURL": payload.get("redirect_url") or settings.onramp_redirect_url,
        "partnerUserRef": external_id,
        "clientIp": _request_ip(request),
    }
    provider_payload = {
        key: value for key, value in provider_payload.items() if value is not None
    }

    checkout_url, quote = await provider.create_widget_url(provider_payload)

    order = PaymentOrder(
        client_id=None,
        idempotency_key=f"admin-moonpay-{uuid.uuid4()}",
        external_id=external_id,
        provider=Provider.MOONPAY,
        side=OrderSide.BUY,
        status=OrderStatus.CREATED,
        network=network,
        fiat_currency=fiat_currency,
        fiat_amount=payload.get("fiat_amount"),
        crypto_currency=crypto_currency,
        crypto_amount=payload.get("crypto_amount"),
        user_wallet_address=destination_address,
        treasury_wallet_address=destination_address,
        payer_email=str(payload.get("customer_email")) if payload.get("customer_email") else None,
        payment_reference=external_id,
        checkout_url=checkout_url,
        quote_json={"quote": quote, "metadata": payload.get("metadata")}
        if payload.get("metadata")
        else quote,
    )

    db.add(order)
    await db.commit()
    await db.refresh(order)

    request.state.transaction_id = str(order.id)
    request.state.order_id = order.id

    await log_event(
        db,
        "ADMIN_MOONPAY_TRANSACTION_CREATED",
        {
            "order_id": str(order.id),
            "external_id": external_id,
            "destination_address": destination_address,
            "checkout_url": checkout_url,
            "quote": quote,
        },
        order.id,
    )

    return _order_response(order)


@router.post("/direct-payment")
async def create_admin_direct_payment(
    _: AdminKey,
    db: AsyncSession = Depends(get_db),
    payload: dict = Body(default_factory=dict),
):
    """Create a manual direct-crypto payment order (admin, no MoonPay). Supports ETH and TRON."""
    from app.payments import order_client_payload

    if payload.get("fiat_amount") is not None and payload.get("crypto_amount") is not None:
        raise HTTPException(status_code=400, detail="Use fiat_amount or crypto_amount, not both")

    if payload.get("fiat_amount") is None and payload.get("crypto_amount") is None:
        raise HTTPException(status_code=400, detail="fiat_amount or crypto_amount is required")

    try:
        network = Network(str(payload.get("network") or Network.ETHEREUM.value).lower())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Unsupported network") from exc

    external_id = str(payload.get("external_id") or f"ADMIN-DIRECT-{uuid.uuid4().hex[:10]}")
    fiat_currency = str(payload.get("fiat_currency") or "USD").upper()
    crypto_currency = str(payload.get("crypto_currency") or "USDT").upper()
    treasury_wallet = _ledger_address(network)

    order = PaymentOrder(
        client_id=None,
        idempotency_key=f"admin-direct-{uuid.uuid4()}",
        external_id=external_id,
        provider=Provider.MANUAL,
        side=OrderSide.BUY,
        status=OrderStatus.CREATED,
        network=network,
        fiat_currency=fiat_currency,
        fiat_amount=payload.get("fiat_amount"),
        crypto_currency=crypto_currency,
        crypto_amount=payload.get("crypto_amount"),
        user_wallet_address=treasury_wallet,
        treasury_wallet_address=treasury_wallet,
        payer_email=str(payload.get("payer_email")) if payload.get("payer_email") else None,
        payment_reference=external_id,
    )

    db.add(order)
    await db.commit()
    await db.refresh(order)

    await log_event(
        db,
        "ADMIN_DIRECT_PAYMENT_CREATED",
        {
            "order_id": str(order.id),
            "external_id": order.external_id,
            "network": order.network.value,
            "crypto_amount": str(order.crypto_amount),
            "crypto_currency": order.crypto_currency,
            "treasury_wallet_address": treasury_wallet,
        },
        order.id,
    )

    return order_client_payload(order)


@router.post("/circle-payment")
async def create_admin_circle_payment(
    request: Request,
    _: AdminKey,
    db: AsyncSession = Depends(get_db),
    payload: dict = Body(default_factory=dict),
):
    """Create a Circle USDC payment order (admin). Generates a hosted USDC payment page."""
    try:
        network = Network(str(payload.get("network") or Network.ETHEREUM.value).lower())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Unsupported network") from exc

    external_id = str(payload.get("external_id") or f"CIR-ADMIN-{uuid.uuid4().hex[:10]}")
    fiat_currency = str(payload.get("fiat_currency") or "USD").upper()
    destination_address = _ledger_address(network)

    provider = await get_provider(Provider.CIRCLE)
    provider_payload = {
        "walletAddress": destination_address,
        "network": network.value,
        "fiatCurrency": fiat_currency,
        "fiatAmount": payload.get("fiat_amount"),
        "partnerUserRef": external_id,
        "clientIp": _request_ip(request),
    }
    provider_payload = {k: v for k, v in provider_payload.items() if v is not None}

    checkout_url, quote = await provider.create_widget_url(provider_payload)

    order = PaymentOrder(
        client_id=None,
        idempotency_key=f"admin-circle-{uuid.uuid4()}",
        external_id=external_id,
        provider=Provider.CIRCLE,
        side=OrderSide.BUY,
        status=OrderStatus.CREATED,
        network=network,
        fiat_currency=fiat_currency,
        fiat_amount=payload.get("fiat_amount"),
        crypto_currency="USDC",
        user_wallet_address=destination_address,
        treasury_wallet_address=destination_address,
        payment_reference=external_id,
        checkout_url=checkout_url,
        quote_json=quote,
    )

    try:
        db.add(order)
        await db.commit()
        await db.refresh(order)
        provider_stored = Provider.CIRCLE.value
    except SQLAlchemyError:
        await db.rollback()
        fallback_quote = {
            "provider_alias": "circle",
            "circle_checkout_url": checkout_url,
            "circle_quote": quote,
            "storage_note": "Stored with fallback provider because the database enum did not accept circle.",
        }
        order = PaymentOrder(
            client_id=None,
            idempotency_key=f"admin-circle-fallback-{uuid.uuid4()}",
            external_id=external_id,
            provider=Provider.MOONPAY,
            side=OrderSide.BUY,
            status=OrderStatus.CREATED,
            network=network,
            fiat_currency=fiat_currency,
            fiat_amount=payload.get("fiat_amount"),
            crypto_currency="USDC",
            user_wallet_address=destination_address,
            treasury_wallet_address=destination_address,
            payment_reference=external_id,
            checkout_url=checkout_url,
            quote_json=fallback_quote,
        )
        db.add(order)
        await db.commit()
        await db.refresh(order)
        provider_stored = "circle:fallback"

    request.state.transaction_id = str(order.id)
    request.state.order_id = order.id

    await log_event(
        db,
        "ADMIN_CIRCLE_PAYMENT_CREATED",
        {
            "order_id": str(order.id),
            "external_id": external_id,
            "destination_address": destination_address,
            "checkout_url": checkout_url,
            "provider_stored": provider_stored,
        },
        order.id,
    )

    return _order_response(order)


@router.post("/onramper-payment")
async def create_admin_onramper_payment(
    request: Request,
    _: AdminKey,
    db: AsyncSession = Depends(get_db),
    payload: dict = Body(default_factory=dict),
):
    """
    Create an Onramper widget link (admin).
    Onramper aggregates 30+ providers: Simplex, Guardarian, Kraken Ramp, etc.
    Supports credit card, debit card, bank transfer, Apple Pay, Google Pay.
    Requires ONRAMPER_API_KEY env var — sign up at https://onramper.com
    """
    try:
        network = Network(str(payload.get("network") or Network.ETHEREUM.value).lower())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Unsupported network") from exc

    external_id = str(payload.get("external_id") or f"ONR-ADMIN-{uuid.uuid4().hex[:10]}")
    fiat_currency = str(payload.get("fiat_currency") or "USD").upper()
    destination_address = _ledger_address(network)

    provider = OnramperProvider()
    provider_payload = {
        "walletAddress": destination_address,
        "network": network.value,
        "fiatCurrency": fiat_currency,
        "fiat_currency": fiat_currency,
        "fiatAmount": payload.get("fiat_amount"),
        "fiat_amount": payload.get("fiat_amount"),
        "crypto": payload.get("crypto") or "USDC",
        "cryptoCurrency": payload.get("crypto") or "USDC",
        "partnerUserRef": external_id,
        "external_id": external_id,
        "clientIp": _request_ip(request),
    }
    provider_payload = {k: v for k, v in provider_payload.items() if v is not None}

    checkout_url, quote = await provider.create_widget_url(provider_payload)

    # Use Provider.MOONPAY in DB (same approach as Circle) — ONR- prefix identifies Onramper orders
    order = PaymentOrder(
        client_id=None,
        idempotency_key=f"admin-onramper-{uuid.uuid4()}",
        external_id=external_id,
        provider=Provider.MOONPAY,
        side=OrderSide.BUY,
        status=OrderStatus.CREATED,
        network=network,
        fiat_currency=fiat_currency,
        fiat_amount=payload.get("fiat_amount"),
        crypto_currency=str(payload.get("crypto") or "USDC"),
        user_wallet_address=destination_address,
        treasury_wallet_address=destination_address,
        payment_reference=external_id,
        checkout_url=checkout_url,
        quote_json=quote,
    )

    db.add(order)
    await db.commit()
    await db.refresh(order)

    request.state.transaction_id = str(order.id)
    request.state.order_id = order.id

    await log_event(
        db,
        "ADMIN_ONRAMPER_PAYMENT_CREATED",
        {
            "order_id": str(order.id),
            "external_id": external_id,
            "destination_address": destination_address,
            "checkout_url": checkout_url,
            "fiat_currency": fiat_currency,
        },
        order.id,
    )

    return _order_response(order)


@router.post("/orders/{order_id}/status")
async def update_order_status(
    order_id: str,
    _: AdminKey,
    db: AsyncSession = Depends(get_db),
    payload: dict = Body(default_factory=dict),
):
    status_value = str(payload.get("status") or "").upper()
    note = payload.get("note")
    tx_hash = payload.get("tx_hash")

    try:
        new_status = OrderStatus(status_value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid order status") from exc

    allowed_manual_statuses = {
        OrderStatus.COMPLETED,
        OrderStatus.FAILED,
        OrderStatus.PENDING,
        OrderStatus.PROCESSING,
    }

    if new_status not in allowed_manual_statuses:
        raise HTTPException(status_code=400, detail="Status cannot be set manually")

    result = await db.execute(
        select(PaymentOrder).where(cast(PaymentOrder.id, String) == str(order_id))
    )
    order = result.scalar_one_or_none()

    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    old_status = order.status
    order.status = new_status

    if new_status == OrderStatus.FAILED:
        order.failure_reason = str(note or "Rejected manually from dashboard")

    if tx_hash and hasattr(order, "tx_hash"):
        order.tx_hash = str(tx_hash)

    await db.commit()
    await db.refresh(order)

    await log_event(
        db,
        "ORDER_STATUS_MANUALLY_UPDATED",
        {
            "order_id": str(order.id),
            "old_status": old_status.value,
            "new_status": order.status.value,
            "note": note,
            "tx_hash": tx_hash,
        },
        order.id,
        client_id=getattr(order, "client_id", None),
    )

    return {
        "id": str(order.id),
        "status": order.status.value,
        "old_status": old_status.value,
    }


@router.delete("/orders/{order_id}")
async def delete_order(
    order_id: str,
    _: AdminKey,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(PaymentOrder).where(cast(PaymentOrder.id, String) == str(order_id))
    )
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    await log_event(
        db,
        "ORDER_DELETED",
        {
            "order_id": str(order.id),
            "external_id": order.external_id,
            "provider": order.provider.value if hasattr(order.provider, "value") else str(order.provider),
            "status": order.status.value if hasattr(order.status, "value") else str(order.status),
        },
        None,
    )
    await db.delete(order)
    await db.commit()
    return {"deleted": True, "order_id": str(order_id)}


@router.post("/clients", response_model=ApiClientCreated)
async def create_client(
    payload: ApiClientCreate,
    _: AdminKey,
    db: AsyncSession = Depends(get_db),
):
    api_key = create_api_key()
    hmac_secret = create_hmac_secret()
    oauth_client_id = create_oauth_client_id()
    oauth_client_secret = create_oauth_client_secret()

    client = ApiClient(
        name=payload.name,
        api_key_hash=hash_api_key(api_key),
        hmac_secret=hmac_secret,
        oauth_client_id_hash=hash_api_key(oauth_client_id),
        oauth_client_secret_hash=hash_oauth_secret(oauth_client_secret),
        allowed_ips=payload.allowed_ips,
        hmac_required=payload.hmac_required,
        oauth_required=payload.oauth_required,
        mtls_required=payload.mtls_required,
        mtls_cert_fingerprint=payload.mtls_cert_fingerprint,
        jws_required=payload.jws_required,
        jws_public_key_pem=payload.jws_public_key_pem,
        jwe_required=payload.jwe_required,
    )

    db.add(client)
    await db.commit()
    await db.refresh(client)

    await log_event(
        db,
        "API_CLIENT_CREATED",
        {
            "client_id": str(client.id),
            "name": client.name,
            "allowed_ips": client.allowed_ips,
            "hmac_required": client.hmac_required,
            "oauth_required": client.oauth_required,
            "mtls_required": client.mtls_required,
            "jws_required": client.jws_required,
            "jwe_required": client.jwe_required,
        },
    )

    return ApiClientCreated(
        id=str(client.id),
        name=client.name,
        allowed_ips=client.allowed_ips,
        is_active=client.is_active,
        hmac_required=client.hmac_required,
        oauth_required=client.oauth_required,
        mtls_required=client.mtls_required,
        mtls_cert_fingerprint=client.mtls_cert_fingerprint,
        jws_required=client.jws_required,
        jwe_required=client.jwe_required,
        created_at=client.created_at,
        api_key=api_key,
        hmac_secret=hmac_secret,
        oauth_client_id=oauth_client_id,
        oauth_client_secret=oauth_client_secret,
    )


@router.get("/clients", response_model=list[ApiClientRead])
async def list_clients(_: AdminKey, db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(ApiClient).order_by(ApiClient.created_at.desc()))
    clients = res.scalars().all()

    return [
        ApiClientRead(
            id=str(client.id),
            name=client.name,
            allowed_ips=client.allowed_ips,
            is_active=client.is_active,
            hmac_required=client.hmac_required,
            oauth_required=client.oauth_required,
            mtls_required=client.mtls_required,
            mtls_cert_fingerprint=client.mtls_cert_fingerprint,
            jws_required=client.jws_required,
            jwe_required=client.jwe_required,
            created_at=client.created_at,
        )
        for client in clients
    ]


@router.get("/clients/{client_id}/details")
async def client_details(
    client_id: str,
    _: AdminKey,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ApiClient).where(cast(ApiClient.id, String) == str(client_id))
    )
    client = result.scalar_one_or_none()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    accounts_result = await db.execute(
        select(ClientAccount)
        .where(cast(ClientAccount.api_client_id, String) == str(client_id))
        .order_by(ClientAccount.created_at.desc())
    )
    orders_result = await db.execute(
        select(PaymentOrder)
        .where(cast(PaymentOrder.client_id, String) == str(client_id))
        .order_by(PaymentOrder.created_at.desc())
        .limit(50)
    )
    payloads_result = await db.execute(
        select(ExternalPayload)
        .where(cast(ExternalPayload.api_client_id, String) == str(client_id))
        .order_by(ExternalPayload.created_at.desc())
        .limit(30)
    )
    logs_result = await db.execute(
        select(AuditLog)
        .where(cast(AuditLog.client_id, String) == str(client_id))
        .order_by(AuditLog.created_at.desc())
        .limit(30)
    )

    accounts = accounts_result.scalars().all()
    orders = orders_result.scalars().all()
    payloads = payloads_result.scalars().all()
    logs = logs_result.scalars().all()

    return {
        "client": {
            "id": str(client.id),
            "name": client.name,
            "allowed_ips": client.allowed_ips or [],
            "is_active": client.is_active,
            "hmac_required": client.hmac_required,
            "oauth_required": client.oauth_required,
            "mtls_required": client.mtls_required,
            "jws_required": client.jws_required,
            "jwe_required": client.jwe_required,
            "created_at": client.created_at,
        },
        "accounts": [
            {
                "id": str(account.id),
                "identifier": account.email_or_phone,
                "is_active": account.is_active,
                "created_at": account.created_at,
                "portal_url": "/client",
            }
            for account in accounts
        ],
        "orders": [_order_response(order) for order in orders],
        "payloads": [
            {
                "id": payload.id,
                "transaction_reference": payload.transaction_reference,
                "amount": str(payload.amount) if payload.amount is not None else None,
                "asset": payload.asset,
                "network": payload.network_name,
                "parsing_status": payload.parsing_status,
                "verification_status": payload.verification_status,
                "tx_hash": payload.tx_hash,
                "created_at": payload.created_at,
            }
            for payload in payloads
        ],
        "audit_logs": [
            {
                "id": log.id,
                "event_type": log.event_type,
                "method": log.method,
                "endpoint": log.endpoint,
                "status_code": log.status_code,
                "ip": log.ip,
                "transaction_id": log.transaction_id,
                "error_message": log.error_message,
                "created_at": log.created_at,
            }
            for log in logs
        ],
    }


@router.get("/orders/{order_id}/details")
async def order_details(
    order_id: str,
    _: AdminKey,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(PaymentOrder).where(cast(PaymentOrder.id, String) == str(order_id))
    )
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    logs_result = await db.execute(
        select(AuditLog)
        .where(cast(AuditLog.order_id, String) == str(order_id))
        .order_by(AuditLog.created_at.desc())
        .limit(50)
    )
    order_data = _order_response(order)
    order_data.update(
        {
            "payer_email": getattr(order, "payer_email", None),
            "payment_reference": getattr(order, "payment_reference", None),
            "tx_hash": getattr(order, "tx_hash", None),
            "failure_reason": getattr(order, "failure_reason", None),
            "treasury_wallet_address": getattr(order, "treasury_wallet_address", None),
            "customer_wallet_address": getattr(order, "customer_wallet_address", None),
            "user_wallet_address": getattr(order, "user_wallet_address", None),
            "idempotency_key": getattr(order, "idempotency_key", None),
            "updated_at": getattr(order, "updated_at", None),
        }
    )
    return {
        "order": order_data,
        "documents": document_summary(order),
        "audit_logs": [serialize_log(log) for log in logs_result.scalars().all()],
    }


@router.patch("/clients/{client_id}", response_model=ApiClientRead)
async def update_client(
    client_id: str,
    payload: ApiClientUpdate,
    _: AdminKey,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(ApiClient).where(cast(ApiClient.id, String) == str(client_id)))
    client = result.scalar_one_or_none()

    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    changes: dict[str, object] = {}
    data = payload.model_dump(exclude_unset=True)

    for field in (
        "name",
        "allowed_ips",
        "is_active",
        "hmac_required",
        "oauth_required",
        "mtls_required",
        "mtls_cert_fingerprint",
        "jws_required",
        "jws_public_key_pem",
        "jwe_required",
    ):
        if field in data:
            old_value = getattr(client, field)
            new_value = data[field]
            if old_value != new_value:
                setattr(client, field, new_value)
                changes[field] = {
                    "old": old_value,
                    "new": new_value if field not in {"jws_public_key_pem"} else "[UPDATED]",
                }

    await db.commit()
    await db.refresh(client)

    await log_event(
        db,
        "API_CLIENT_UPDATED",
        {
            "client_id": str(client.id),
            "name": client.name,
            "changes": changes,
        },
        None,
        client_id=client.id,
    )

    return ApiClientRead(
        id=str(client.id),
        name=client.name,
        allowed_ips=client.allowed_ips,
        is_active=client.is_active,
        hmac_required=client.hmac_required,
        oauth_required=client.oauth_required,
        mtls_required=client.mtls_required,
        mtls_cert_fingerprint=client.mtls_cert_fingerprint,
        jws_required=client.jws_required,
        jwe_required=client.jwe_required,
        created_at=client.created_at,
    )


@router.post("/clients/{client_id}/rotate-secrets")
async def rotate_client_secrets(
    client_id: str,
    _: AdminKey,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(ApiClient).where(cast(ApiClient.id, String) == str(client_id)))
    client = result.scalar_one_or_none()

    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    api_key = create_api_key()
    hmac_secret = create_hmac_secret()
    oauth_client_id = create_oauth_client_id()
    oauth_client_secret = create_oauth_client_secret()

    client.api_key_hash = hash_api_key(api_key)
    client.hmac_secret = hmac_secret
    client.oauth_client_id_hash = hash_api_key(oauth_client_id)
    client.oauth_client_secret_hash = hash_oauth_secret(oauth_client_secret)

    await db.commit()
    await db.refresh(client)

    await log_event(
        db,
        "API_CLIENT_SECRETS_ROTATED",
        {
            "client_id": str(client.id),
            "name": client.name,
        },
        None,
        client_id=client.id,
    )

    return {
        "client_id": str(client.id),
        "name": client.name,
        "api_key": api_key,
        "hmac_secret": hmac_secret,
        "oauth_client_id": oauth_client_id,
        "oauth_client_secret": oauth_client_secret,
        "message": "Store these credentials securely. They will not be shown again.",
    }


@router.get("/clients/security-posture")
async def client_security_posture(_: AdminKey, db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(ApiClient).order_by(ApiClient.created_at.desc()))
    clients = res.scalars().all()

    results = []
    for client in clients:
        posture, score = _client_security_posture(client)

        latest_payload_res = await db.execute(
            select(ExternalPayload)
            .where(ExternalPayload.api_client_id == client.id)
            .order_by(ExternalPayload.created_at.desc())
            .limit(1)
        )
        latest_payload = latest_payload_res.scalar_one_or_none()

        payload_count_res = await db.execute(
            select(func.count(ExternalPayload.id)).where(ExternalPayload.api_client_id == client.id)
        )
        payload_count = int(payload_count_res.scalar() or 0)

        results.append(
            {
                "client_id": str(client.id),
                "name": client.name,
                "is_active": client.is_active,
                "posture": posture,
                "security_score": score,
                "allowed_ip_count": len(client.allowed_ips or []),
                "allowed_ips": client.allowed_ips or [],
                "hmac_required": client.hmac_required,
                "oauth_required": client.oauth_required,
                "mtls_required": client.mtls_required,
                "mtls_cert_fingerprint": client.mtls_cert_fingerprint,
                "jws_required": client.jws_required,
                "jwe_required": client.jwe_required,
                "latest_payload_at": latest_payload.created_at.isoformat() if latest_payload and latest_payload.created_at else None,
                "latest_verification_status": latest_payload.verification_status if latest_payload else None,
                "payload_count": payload_count,
                "created_at": client.created_at.isoformat() if isinstance(client.created_at, datetime) else client.created_at,
            }
        )

    return {
        "total_clients": len(results),
        "institutional_ready": len([r for r in results if r["posture"] == "institutional"]),
        "strong_clients": len([r for r in results if r["posture"] == "strong"]),
        "basic_clients": len([r for r in results if r["posture"] == "basic"]),
        "compatibility_clients": len([r for r in results if r["posture"] == "compatibility"]),
        "clients": results,
    }


@router.get("/audit-logs")
async def audit_logs(
    _: AdminKey,
    db: AsyncSession = Depends(get_db),
    limit: int = 100,
):
    limit = max(1, min(limit, 500))

    res = await db.execute(
        select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit)
    )
    logs = res.scalars().all()

    return [serialize_log(log) for log in logs]


@router.get("/alchemy-events")
async def alchemy_events(
    _: AdminKey,
    db: AsyncSession = Depends(get_db),
    limit: int = 200,
):
    limit = max(1, min(limit, 500))

    res = await db.execute(
        select(AuditLog)
        .where(AuditLog.event_type.like("ALCHEMY_%"))
        .order_by(AuditLog.created_at.desc())
        .limit(limit)
    )
    logs = res.scalars().all()

    return [serialize_log(log) for log in logs]


@router.get("/documents")
async def list_documents(
    _: AdminKey,
    db: AsyncSession = Depends(get_db),
    limit: int = 100,
):
    limit = max(1, min(limit, 500))

    res = await db.execute(
        select(PaymentOrder).order_by(PaymentOrder.created_at.desc()).limit(limit)
    )
    orders = res.scalars().all()

    return [document_summary(order) for order in orders]


@router.get("/orders/{order_id}/documents/{document_type}", response_class=HTMLResponse)
async def order_document(
    order_id: str,
    document_type: str,
    _: AdminKey,
    db: AsyncSession = Depends(get_db),
):
    allowed_types = {"invoice", "pending", "receive-receipt", "send-receipt", "statement"}

    if document_type not in allowed_types:
        raise HTTPException(status_code=404, detail="Document type not found")

    result = await db.execute(
        select(PaymentOrder).where(cast(PaymentOrder.id, String) == str(order_id))
    )
    order = result.scalar_one_or_none()

    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    return HTMLResponse(render_order_document(order, document_type))


@router.get("/reports/transactions", response_class=HTMLResponse)
async def transactions_report(
    _: AdminKey,
    db: AsyncSession = Depends(get_db),
    order_id: str | None = None,
):
    stmt = select(PaymentOrder).order_by(PaymentOrder.created_at.desc())
    if order_id:
        stmt = select(PaymentOrder).where(cast(PaymentOrder.id, String) == str(order_id))
    res = await db.execute(stmt)
    orders = list(res.scalars().all())
    if order_id and not orders:
        raise HTTPException(status_code=404, detail="Order not found")

    completed = [order for order in orders if order.status == OrderStatus.COMPLETED]
    pending = [
        order
        for order in orders
        if order.status in {OrderStatus.CREATED, OrderStatus.PENDING, OrderStatus.PROCESSING}
    ]
    failed = [order for order in orders if order.status == OrderStatus.FAILED]

    fiat_total = sum(float(order.fiat_amount or 0) for order in completed)
    crypto_total = sum(float(order.crypto_amount or 0) for order in completed)

    rows = "".join(
        f"""
        <tr>
          <td>{order.external_id or order.id}</td>
          <td><span class="status {order.status.value}">{order.status.value}</span></td>
          <td>{order.provider.value}</td>
          <td>{order.network.value}</td>
          <td>{order.fiat_amount or "-"} {order.fiat_currency or ""}</td>
          <td>{order.crypto_amount or "-"} {order.crypto_currency or ""}</td>
          <td>{order.user_wallet_address or "-"}</td>
          <td>{getattr(order, "tx_hash", None) or "-"}</td>
          <td>{order.created_at}</td>
        </tr>
        """
        for order in orders
    )

    return HTMLResponse(
        f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Transactions Report</title>
  <style>
    body {{
      margin:0;
      padding:34px;
      font-family:Arial,sans-serif;
      color:#111827;
      background:#f4f7fb;
    }}
    .sheet {{
      max-width:1180px;
      margin:0 auto;
      padding:34px;
      background:white;
      border:1px solid #d8e0ea;
      box-shadow:0 18px 50px rgba(15,23,42,.08);
    }}
    .head {{
      display:flex;
      justify-content:space-between;
      gap:20px;
      border-bottom:2px solid #d8e0ea;
      padding-bottom:20px;
    }}
    .brand {{
      color:#c79a45;
      font-size:13px;
      font-weight:900;
      text-transform:uppercase;
    }}
    h1 {{
      margin:8px 0 0;
      font-size:32px;
    }}
    p {{
      color:#667085;
      line-height:1.6;
    }}
    .metrics {{
      display:grid;
      grid-template-columns:repeat(5,1fr);
      gap:12px;
      margin:22px 0;
    }}
    .metric {{
      border:1px solid #d8e0ea;
      padding:14px;
      border-radius:8px;
      background:#fbfcff;
    }}
    .metric span {{
      color:#667085;
      font-size:12px;
    }}
    .metric strong {{
      display:block;
      margin-top:7px;
      font-size:24px;
    }}
    table {{
      width:100%;
      border-collapse:collapse;
      font-size:12px;
    }}
    th,
    td {{
      border-bottom:1px solid #d8e0ea;
      padding:10px 8px;
      text-align:left;
      vertical-align:top;
      word-break:break-word;
    }}
    th {{
      background:#f8fafc;
      color:#667085;
    }}
    .status {{
      display:inline-block;
      padding:4px 8px;
      border-radius:6px;
      font-weight:800;
    }}
    .COMPLETED {{
      color:#0f8a5f;
      background:#e7f6ef;
    }}
    .PENDING,
    .PROCESSING,
    .CREATED {{
      color:#ad6a00;
      background:#fff6e8;
    }}
    .FAILED {{
      color:#b83232;
      background:#fff0f0;
    }}
    .actions {{
      max-width:1180px;
      margin:18px auto 0;
      text-align:right;
    }}
    button {{
      min-height:40px;
      padding:8px 14px;
      border:0;
      border-radius:7px;
      background:#1f5fd0;
      color:white;
      font-weight:800;
      cursor:pointer;
    }}
    @media print {{
      body {{
        background:white;
        padding:0;
      }}
      .sheet {{
        border:0;
        box-shadow:none;
      }}
      .actions {{
        display:none;
      }}
    }}
  </style>
</head>
<body>
  <section class="sheet">
    <div class="head">
      <div>
        <div class="brand">ALSHUMOOKH GLOBAL BANKING FINANCE & CREDIT</div>
        <h1>Transactions Report</h1>
        <p>Production payment gateway report for MoonPay Commerce and direct crypto receiving.</p>
      </div>
      <div>
        <strong>Generated</strong><br>{orders[0].created_at if orders else "-"}
      </div>
    </div>

    <div class="metrics">
      <div class="metric"><span>Total Orders</span><strong>{len(orders)}</strong></div>
      <div class="metric"><span>Completed</span><strong>{len(completed)}</strong></div>
      <div class="metric"><span>Pending</span><strong>{len(pending)}</strong></div>
      <div class="metric"><span>Failed</span><strong>{len(failed)}</strong></div>
      <div class="metric"><span>Fiat Completed</span><strong>{round(fiat_total, 2)} USD</strong></div>
    </div>

    <p>Total completed crypto amount: {round(crypto_total, 8)}</p>

    <table>
      <thead>
        <tr>
          <th>Reference</th>
          <th>Status</th>
          <th>Provider</th>
          <th>Network</th>
          <th>Fiat</th>
          <th>Crypto</th>
          <th>Wallet</th>
          <th>TX Hash</th>
          <th>Created</th>
        </tr>
      </thead>
      <tbody>{rows}</tbody>
    </table>
  </section>

  <div class="actions">
    <button onclick="window.print()">Print / Save PDF</button>
  </div>
</body>
</html>"""
    )


@router.get("/wallets")
async def list_wallets(_: AdminKey, db: AsyncSession = Depends(get_db)):
    res = await db.execute(
        select(TreasuryWallet).order_by(TreasuryWallet.created_at.desc())
    )
    rows = res.scalars().all()

    return [
        {
            "id": str(wallet.id),
            "network": wallet.network,
            "address": wallet.address,
            "label": wallet.label,
            "is_active": wallet.is_active,
        }
        for wallet in rows
    ]


@router.post("/reconcile")
async def run_reconcile(_: AdminKey, db: AsyncSession = Depends(get_db)):
    return await reconcile(db)


# ══════════════════════════════════════════════════════════════════════════════
#  SWIFT TERMINAL — Transaction Lookup & File Management
# ══════════════════════════════════════════════════════════════════════════════

def _swift_trn(value: str | None) -> str:
    raw = str(value or uuid.uuid4().hex).replace("-", "").upper()
    return f"TRN{raw[:16]}"


def _swift_uetr(value: str | None) -> str:
    raw = str(value or uuid.uuid4())
    return str(uuid.uuid5(uuid.NAMESPACE_URL, raw))


def _order_swift(order: PaymentOrder) -> dict:
    """Serialize a PaymentOrder as SWIFT-style record."""
    reference = order.payment_reference or order.external_id or str(order.id)
    return {
        "record_type": "PAYMENT_ORDER",
        "id": str(order.id),
        "reference": reference,
        "trn": _swift_trn(reference),
        "uetr": _swift_uetr(order.tx_hash or reference),
        "status": order.status.value,
        "provider": order.provider.value,
        "network": order.network.value,
        "fiat_amount": str(order.fiat_amount) if order.fiat_amount else None,
        "fiat_currency": order.fiat_currency,
        "crypto_amount": str(order.crypto_amount) if order.crypto_amount else None,
        "crypto_currency": order.crypto_currency,
        "sender_email": order.payer_email,
        "sender_wallet": order.user_wallet_address,
        "receiver_wallet": order.treasury_wallet_address or order.customer_wallet_address,
        "tx_hash": order.tx_hash,
        "provider_order_id": order.provider_order_id,
        "external_id": order.external_id,
        "idempotency_key": order.idempotency_key,
        "checkout_url": order.checkout_url or order.coinbase_session_url,
        "failure_reason": order.failure_reason,
        "created_at": order.created_at.isoformat() if order.created_at else None,
        "updated_at": order.updated_at.isoformat() if order.updated_at else None,
        "raw_json": order.coinbase_session_raw or order.quote_json or order.webhook_payload,
    }


def _payload_swift(ep: ExternalPayload) -> dict:
    """Serialize an ExternalPayload as SWIFT-style record."""
    reference = ep.transaction_reference or ep.request_id or str(ep.id)
    return {
        "record_type": "SETTLEMENT_PAYLOAD",
        "id": str(ep.id),
        "reference": reference,
        "trn": _swift_trn(reference),
        "uetr": _swift_uetr(ep.tx_hash or reference),
        "status": ep.verification_status,
        "parsing_status": ep.parsing_status,
        "security_level": ep.security_level,
        "amount": str(ep.amount) if ep.amount else None,
        "asset": ep.asset,
        "network": ep.network_name,
        "sender_wallet": ep.sender_wallet,
        "receiver_wallet": ep.receiver_wallet,
        "tx_hash": ep.tx_hash,
        "token_contract": ep.token_contract,
        "settlement_type": ep.settlement_type,
        "authorization_code": ep.authorization_code,
        "block_number": ep.block_number,
        "confirmations": ep.confirmations,
        "explorer_url": ep.explorer_url,
        "review_priority": ep.review_priority,
        "review_decision": ep.review_decision,
        "review_note": ep.review_note,
        "error_message": ep.error_message,
        "created_at": ep.created_at.isoformat() if ep.created_at else None,
        "parsed_payload": ep.parsed_payload,
    }


@router.get("/swift/lookup")
async def swift_lookup(
    q: str,
    _: AdminKey,
    db: AsyncSession = Depends(get_db),
):
    """
    Search for transactions by any reference:
    UUID, external_id, payment_reference, tx_hash, payer_email,
    transaction_reference, request_id, idempotency_key.
    """
    q = q.strip()
    if not q or len(q) < 3:
        raise HTTPException(status_code=400, detail="Query too short — minimum 3 characters.")

    results = []

    # ── Search PaymentOrder ──────────────────────────────────────────────
    order_q = await db.execute(
        select(PaymentOrder).where(
            or_(
                cast(PaymentOrder.id, String).ilike(f"%{q}%"),
                cast(PaymentOrder.external_id, String).ilike(f"%{q}%"),
                cast(PaymentOrder.payment_reference, String).ilike(f"%{q}%"),
                cast(PaymentOrder.tx_hash, String).ilike(f"%{q}%"),
                cast(PaymentOrder.payer_email, String).ilike(f"%{q}%"),
                cast(PaymentOrder.provider_order_id, String).ilike(f"%{q}%"),
                cast(PaymentOrder.idempotency_key, String).ilike(f"%{q}%"),
            )
        ).order_by(PaymentOrder.created_at.desc()).limit(10)
    )
    for order in order_q.scalars().all():
        rec = _order_swift(order)
        # Attach file list
        files_q = await db.execute(
            select(TransactionFile).where(
                or_(
                    TransactionFile.order_id == str(order.id),
                    TransactionFile.transaction_ref == rec["reference"],
                )
            ).order_by(TransactionFile.created_at.desc())
        )
        all_order_files = files_q.scalars().all()
        rec["files"] = [
            {
                "id": f.id,
                "filename": f.filename,
                "content_type": f.content_type,
                "file_size": f.file_size,
                "description": f.description,
                "created_at": f.created_at.isoformat() if f.created_at else None,
            }
            for f in all_order_files if f.content_type != "text/x-internal-note"
        ]
        rec["notes"] = [
            {
                "id": f.id,
                "note": f.file_data.decode("utf-8", errors="replace") if f.file_data else (f.description or ""),
                "created_at": f.created_at.isoformat() if f.created_at else None,
            }
            for f in all_order_files if f.content_type == "text/x-internal-note"
        ]
        results.append(rec)

    # ── Search ExternalPayload ───────────────────────────────────────────
    payload_q = await db.execute(
        select(ExternalPayload).where(
            or_(
                cast(ExternalPayload.id, String).ilike(f"%{q}%"),
                cast(ExternalPayload.transaction_reference, String).ilike(f"%{q}%"),
                cast(ExternalPayload.tx_hash, String).ilike(f"%{q}%"),
                cast(ExternalPayload.request_id, String).ilike(f"%{q}%"),
                cast(ExternalPayload.idempotency_key, String).ilike(f"%{q}%"),
                cast(ExternalPayload.sender_wallet, String).ilike(f"%{q}%"),
            )
        ).order_by(ExternalPayload.created_at.desc()).limit(10)
    )
    for ep in payload_q.scalars().all():
        rec = _payload_swift(ep)
        files_q = await db.execute(
            select(TransactionFile).where(
                or_(
                    TransactionFile.payload_id == str(ep.id),
                    TransactionFile.transaction_ref == rec["reference"],
                )
            ).order_by(TransactionFile.created_at.desc())
        )
        all_ep_files = files_q.scalars().all()
        rec["files"] = [
            {
                "id": f.id,
                "filename": f.filename,
                "content_type": f.content_type,
                "file_size": f.file_size,
                "description": f.description,
                "created_at": f.created_at.isoformat() if f.created_at else None,
            }
            for f in all_ep_files if f.content_type != "text/x-internal-note"
        ]
        rec["notes"] = [
            {
                "id": f.id,
                "note": f.file_data.decode("utf-8", errors="replace") if f.file_data else (f.description or ""),
                "created_at": f.created_at.isoformat() if f.created_at else None,
            }
            for f in all_ep_files if f.content_type == "text/x-internal-note"
        ]
        results.append(rec)

    return {"query": q, "count": len(results), "results": results}


@router.post("/swift/{record_id}/files")
async def swift_upload_file(
    record_id: str,
    _: AdminKey,
    db: AsyncSession = Depends(get_db),
    file: UploadFile = File(...),
    description: str = Form(default=""),
    transaction_ref: str = Form(default=""),
):
    """Upload a file and attach it to a transaction record (order or payload)."""
    MAX_SIZE = 20 * 1024 * 1024  # 20 MB
    data = await file.read()
    if len(data) > MAX_SIZE:
        raise HTTPException(status_code=413, detail="File too large. Maximum 20 MB.")

    # Determine record type
    order_id = None
    payload_id = None
    ref = transaction_ref.strip() or record_id

    order_check = await db.get(PaymentOrder, record_id)
    if order_check:
        order_id = record_id
    else:
        payload_check = await db.get(ExternalPayload, record_id)
        if payload_check:
            payload_id = record_id

    tf = TransactionFile(
        id=str(uuid.uuid4()),
        order_id=order_id,
        payload_id=payload_id,
        transaction_ref=ref,
        filename=file.filename or "untitled",
        content_type=file.content_type or "application/octet-stream",
        file_data=data,
        file_size=len(data),
        description=description[:500] if description else None,
        uploaded_by="admin",
    )
    db.add(tf)
    await db.commit()
    await db.refresh(tf)

    return {
        "id": tf.id,
        "filename": tf.filename,
        "file_size": tf.file_size,
        "content_type": tf.content_type,
        "description": tf.description,
        "created_at": tf.created_at.isoformat() if tf.created_at else None,
    }


@router.get("/swift/files/{file_id}")
async def swift_download_file(
    file_id: str,
    _: AdminKey,
    db: AsyncSession = Depends(get_db),
):
    """Download a file by ID."""
    tf = await db.get(TransactionFile, file_id)
    if not tf:
        raise HTTPException(status_code=404, detail="File not found.")

    return Response(
        content=tf.file_data,
        media_type=tf.content_type,
        headers={
            "Content-Disposition": f'attachment; filename="{tf.filename}"',
            "Content-Length": str(tf.file_size),
        },
    )


@router.delete("/swift/files/{file_id}")
async def swift_delete_file(
    file_id: str,
    _: AdminKey,
    db: AsyncSession = Depends(get_db),
):
    """Delete an attached file."""
    tf = await db.get(TransactionFile, file_id)
    if not tf:
        raise HTTPException(status_code=404, detail="File not found.")
    await db.delete(tf)
    await db.commit()
    return {"deleted": file_id}


@router.patch("/swift/{record_id}/status")
async def swift_update_status(
    record_id: str,
    _: AdminKey,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Update the status of a PaymentOrder or ExternalPayload."""
    body = await request.json()
    new_status = body.get("status", "").strip().upper()
    record_type = body.get("record_type", "").strip()

    if not new_status:
        raise HTTPException(status_code=400, detail="status is required")

    if record_type == "PAYMENT_ORDER":
        valid_statuses = {s.value for s in OrderStatus}
        if new_status not in valid_statuses:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid status. Valid values: {sorted(valid_statuses)}",
            )
        rec = await db.get(PaymentOrder, record_id)
        if not rec:
            raise HTTPException(status_code=404, detail="Payment order not found")
        rec.status = OrderStatus(new_status)
        await db.commit()
        return {"ok": True, "record_id": record_id, "record_type": record_type, "status": new_status}

    elif record_type == "SETTLEMENT_PAYLOAD":
        rec = await db.get(ExternalPayload, record_id)
        if not rec:
            raise HTTPException(status_code=404, detail="Settlement payload not found")
        rec.verification_status = new_status
        await db.commit()
        return {"ok": True, "record_id": record_id, "record_type": record_type, "status": new_status}

    else:
        raise HTTPException(status_code=400, detail="Invalid record_type. Use PAYMENT_ORDER or SETTLEMENT_PAYLOAD")


@router.post("/swift/{record_id}/notes")
async def swift_add_note(
    record_id: str,
    _: AdminKey,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Add an internal admin note to a transaction (stored as a special file entry)."""
    body = await request.json()
    note_text = body.get("note", "").strip()
    if not note_text:
        raise HTTPException(status_code=400, detail="note is required")
    if len(note_text) > 2000:
        raise HTTPException(status_code=400, detail="Note too long — maximum 2000 characters")

    order_id = None
    payload_id = None
    order_check = await db.get(PaymentOrder, record_id)
    if order_check:
        order_id = record_id
    else:
        payload_check = await db.get(ExternalPayload, record_id)
        if payload_check:
            payload_id = record_id

    note_bytes = note_text.encode("utf-8")
    note_entry = TransactionFile(
        id=str(uuid.uuid4()),
        order_id=order_id,
        payload_id=payload_id,
        transaction_ref=record_id,
        filename=f"_note_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.txt",
        content_type="text/x-internal-note",
        file_data=note_bytes,
        file_size=len(note_bytes),
        description=note_text[:200],
        uploaded_by="admin",
    )
    db.add(note_entry)
    await db.commit()
    await db.refresh(note_entry)

    return {
        "id": note_entry.id,
        "note": note_text,
        "created_at": note_entry.created_at.isoformat() if note_entry.created_at else None,
    }


@router.delete("/swift/notes/{note_id}")
async def swift_delete_note(
    note_id: str,
    _: AdminKey,
    db: AsyncSession = Depends(get_db),
):
    """Delete an internal note by ID."""
    note = await db.get(TransactionFile, note_id)
    if not note or note.content_type != "text/x-internal-note":
        raise HTTPException(status_code=404, detail="Note not found")
    await db.delete(note)
    await db.commit()
    return {"deleted": note_id}


@router.post("/swift/import")
async def swift_import_file(
    _: AdminKey,
    db: AsyncSession = Depends(get_db),
    file: UploadFile = File(...),
):
    """
    Import a JSON or PDF file into the SWIFT system with automatic verification.
    - JSON: parsed and each transaction reference is looked up in the database.
    - PDF:  stored as a standalone file and confirmed.
    """
    import json as _json

    MAX_SIZE = 20 * 1024 * 1024
    data = await file.read()
    if len(data) > MAX_SIZE:
        raise HTTPException(status_code=413, detail="File too large. Maximum 20 MB.")

    fn  = (file.filename or "").lower()
    ct  = (file.content_type or "").lower()
    is_json = fn.endswith(".json") or "json" in ct
    is_pdf  = fn.endswith(".pdf")  or "pdf"  in ct

    if not (is_json or is_pdf):
        raise HTTPException(
            status_code=400,
            detail="Unsupported file type. Only JSON and PDF are accepted.",
        )

    result: dict = {
        "filename":         file.filename,
        "file_size":        len(data),
        "content_type":     file.content_type,
        "verified":         False,
        "records_found":    [],
        "records_not_found": [],
        "summary":          "",
        "raw_preview":      None,
        "file_id":          None,
    }

    # ── JSON verification ──────────────────────────────────────────────
    if is_json:
        try:
            payload = _json.loads(data.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as e:
            result["summary"] = f"Invalid JSON file: {e}"
            return result

        # Preview (first 500 chars of pretty-printed)
        preview = _json.dumps(payload, ensure_ascii=False, indent=2)
        result["raw_preview"] = preview[:600] + ("…" if len(preview) > 600 else "")

        # Collect candidate references
        refs: list[str] = []

        def _harvest(obj: object, depth: int = 0) -> None:
            """Recursively extract string values that look like IDs/references."""
            if depth > 5:
                return
            if isinstance(obj, dict):
                for k, v in obj.items():
                    if isinstance(v, str) and len(v) >= 3:
                        if any(kw in k.lower() for kw in (
                            "id", "ref", "reference", "hash", "tx", "key",
                            "transaction", "order", "payload",
                        )):
                            refs.append(v)
                    _harvest(v, depth + 1)
            elif isinstance(obj, list):
                for item in obj[:100]:
                    _harvest(item, depth + 1)

        _harvest(payload)
        # Deduplicate while preserving order
        seen: set[str] = set()
        unique_refs: list[str] = []
        for r in refs:
            if r not in seen and len(r) >= 6:
                seen.add(r)
                unique_refs.append(r)
        unique_refs = unique_refs[:60]  # cap at 60 lookups

        # Look up each reference
        for ref in unique_refs:
            found = False

            order_r = await db.execute(
                select(PaymentOrder).where(
                    or_(
                        cast(PaymentOrder.id, String).ilike(f"%{ref}%"),
                        cast(PaymentOrder.payment_reference, String).ilike(f"%{ref}%"),
                        cast(PaymentOrder.external_id, String).ilike(f"%{ref}%"),
                        cast(PaymentOrder.tx_hash, String).ilike(f"%{ref}%"),
                        cast(PaymentOrder.provider_order_id, String).ilike(f"%{ref}%"),
                    )
                ).limit(1)
            )
            if order_r.scalar():
                result["records_found"].append({"ref": ref, "type": "PAYMENT_ORDER"})
                found = True

            if not found:
                ep_r = await db.execute(
                    select(ExternalPayload).where(
                        or_(
                            cast(ExternalPayload.id, String).ilike(f"%{ref}%"),
                            cast(ExternalPayload.transaction_reference, String).ilike(f"%{ref}%"),
                            cast(ExternalPayload.tx_hash, String).ilike(f"%{ref}%"),
                            cast(ExternalPayload.request_id, String).ilike(f"%{ref}%"),
                        )
                    ).limit(1)
                )
                if ep_r.scalar():
                    result["records_found"].append({"ref": ref, "type": "SETTLEMENT_PAYLOAD"})
                    found = True

            if not found:
                result["records_not_found"].append(ref)

        found_n    = len(result["records_found"])
        nf_n       = len(result["records_not_found"])
        result["verified"] = found_n > 0
        result["summary"] = (
            f"JSON verified — {found_n} reference(s) matched in database, "
            f"{nf_n} not found. "
            f"Total scanned: {len(unique_refs)} unique identifiers."
        )

    # ── PDF storage ────────────────────────────────────────────────────
    elif is_pdf:
        stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        tf = TransactionFile(
            id=str(uuid.uuid4()),
            order_id=None,
            payload_id=None,
            transaction_ref=f"IMPORT_{stamp}",
            filename=file.filename or f"import_{stamp}.pdf",
            content_type=file.content_type or "application/pdf",
            file_data=data,
            file_size=len(data),
            description="Imported via SWIFT Terminal bulk upload",
            uploaded_by="admin",
        )
        db.add(tf)
        await db.commit()
        await db.refresh(tf)

        result["verified"] = True
        result["file_id"]  = tf.id
        result["summary"]  = (
            f"PDF received and stored successfully. "
            f"File ID: {tf.id} | Size: {len(data):,} bytes"
        )

    return result


# ──────────────────────────────────────────────────────────────────────────────
# SWIFT TRANSMITTER — Send SWIFT envelope to an external API endpoint
# ──────────────────────────────────────────────────────────────────────────────
class TransmitRequest(BaseModel):
    destination_url:  str = ""
    from_endpoint:    str = ""
    from_account:     str = ""
    to_account:       str = ""
    auth_type:        str = "none"   # none | bearer | apikey | basic | custom
    auth_value:       str = ""
    auth_header_name: str = "X-API-Key"
    message_type:     str = "MT103"
    transfer_type:    str = "CREDIT_TRANSFER"
    record_id:        str | None = None
    timeout:          int = 30


@router.post("/swift/transmit", tags=["admin-swift"])
async def swift_transmit(
    request: Request,
    _: AdminKey,
    db: AsyncSession = Depends(get_db),
):
    """
    Build a SWIFT envelope and POST it to an external endpoint.
    Supports: None / Bearer / API-Key / Basic / Custom auth.
    """
    # ── Parse raw JSON body (bypasses Pydantic 422 issues) ────────
    try:
        raw = await request.json()
    except Exception:
        raw = {}

    destination_url  = str(raw.get("destination_url",  "") or "").strip()
    from_endpoint    = str(raw.get("from_endpoint",    "") or "").strip()
    from_account     = str(raw.get("from_account",     "") or "").strip()
    to_account       = str(raw.get("to_account",       "") or "").strip()
    auth_type        = str(raw.get("auth_type",        "none") or "none").strip()
    auth_value       = str(raw.get("auth_value",       "") or "").strip()
    auth_header_name = str(raw.get("auth_header_name", "X-API-Key") or "X-API-Key").strip()
    message_type     = str(raw.get("message_type",     "MT103") or "MT103").strip()
    transfer_type    = str(raw.get("transfer_type",    "CREDIT_TRANSFER") or "CREDIT_TRANSFER").strip()
    record_id        = raw.get("record_id")
    timeout_val      = int(raw.get("timeout", 30) or 30)

    # ── Minimal validation — only destination URL is required ──────
    if not destination_url:
        raise HTTPException(status_code=400, detail="destination_url is required")

    now_iso  = datetime.now(timezone.utc).isoformat()
    stamp    = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    msg_ref  = f"ALSH-{stamp}-{uuid.uuid4().hex[:6].upper()}"
    tx_id    = str(uuid.uuid4())
    trn_code = _swift_trn(record_id or msg_ref)
    uetr_code = _swift_uetr(record_id or tx_id)

    # ── Build envelope ────────────────────────────────────────────
    envelope = {
        "swift_envelope": {
            "version": "1.0",
            "transmission_id": tx_id,
            "message_type": message_type,
            "transfer_type": transfer_type,
            "transmission_timestamp": now_iso,
            "sender": {
                "system": "ALSHUMOOKH GLOBAL BANKING FINANCE & CREDIT",
                "endpoint": from_endpoint,
                "account_or_wallet": from_account,
            },
            "recipient": {
                "endpoint": destination_url,
                "account_or_wallet": to_account,
            },
            "message_header": {
                "msg_ref": msg_ref,
                "trn": trn_code,
                "uetr": uetr_code,
                "msg_type": message_type,
                "transfer_type": transfer_type,
                "priority": "NORMAL",
                "service_id": "01",
            },
        }
    }
    if record_id:
        envelope["record_id"] = record_id
    envelope["trn"] = trn_code
    envelope["uetr"] = uetr_code

    # ── Build headers ─────────────────────────────────────────────
    req_headers: dict = {"Content-Type": "application/json"}
    at = auth_type.lower()
    if at == "bearer":
        req_headers["Authorization"] = f"Bearer {auth_value}"
    elif at == "apikey":
        hdr_name = auth_header_name or "X-API-Key"
        req_headers[hdr_name] = auth_value
    elif at == "basic":
        cred = auth_value
        if ":" in cred:
            cred = base64.b64encode(cred.encode()).decode()
        req_headers["Authorization"] = f"Basic {cred}"
    elif at == "custom":
        hdr_name = auth_header_name or "X-Custom-Auth"
        req_headers[hdr_name] = auth_value

    # ── Send ──────────────────────────────────────────────────────
    t0 = time.time()
    try:
        async with httpx.AsyncClient(timeout=timeout_val) as client:
            resp = await client.post(
                destination_url,
                json=envelope,
                headers=req_headers,
            )
        duration_ms = int((time.time() - t0) * 1000)
        status_code = resp.status_code
        try:
            resp_body = resp.text[:4096]
        except Exception:
            resp_body = ""

        # ── Log transmission as a TransactionFile note ────────────
        log_note = (
            f"SWIFT TRANSMISSION [{message_type}] | ID: {tx_id}\n"
            f"TO: {destination_url}\n"
            f"FROM_ACCT: {from_account} => TO_ACCT: {to_account}\n"
            f"STATUS: {status_code} | DURATION: {duration_ms}ms\n"
            f"TIMESTAMP: {now_iso}"
        )
        tf_log = TransactionFile(
            id=str(uuid.uuid4()),
            order_id=record_id if record_id else None,
            payload_id=None,
            transaction_ref=msg_ref,
            filename=f"transmit_{tx_id[:8]}.log",
            content_type="text/x-internal-note",
            file_data=log_note.encode("utf-8"),
            file_size=len(log_note.encode()),
            description=f"SWIFT Transmit log: {message_type} to {destination_url}",
            uploaded_by="admin",
        )
        db.add(tf_log)
        await db.commit()

        return {
            "transmission_id": tx_id,
            "msg_ref":         msg_ref,
            "trn":             trn_code,
            "uetr":            uetr_code,
            "status_code":     status_code,
            "duration_ms":     duration_ms,
            "response_body":   resp_body,
            "response_headers": dict(resp.headers),
        }

    except httpx.TimeoutException:
        duration_ms = int((time.time() - t0) * 1000)
        raise HTTPException(
            status_code=504,
            detail=f"Transmission timed out after {timeout_val}s ({duration_ms}ms elapsed). "
                   f"Destination: {destination_url}"
        )
    except httpx.RequestError as exc:
        duration_ms = int((time.time() - t0) * 1000)
        raise HTTPException(
            status_code=502,
            detail=f"Connection error: {exc} ({duration_ms}ms). "
                   f"Destination: {destination_url}"
        )


# ──────────────────────────────────────────────────────────────────────────────
# M1 FUND ADMIN — View and manage incoming M1 Fund payloads
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/m1-funds", tags=["admin-m1-funds"])
async def list_m1_funds(
    _: AdminKey,
    db: AsyncSession = Depends(get_db),
    limit: int = 50,
    offset: int = 0,
):
    """List all received M1 Fund payloads ordered by newest first."""
    result = await db.execute(
        select(ExternalPayload)
        .where(ExternalPayload.settlement_type == "M1_FUND_INBOUND")
        .order_by(ExternalPayload.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    funds = result.scalars().all()
    return {
        "total": len(funds),
        "funds": [
            {
                "fund_id":            f.id,
                "m1_reference":       f.transaction_reference,
                "sender_id":          f.sender_wallet,
                "amount_eur":         str(f.amount) if f.amount else "N/A",
                "verification_status": f.verification_status,
                "review_decision":    f.review_decision,
                "review_priority":    f.review_priority,
                "client_ip":          f.client_ip,
                "received_at":        f.created_at.isoformat() if f.created_at else None,
            }
            for f in funds
        ],
    }


@router.get("/m1-funds/{fund_id}", tags=["admin-m1-funds"])
async def get_m1_fund(
    fund_id: str,
    _: AdminKey,
    db: AsyncSession = Depends(get_db),
):
    """Get full details of a specific M1 Fund payload including parsed data and attached files."""
    result = await db.execute(
        select(ExternalPayload).where(
            ExternalPayload.id == fund_id,
            ExternalPayload.settlement_type == "M1_FUND_INBOUND",
        )
    )
    fund = result.scalar_one_or_none()
    if not fund:
        raise HTTPException(status_code=404, detail="M1 Fund not found")

    file_result = await db.execute(
        select(TransactionFile).where(TransactionFile.payload_id == fund_id)
    )
    files = file_result.scalars().all()

    return {
        "fund_id":            fund.id,
        "m1_reference":       fund.transaction_reference,
        "sender_id":          fund.sender_wallet,
        "amount_eur":         str(fund.amount) if fund.amount else "N/A",
        "asset":              fund.asset,
        "token_contract":     fund.token_contract,
        "tx_hash":            fund.tx_hash,
        "payload_hash":       fund.payload_hash,
        "verification_status": fund.verification_status,
        "review_priority":    fund.review_priority,
        "review_decision":    fund.review_decision,
        "review_note":        fund.review_note,
        "reviewed_by":        fund.reviewed_by,
        "reviewed_at":        fund.reviewed_at.isoformat() if fund.reviewed_at else None,
        "client_ip":          fund.client_ip,
        "received_at":        fund.created_at.isoformat() if fund.created_at else None,
        "parsed_payload":     fund.parsed_payload,
        "files": [
            {
                "file_id":    f.id,
                "filename":   f.filename,
                "size_bytes": f.file_size,
                "description": f.description,
                "uploaded_at": f.created_at.isoformat() if f.created_at else None,
            }
            for f in files
        ],
    }


@router.post("/m1-funds/{fund_id}/approve", tags=["admin-m1-funds"])
async def approve_m1_fund(
    fund_id: str,
    request: Request,
    _: AdminKey,
    db: AsyncSession = Depends(get_db),
):
    """Approve an M1 Fund for tokenization processing."""
    try:
        raw = await request.json()
    except Exception:
        raw = {}
    note = str(raw.get("note", "") or "").strip()

    result = await db.execute(
        select(ExternalPayload).where(
            ExternalPayload.id == fund_id,
            ExternalPayload.settlement_type == "M1_FUND_INBOUND",
        )
    )
    fund = result.scalar_one_or_none()
    if not fund:
        raise HTTPException(status_code=404, detail="M1 Fund not found")

    fund.review_decision    = "APPROVED"
    fund.verification_status = "APPROVED"
    fund.review_note        = note or "Approved by admin — cleared for tokenization"
    fund.reviewed_by        = "admin"
    fund.reviewed_at        = datetime.now(timezone.utc)
    await db.commit()

    return {
        "fund_id":      fund_id,
        "m1_reference": fund.transaction_reference,
        "status":       "APPROVED",
        "message":      "M1 Fund approved and cleared for tokenization.",
        "reviewed_at":  fund.reviewed_at.isoformat(),
    }


@router.post("/m1-funds/{fund_id}/reject", tags=["admin-m1-funds"])
async def reject_m1_fund(
    fund_id: str,
    request: Request,
    _: AdminKey,
    db: AsyncSession = Depends(get_db),
):
    """Reject an M1 Fund payload."""
    try:
        raw = await request.json()
    except Exception:
        raw = {}
    reason = str(raw.get("reason", "") or "").strip()

    result = await db.execute(
        select(ExternalPayload).where(
            ExternalPayload.id == fund_id,
            ExternalPayload.settlement_type == "M1_FUND_INBOUND",
        )
    )
    fund = result.scalar_one_or_none()
    if not fund:
        raise HTTPException(status_code=404, detail="M1 Fund not found")

    fund.review_decision    = "REJECTED"
    fund.verification_status = "REJECTED"
    fund.review_note        = reason or "Rejected by admin"
    fund.reviewed_by        = "admin"
    fund.reviewed_at        = datetime.now(timezone.utc)
    await db.commit()

    return {
        "fund_id":      fund_id,
        "m1_reference": fund.transaction_reference,
        "status":       "REJECTED",
        "reason":       fund.review_note,
        "reviewed_at":  fund.reviewed_at.isoformat(),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# OUTBOUND TRANSFERS — Admin Management
# ═══════════════════════════════════════════════════════════════════════════════

def _transfer_dict(ot: OutboundTransfer) -> dict:
    return {
        "id": ot.id,
        "status": ot.status,
        "network": ot.network,
        "asset": ot.asset,
        "amount": str(ot.amount),
        "to_address": ot.to_address,
        "from_address": ot.from_address,
        "tx_hash": ot.tx_hash,
        "explorer_url": ot.explorer_url,
        "order_id": ot.order_id,
        "payload_id": ot.payload_id,
        "tokenization_job_id": ot.tokenization_job_id,
        "initiated_by": ot.initiated_by,
        "approved_by": ot.approved_by,
        "approved_at": ot.approved_at.isoformat() if ot.approved_at else None,
        "cancelled_by": ot.cancelled_by,
        "cancel_reason": ot.cancel_reason,
        "error_message": ot.error_message,
        "retry_count": ot.retry_count,
        "callback_url": ot.callback_url,
        "webhook_status_code": ot.webhook_status_code,
        "notes": ot.notes,
        "created_at": ot.created_at.isoformat() if ot.created_at else None,
        "broadcasted_at": ot.broadcasted_at.isoformat() if ot.broadcasted_at else None,
        "completed_at": ot.completed_at.isoformat() if ot.completed_at else None,
    }


@router.get("/outbound-transfers", tags=["admin-transfers"])
async def list_outbound_transfers(
    _: AdminKey,
    db: AsyncSession = Depends(get_db),
    status: str | None = None,
    network: str | None = None,
    limit: int = 100,
):
    """List all outbound USDT transfers with optional status/network filter."""
    q = select(OutboundTransfer).order_by(OutboundTransfer.created_at.desc()).limit(limit)
    if status:
        q = q.where(OutboundTransfer.status == status.upper())
    if network:
        q = q.where(OutboundTransfer.network == network.lower())
    result = await db.execute(q)
    transfers = result.scalars().all()
    return [_transfer_dict(t) for t in transfers]


@router.get("/outbound-transfers/{transfer_id}", tags=["admin-transfers"])
async def get_outbound_transfer(
    transfer_id: str,
    _: AdminKey,
    db: AsyncSession = Depends(get_db),
):
    """Get a single outbound transfer by ID."""
    result = await db.execute(
        select(OutboundTransfer).where(OutboundTransfer.id == transfer_id)
    )
    ot = result.scalar_one_or_none()
    if not ot:
        raise HTTPException(status_code=404, detail="Transfer not found")
    return _transfer_dict(ot)


@router.post("/outbound-transfers", tags=["admin-transfers"])
async def create_manual_outbound_transfer(
    request: Request,
    _: AdminKey,
    db: AsyncSession = Depends(get_db),
):
    """
    Manually create a new outbound USDT transfer (starts in PENDING status).
    Requires: to_address, amount, network
    Optional: payload_id, order_id, callback_url, notes
    """
    body = await request.json()
    to_address = body.get("to_address", "").strip()
    amount_raw = body.get("amount")
    network = body.get("network", "ethereum").strip().lower()

    if not to_address:
        raise HTTPException(status_code=422, detail="to_address is required")
    if not amount_raw:
        raise HTTPException(status_code=422, detail="amount is required")

    from decimal import Decimal as D
    try:
        amount = D(str(amount_raw))
    except Exception:
        raise HTTPException(status_code=422, detail="Invalid amount")

    if amount <= 0:
        raise HTTPException(status_code=422, detail="amount must be > 0")

    ot = await create_outbound_transfer(
        db,
        to_address=to_address,
        amount=amount,
        network=network,
        asset=body.get("asset", "USDT"),
        order_id=body.get("order_id"),
        payload_id=body.get("payload_id"),
        callback_url=body.get("callback_url"),
        initiated_by="admin",
        notes=body.get("notes"),
    )

    await log_event(
        db,
        "OUTBOUND_TRANSFER_CREATED",
        {"transfer_id": ot.id, "amount": str(amount), "network": network, "to": to_address},
        None,
    )
    return _transfer_dict(ot)


@router.post("/outbound-transfers/{transfer_id}/approve", tags=["admin-transfers"])
async def approve_transfer(
    transfer_id: str,
    _: AdminKey,
    db: AsyncSession = Depends(get_db),
):
    """Approve a PENDING outbound transfer (sets status to APPROVED)."""
    try:
        ot = await approve_outbound_transfer(db, transfer_id, approved_by="admin")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    await log_event(
        db,
        "OUTBOUND_TRANSFER_APPROVED",
        {"transfer_id": transfer_id},
        ot.order_id,
    )
    return _transfer_dict(ot)


@router.post("/outbound-transfers/{transfer_id}/broadcast", tags=["admin-transfers"])
async def broadcast_transfer(
    transfer_id: str,
    _: AdminKey,
    db: AsyncSession = Depends(get_db),
):
    """
    Broadcast an APPROVED outbound transfer to the blockchain.
    Sends USDT on the configured network and records the tx_hash.
    """
    try:
        ot = await broadcast_outbound_transfer(db, transfer_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        # Already logged inside broadcast_outbound_transfer
        raise HTTPException(status_code=500, detail=f"Broadcast failed: {exc}")

    # Send webhook + email notification
    import asyncio
    asyncio.create_task(
        notify_transfer_completed(
            callback_url=ot.callback_url,
            transfer_id=ot.id,
            tx_hash=ot.tx_hash,
            amount=str(ot.amount),
            network=ot.network,
            to_address=ot.to_address,
            explorer_url=ot.explorer_url,
        )
    )
    return _transfer_dict(ot)


@router.post("/outbound-transfers/{transfer_id}/cancel", tags=["admin-transfers"])
async def cancel_transfer(
    transfer_id: str,
    request: Request,
    _: AdminKey,
    db: AsyncSession = Depends(get_db),
):
    """Cancel a pending/awaiting outbound transfer."""
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass

    reason = str(body.get("reason", "") or "").strip() or "Cancelled by admin"

    try:
        ot = await cancel_outbound_transfer(db, transfer_id, cancelled_by="admin", reason=reason)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    await log_event(
        db,
        "OUTBOUND_TRANSFER_CANCELLED",
        {"transfer_id": transfer_id, "reason": reason},
        ot.order_id,
    )
    return _transfer_dict(ot)


@router.post("/outbound-transfers/{transfer_id}/retry", tags=["admin-transfers"])
async def retry_transfer(
    transfer_id: str,
    _: AdminKey,
    db: AsyncSession = Depends(get_db),
):
    """Retry a FAILED outbound transfer by re-approving and broadcasting."""
    result = await db.execute(
        select(OutboundTransfer).where(OutboundTransfer.id == transfer_id)
    )
    ot = result.scalar_one_or_none()
    if not ot:
        raise HTTPException(status_code=404, detail="Transfer not found")
    if ot.status != OutboundTransferStatus.FAILED.value:
        raise HTTPException(status_code=400, detail=f"Transfer status is {ot.status}, can only retry FAILED")

    # Re-approve then broadcast
    ot.status = OutboundTransferStatus.APPROVED.value
    ot.approved_by = "admin (retry)"
    ot.approved_at = datetime.now(timezone.utc)
    await db.commit()

    try:
        ot = await broadcast_outbound_transfer(db, transfer_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Retry broadcast failed: {exc}")

    return _transfer_dict(ot)


@router.delete("/outbound-transfers/{transfer_id}", tags=["admin-transfers"])
async def delete_transfer(
    transfer_id: str,
    _: AdminKey,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(OutboundTransfer).where(OutboundTransfer.id == transfer_id)
    )
    ot = result.scalar_one_or_none()
    if not ot:
        raise HTTPException(status_code=404, detail="Transfer not found")
    if ot.status == OutboundTransferStatus.BROADCASTING.value:
        raise HTTPException(status_code=400, detail="Cannot delete a transfer while it is broadcasting")

    await log_event(
        db,
        "OUTBOUND_TRANSFER_DELETED",
        {
            "transfer_id": ot.id,
            "status": ot.status,
            "network": ot.network,
            "amount": str(ot.amount),
            "to_address": ot.to_address,
        },
        ot.order_id,
    )
    await db.delete(ot)
    await db.commit()
    return {"deleted": True, "transfer_id": transfer_id}


# ═══════════════════════════════════════════════════════════════════════════════
# M1 TOKENIZATION JOBS — Admin Management
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/tokenization-jobs", tags=["admin-tokenization"])
async def list_tokenization_jobs(
    _: AdminKey,
    db: AsyncSession = Depends(get_db),
    status: str | None = None,
    limit: int = 100,
):
    """List M1 tokenization jobs with optional status filter."""
    q = select(M1TokenizationJob).order_by(M1TokenizationJob.created_at.desc()).limit(limit)
    if status:
        q = q.where(M1TokenizationJob.status == status.upper())
    result = await db.execute(q)
    jobs = result.scalars().all()

    output = []
    for job in jobs:
        output.append({
            "id": job.id,
            "status": job.status,
            "sender_reference": job.sender_reference,
            "sender_name": job.sender_name,
            "eur_amount": str(job.eur_amount),
            "fx_rate": str(job.fx_rate_eur_usd) if job.fx_rate_eur_usd else None,
            "usd_amount": str(job.usd_amount) if job.usd_amount else None,
            "usdt_amount": str(job.usdt_amount) if job.usdt_amount else None,
            "network": job.network,
            "destination_wallet": job.destination_wallet,
            "outbound_transfer_id": job.outbound_transfer_id,
            "error_message": job.error_message,
            "created_at": job.created_at.isoformat() if job.created_at else None,
            "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        })
    return output


@router.get("/tokenization-jobs/{job_id}", tags=["admin-tokenization"])
async def get_tokenization_job(
    job_id: str,
    _: AdminKey,
    db: AsyncSession = Depends(get_db),
):
    """Get full summary for a tokenization job including outbound transfer."""
    try:
        return await get_job_summary(db, job_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/tokenization-jobs", tags=["admin-tokenization"])
async def create_manual_tokenization_job(
    request: Request,
    _: AdminKey,
    db: AsyncSession = Depends(get_db),
):
    """
    Manually create an M1 tokenization job.
    Required: eur_amount, destination_wallet
    Optional: sender_reference, sender_name, sender_iban, network, payload_id, notes
    """
    body = await request.json()
    eur_raw = body.get("eur_amount")
    destination = body.get("destination_wallet", "").strip()

    if not eur_raw:
        raise HTTPException(status_code=422, detail="eur_amount is required")
    if not destination:
        raise HTTPException(status_code=422, detail="destination_wallet is required")

    from decimal import Decimal as D
    try:
        eur_amount = D(str(eur_raw))
    except Exception:
        raise HTTPException(status_code=422, detail="Invalid eur_amount")

    job = await create_tokenization_job(
        db,
        eur_amount=eur_amount,
        sender_reference=body.get("sender_reference"),
        sender_name=body.get("sender_name"),
        sender_iban=body.get("sender_iban"),
        payload_id=body.get("payload_id"),
        destination_wallet=destination,
        network=body.get("network", "ethereum"),
        notes=body.get("notes"),
    )
    return await get_job_summary(db, job.id)


@router.post("/tokenization-jobs/{job_id}/process", tags=["admin-tokenization"])
async def process_job(
    job_id: str,
    request: Request,
    _: AdminKey,
    db: AsyncSession = Depends(get_db),
):
    """
    Run the EUR→USD→USDT tokenization pipeline for a queued job.
    Fetches live FX rate, calculates USDT, creates OutboundTransfer (AWAITING_APPROVAL).
    """
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass

    try:
        job = await process_tokenization_job(
            db,
            job_id,
            override_destination=body.get("destination_wallet"),
            override_network=body.get("network"),
            processed_by="admin",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Processing failed: {exc}")

    summary = await get_job_summary(db, job.id)

    # Notify ops
    if job.outbound_transfer_id and job.usdt_amount:
        import asyncio
        asyncio.create_task(
            notify_m1_job_ready(
                callback_url=None,
                job_id=job_id,
                eur_amount=str(job.eur_amount),
                usdt_amount=str(job.usdt_amount),
                outbound_transfer_id=job.outbound_transfer_id,
            )
        )

    return summary


@router.post("/tokenization-jobs/gas-fee/estimate", tags=["admin-tokenization"])
async def estimate_m1_gas_fee(
    request: Request,
    _: AdminKey,
):
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    manual_fee = body.get("manual_gas_fee") or body.get("manual_native_fee")
    if manual_fee not in (None, ""):
        native_symbol = str(body.get("native_symbol") or ("TRX" if str(body.get("network") or "").lower() == "tron" else "ETH")).upper()
        return {
            "network": str(body.get("network") or "ethereum").lower(),
            "asset": str(body.get("asset") or "USDT").upper(),
            "native_symbol": native_symbol,
            "amount": str(body.get("amount") or body.get("usdt_amount") or "1"),
            "gas_limit": None,
            "gas_price_wei": None,
            "estimated_native_fee": str(manual_fee),
            "estimated_fee_label": f"{manual_fee} {native_symbol}",
            "source": "manual_admin_override",
            "manual_override": True,
        }
    return await estimate_usdt_transfer_fee(
        network=str(body.get("network") or "ethereum"),
        to_address=body.get("destination_wallet") or body.get("to_address"),
        amount=body.get("amount") or body.get("usdt_amount") or "1",
    )


@router.post("/tokenization-jobs/{job_id}/gas-fee-invoice", tags=["admin-tokenization"])
async def create_m1_gas_fee_invoice(
    job_id: str,
    request: Request,
    _: AdminKey,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(M1TokenizationJob).where(M1TokenizationJob.id == job_id)
    )
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Tokenization job not found")

    body = {}
    try:
        body = await request.json()
    except Exception:
        pass

    def _clean_decimal(value: object) -> str | None:
        if value in (None, ""):
            return None
        text = str(value).strip().replace(",", "")
        try:
            amount = Decimal(text)
        except Exception as exc:
            raise HTTPException(status_code=422, detail="Gas fee value must be a valid number") from exc
        if amount < 0:
            raise HTTPException(status_code=422, detail="Gas fee value cannot be negative")
        return str(amount)

    manual_fee = _clean_decimal(body.get("manual_gas_fee") or body.get("manual_native_fee"))
    if manual_fee in (None, ""):
        raise HTTPException(
            status_code=422,
            detail="Manual gas fee amount in USDT TRC20 is required before issuing the invoice",
        )

    estimate = {
        "network": "tron",
        "native_symbol": "USDT TRC20",
        "estimated_native_fee": str(manual_fee),
        "estimated_fee_label": f"{manual_fee} USDT TRC20",
        "source": "manual_admin_override",
        "manual_override": True,
        "settlement_asset": "USDT TRC20",
    }
    external_id = f"M1-GAS-{uuid.uuid4().hex[:10].upper()}"
    network_value = Network.TRON
    wallet = _ledger_address(network_value)

    order = PaymentOrder(
        client_id=None,
        idempotency_key=f"m1-gas-fee-{uuid.uuid4()}",
        external_id=external_id,
        provider=Provider.MANUAL,
        side=OrderSide.BUY,
        status=OrderStatus.CREATED,
        network=network_value,
        fiat_currency=str(body.get("fiat_currency") or "USD").upper(),
        fiat_amount=_clean_decimal(body.get("fiat_amount")) if body.get("fiat_amount") not in (None, "") else None,
        crypto_currency="USDT TRC20",
        crypto_amount=manual_fee,
        user_wallet_address=wallet,
        treasury_wallet_address=wallet,
        payment_reference=external_id,
        quote_json={
            "type": "M1_GAS_FEE_INVOICE",
            "tokenization_job_id": job.id,
            "tokenization_job": {
                "id": job.id,
                "sender_reference": job.sender_reference,
                "sender_name": job.sender_name,
                "sender_iban": job.sender_iban,
                "eur_amount": str(job.eur_amount) if job.eur_amount is not None else None,
                "fx_rate_eur_usd": str(job.fx_rate_eur_usd) if job.fx_rate_eur_usd is not None else None,
                "usd_amount": str(job.usd_amount) if job.usd_amount is not None else None,
                "usdt_amount": str(job.usdt_amount) if job.usdt_amount is not None else None,
                "network": job.network,
                "destination_wallet": job.destination_wallet,
                "outbound_transfer_id": job.outbound_transfer_id,
                "status": job.status,
            },
            "gas_fee_estimate": estimate,
        },
    )
    db.add(order)
    await db.commit()
    await db.refresh(order)

    await log_event(
        db,
        "M1_GAS_FEE_INVOICE_CREATED",
        {
            "job_id": job.id,
            "order_id": str(order.id),
            "external_id": external_id,
            "estimate": estimate,
        },
        order.id,
    )

    return {
        "order": _order_response(order),
        "estimate": estimate,
        "invoice_url": f"/api/v1/admin/orders/{order.id}/documents/invoice",
    }


@router.delete("/tokenization-jobs/{job_id}", tags=["admin-tokenization"])
async def delete_tokenization_job(
    job_id: str,
    _: AdminKey,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(M1TokenizationJob).where(M1TokenizationJob.id == job_id)
    )
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Tokenization job not found")
    if job.status == M1TokenizationStatus.SENDING.value:
        raise HTTPException(status_code=400, detail="Cannot delete a job while it is sending")

    await log_event(
        db,
        "M1_TOKENIZATION_JOB_DELETED",
        {
            "job_id": job.id,
            "status": job.status,
            "sender_reference": job.sender_reference,
            "eur_amount": str(job.eur_amount),
        },
        None,
    )
    await db.delete(job)
    await db.commit()
    return {"deleted": True, "job_id": job_id}


@router.get("/tokenization-jobs/fx-rate/live", tags=["admin-tokenization"])
async def get_live_fx_rate(_: AdminKey):
    """Fetch the current live EUR/USD FX rate from available providers."""
    try:
        rate, provider = await fetch_live_eur_usd()
        return {
            "eur_usd": str(rate),
            "provider": provider,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"FX rate unavailable: {exc}")


# ═══════════════════════════════════════════════════════════════════════════════
# LIVE MONITORING — System Stats API
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/monitoring/live", tags=["admin-monitoring"])
async def live_monitoring(_: AdminKey, db: AsyncSession = Depends(get_db)):
    """
    Real-time system monitoring snapshot.
    Returns aggregated counts, recent activity, and health indicators.
    """
    from sqlalchemy import text

    # Orders summary
    orders_result = await db.execute(
        select(PaymentOrder.status, func.count(PaymentOrder.id).label("cnt"))
        .group_by(PaymentOrder.status)
    )
    orders_by_status = {row.status: row.cnt for row in orders_result}

    # Payloads summary
    payloads_result = await db.execute(
        select(ExternalPayload.verification_status, func.count(ExternalPayload.id).label("cnt"))
        .group_by(ExternalPayload.verification_status)
    )
    payloads_by_status = {row.verification_status: row.cnt for row in payloads_result}

    # Outbound transfers summary
    transfers_result = await db.execute(
        select(OutboundTransfer.status, func.count(OutboundTransfer.id).label("cnt"))
        .group_by(OutboundTransfer.status)
    )
    transfers_by_status = {row.status: row.cnt for row in transfers_result}

    # Tokenization jobs summary
    jobs_result = await db.execute(
        select(M1TokenizationJob.status, func.count(M1TokenizationJob.id).label("cnt"))
        .group_by(M1TokenizationJob.status)
    )
    jobs_by_status = {row.status: row.cnt for row in jobs_result}

    # Recent 5 transfers
    recent_xfer_result = await db.execute(
        select(OutboundTransfer).order_by(OutboundTransfer.created_at.desc()).limit(5)
    )
    recent_transfers = [
        {
            "id": t.id, "status": t.status, "network": t.network,
            "amount": str(t.amount), "tx_hash": t.tx_hash,
            "created_at": t.created_at.isoformat() if t.created_at else None,
        }
        for t in recent_xfer_result.scalars().all()
    ]

    # Pending approvals (transfers needing admin action)
    pending_result = await db.execute(
        select(func.count(OutboundTransfer.id)).where(
            OutboundTransfer.status.in_([
                OutboundTransferStatus.PENDING.value,
                OutboundTransferStatus.AWAITING_APPROVAL.value,
            ])
        )
    )
    pending_approvals = pending_result.scalar() or 0

    # M1 jobs awaiting approval
    m1_pending_result = await db.execute(
        select(func.count(M1TokenizationJob.id)).where(
            M1TokenizationJob.status == M1TokenizationStatus.COMPLETED.value,
            M1TokenizationJob.outbound_transfer_id.isnot(None),
        )
    )
    m1_pending = m1_pending_result.scalar() or 0

    # Total USDT sent (completed transfers)
    usdt_result = await db.execute(
        select(func.coalesce(func.sum(OutboundTransfer.amount), 0)).where(
            OutboundTransfer.status == OutboundTransferStatus.COMPLETED.value
        )
    )
    total_usdt_sent = float(usdt_result.scalar() or 0)

    # Recent audit events
    audit_result = await db.execute(
        select(AuditLog).order_by(AuditLog.created_at.desc()).limit(10)
    )
    recent_events = [
        {
            "event_type": a.event_type,
            "order_id": a.order_id,
            "created_at": a.created_at.isoformat() if a.created_at else None,
        }
        for a in audit_result.scalars().all()
    ]

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "orders": {
            "by_status": orders_by_status,
            "total": sum(orders_by_status.values()),
        },
        "payloads": {
            "by_status": payloads_by_status,
            "total": sum(payloads_by_status.values()),
        },
        "outbound_transfers": {
            "by_status": transfers_by_status,
            "total": sum(transfers_by_status.values()),
            "pending_approvals": pending_approvals,
            "total_usdt_sent": total_usdt_sent,
            "recent": recent_transfers,
        },
        "tokenization_jobs": {
            "by_status": jobs_by_status,
            "total": sum(jobs_by_status.values()),
            "m1_awaiting_approval": m1_pending,
        },
        "recent_events": recent_events,
        "health": {
            "database": "ok",
            "pending_actions": pending_approvals + m1_pending,
        },
    }
