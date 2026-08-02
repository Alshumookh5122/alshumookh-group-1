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
    TopUpCard,
    TopUpWallet,
    TopUpTransaction,
    Provider,
    TransactionFile,
    TreasuryWallet,
)
from app.provider_service import get_provider, OnramperProvider
from app.reconciliation_service import reconcile
from app.request_utils import get_client_ip
from app.security import runtime_security_snapshot, clear_login_failures
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
    notify_transfer_failed,
    notify_m1_job_ready,
)
from app.topup_service import (
    create_wallet as topup_create_wallet,
    list_wallets as topup_list_wallets,
    get_wallet as topup_get_wallet,
    update_wallet_status as topup_update_wallet_status,
    create_card as topup_create_card,
    list_cards as topup_list_cards,
    get_card as topup_get_card,
    update_card_status as topup_update_card_status,
    process_topup,
    list_transactions as topup_list_transactions,
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


@router.get("/settings/wallets", tags=["admin-settings"])
async def get_treasury_wallets(_: AdminKey):
    """Return treasury/master wallet addresses from system config."""
    return {
        "ethereum": (settings.eth_treasury_address or settings.treasury_wallet or "").strip(),
        "tron":     (settings.master_wallet_tron or "").strip(),
        "base":     (settings.master_wallet_base or "").strip(),
        "label":    "Al Shumookh Treasury",
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


# ─── Blockchain-First Tokenization for any Payment Order ──────────────────────

@router.post("/orders/{order_id}/tokenize", tags=["admin-orders"])
async def tokenize_order(
    order_id: str,
    _: AdminKey,
    db: AsyncSession = Depends(get_db),
    payload: dict = Body(default_factory=dict),
):
    """
    Blockchain-First flow: Record the order on Ethereum BEFORE routing to provider.

    1. Converts the order's payment amount → EUR → USD → SIG tokens
    2. Creates an M1TokenizationJob and processes it immediately
    3. Creates an AWAITING_APPROVAL OutboundTransfer linked to this order
    4. Admin approves + broadcasts → real Etherscan TX hash saved to the order
    5. Order then proceeds to the payment provider (Stripe / Circle / MoonPay)

    Body (all optional):
      destination_wallet: str   — override destination (default: ETH_TREASURY_ADDRESS)
      network:            str   — "ethereum" (default)
      asset:              str   — "SIG" (default) or "USDT"
      auto_approve:       bool  — if true, also approve the OutboundTransfer immediately
    """
    destination_wallet = payload.get("destination_wallet") or None
    network            = str(payload.get("network") or "ethereum").lower()
    asset              = str(payload.get("asset") or "SIG").upper()
    auto_approve       = bool(payload.get("auto_approve", False))

    # ── 1. Fetch order ──────────────────────────────────────────────────────
    res = await db.execute(
        select(PaymentOrder).where(cast(PaymentOrder.id, String) == str(order_id))
    )
    order = res.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    # ── 2. Determine EUR-equivalent amount ─────────────────────────────────
    fiat_amount    = order.fiat_amount
    fiat_currency  = (order.fiat_currency or "USD").strip().upper()
    crypto_amount  = order.crypto_amount

    eur_amount: Decimal | None = None
    fx_rate_used: Decimal | None = None

    if fiat_amount and fiat_amount > 0:
        if fiat_currency == "EUR":
            eur_amount = fiat_amount
        else:
            # Convert USD (or other) → EUR using live FX
            fx_rate, fx_src = await fetch_live_eur_usd()
            fx_rate_used = fx_rate
            eur_amount = (fiat_amount / fx_rate).quantize(Decimal("0.000001"))
    elif crypto_amount and crypto_amount > 0:
        # Treat USDT/SIG crypto as USD-equivalent → then EUR
        fx_rate, fx_src = await fetch_live_eur_usd()
        fx_rate_used = fx_rate
        eur_amount = (crypto_amount / fx_rate).quantize(Decimal("0.000001"))

    if not eur_amount or eur_amount <= 0:
        raise HTTPException(
            status_code=400,
            detail="Order has no usable fiat or crypto amount for blockchain tokenization.",
        )

    # ── 3. Create M1TokenizationJob linked to this order ───────────────────
    payer_ref = (
        getattr(order, "external_id", None)
        or getattr(order, "idempotency_key", None)
        or str(order.id)
    )
    payer_name = getattr(order, "payer_email", None) or "ALSHUMOOKH ORDER"

    job = await create_tokenization_job(
        db,
        eur_amount=eur_amount,
        sender_reference=payer_ref,
        sender_name=payer_name,
        sender_iban=None,
        payload_id=None,
        destination_wallet=destination_wallet or None,
        network=network,
        notes=f"Blockchain-first record for PaymentOrder {order_id}",
        raw_data={
            "order_id": order_id,
            "target_asset": asset,
            "source": "order_blockchain_record",
            "original_fiat_amount": str(fiat_amount) if fiat_amount else None,
            "original_fiat_currency": fiat_currency,
            "original_crypto_amount": str(crypto_amount) if crypto_amount else None,
            "fx_rate_used": str(fx_rate_used) if fx_rate_used else None,
            "provider": (
                order.provider.value
                if hasattr(order.provider, "value")
                else str(order.provider)
            ),
        },
    )

    # ── 4. Process the pipeline: EUR → USD → SIG ───────────────────────────
    try:
        job = await process_tokenization_job(
            db,
            str(job.id),
            override_asset=asset,
            processed_by="admin",
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Tokenization pipeline failed: {exc}",
        ) from exc

    # ── 5. Link outbound transfer's order_id to this PaymentOrder ──────────
    ot_id = job.outbound_transfer_id
    ot = None
    if ot_id:
        ot_res = await db.execute(
            select(OutboundTransfer).where(OutboundTransfer.id == ot_id)
        )
        ot = ot_res.scalar_one_or_none()
        if ot and not ot.order_id:
            ot.order_id = order_id
            await db.commit()

    # ── 6. Optionally auto-approve (admin still needs to broadcast manually) ─
    if auto_approve and ot:
        try:
            ot = await approve_outbound_transfer(db, str(ot_id), approved_by="admin (auto)")
        except Exception:
            pass  # Non-fatal — admin can approve from dashboard

    await log_event(
        db,
        "ORDER_BLOCKCHAIN_RECORD_CREATED",
        {
            "order_id": order_id,
            "tokenization_job_id": str(job.id),
            "eur_amount": str(eur_amount),
            "sig_amount": str(job.usdt_amount) if job.usdt_amount else None,
            "outbound_transfer_id": ot_id,
            "network": network,
            "asset": asset,
            "auto_approve": auto_approve,
        },
        order_id,
    )

    return {
        "ok": True,
        "order_id": order_id,
        "tokenization_job_id": str(job.id),
        "job_status": job.status,
        "eur_amount": str(eur_amount),
        "sig_amount": str(job.usdt_amount) if job.usdt_amount else None,
        "network": network,
        "asset": asset,
        "outbound_transfer_id": ot_id,
        "outbound_transfer_status": ot.status if ot else None,
        "message": (
            "Blockchain record created. "
            + ("OutboundTransfer auto-approved — go to Outbound Transfers and click Broadcast to mint on Ethereum."
               if auto_approve
               else "Go to Outbound Transfers → Approve → Broadcast to record the TX hash on Ethereum.")
        ),
    }


@router.post("/orders/tokenize-batch", tags=["admin-orders"])
async def tokenize_orders_batch(
    _: AdminKey,
    db: AsyncSession = Depends(get_db),
    payload: dict = Body(default_factory=dict),
):
    """
    Bulk blockchain recording: tokenize all matching orders in one call.

    Body:
      order_ids:   list[str]  — specific IDs to process (optional)
      status:      str        — filter by status, e.g. "COMPLETED" (optional)
      asset:       str        — "SIG" (default)
      network:     str        — "ethereum" (default)
      auto_approve: bool      — also auto-approve each outbound transfer
    """
    order_ids    = payload.get("order_ids") or []
    status_filter = payload.get("status") or None
    asset        = str(payload.get("asset") or "SIG").upper()
    network      = str(payload.get("network") or "ethereum").lower()
    auto_approve = bool(payload.get("auto_approve", False))

    query = select(PaymentOrder)
    if order_ids:
        query = query.where(PaymentOrder.id.in_(order_ids))
    if status_filter:
        try:
            query = query.where(PaymentOrder.status == OrderStatus(status_filter.upper()))
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid status: {status_filter}")
    query = query.limit(50)

    res = await db.execute(query)
    orders = list(res.scalars().all())

    results = []
    for order in orders:
        try:
            sub_payload = {
                "asset": asset,
                "network": network,
                "auto_approve": auto_approve,
            }
            # Reuse single-order logic inline
            fiat_amount   = order.fiat_amount
            fiat_currency = (order.fiat_currency or "USD").strip().upper()
            crypto_amount = order.crypto_amount
            eur_amount: Decimal | None = None

            if fiat_amount and fiat_amount > 0:
                if fiat_currency == "EUR":
                    eur_amount = fiat_amount
                else:
                    fx_rate, _ = await fetch_live_eur_usd()
                    eur_amount = (fiat_amount / fx_rate).quantize(Decimal("0.000001"))
            elif crypto_amount and crypto_amount > 0:
                fx_rate, _ = await fetch_live_eur_usd()
                eur_amount = (crypto_amount / fx_rate).quantize(Decimal("0.000001"))

            if not eur_amount or eur_amount <= 0:
                results.append({"order_id": str(order.id), "ok": False, "error": "No usable amount"})
                continue

            job = await create_tokenization_job(
                db,
                eur_amount=eur_amount,
                sender_reference=order.external_id or str(order.id),
                sender_name=getattr(order, "payer_email", None) or "ALSHUMOOKH ORDER",
                network=network,
                notes=f"Batch blockchain record for PaymentOrder {order.id}",
                raw_data={"order_id": str(order.id), "target_asset": asset, "source": "batch_tokenization"},
            )
            job = await process_tokenization_job(db, str(job.id), override_asset=asset, processed_by="admin")

            ot_id = job.outbound_transfer_id
            if ot_id:
                ot_res = await db.execute(select(OutboundTransfer).where(OutboundTransfer.id == ot_id))
                ot = ot_res.scalar_one_or_none()
                if ot and not ot.order_id:
                    ot.order_id = str(order.id)
                    await db.commit()
                if auto_approve and ot:
                    try:
                        await approve_outbound_transfer(db, str(ot_id), approved_by="admin (batch)")
                    except Exception:
                        pass

            results.append({
                "order_id": str(order.id),
                "ok": True,
                "tokenization_job_id": str(job.id),
                "outbound_transfer_id": ot_id,
                "sig_amount": str(job.usdt_amount) if job.usdt_amount else None,
            })
        except Exception as exc:
            results.append({"order_id": str(order.id), "ok": False, "error": str(exc)})

    return {
        "processed": len(results),
        "success": sum(1 for r in results if r.get("ok")),
        "failed": sum(1 for r in results if not r.get("ok")),
        "results": results,
    }


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
        bridge_contract_address=payload.bridge_contract_address,
        egress_ip=payload.egress_ip,
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
            "bridge_contract_address": client.bridge_contract_address,
            "egress_ip": client.egress_ip,
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
        bridge_contract_address=client.bridge_contract_address,
        egress_ip=client.egress_ip,
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
            bridge_contract_address=client.bridge_contract_address,
            egress_ip=client.egress_ip,
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
            "bridge_contract_address": client.bridge_contract_address,
            "egress_ip": client.egress_ip,
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
        "bridge_contract_address",
        "egress_ip",
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
        bridge_contract_address=client.bridge_contract_address,
        egress_ip=client.egress_ip,
        is_active=client.is_active,
        hmac_required=client.hmac_required,
        oauth_required=client.oauth_required,
        mtls_required=client.mtls_required,
        mtls_cert_fingerprint=client.mtls_cert_fingerprint,
        jws_required=client.jws_required,
        jwe_required=client.jwe_required,
        created_at=client.created_at,
    )


class _WhitelistIpBody(BaseModel):
    ip: str

@router.post("/clients/{client_id}/whitelist-ip")
async def whitelist_client_ip(
    client_id: str,
    body: _WhitelistIpBody,
    _: AdminKey,
    db: AsyncSession = Depends(get_db),
):
    """Add an IP address to a client's allowed_ips whitelist."""
    ip_address = (body.ip or "").strip()
    if not ip_address:
        raise HTTPException(status_code=400, detail="ip is required")

    result = await db.execute(select(ApiClient).where(ApiClient.id == client_id))
    client = result.scalar_one_or_none()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    current_ips = list(client.allowed_ips or [])
    if ip_address in current_ips:
        return {"status": "already_whitelisted", "allowed_ips": current_ips, "client_name": client.name}

    current_ips.append(ip_address)
    client.allowed_ips = current_ips
    await db.commit()
    await db.refresh(client)

    await log_event(
        db,
        "IP_WHITELISTED",
        {"client_id": str(client.id), "client_name": client.name, "ip_added": ip_address, "all_ips": current_ips},
        None,
        client_id=client.id,
    )

    return {"status": "whitelisted", "allowed_ips": current_ips, "client_name": client.name}


@router.get("/clients/{client_id}/whitelist-certificate")
async def whitelist_certificate(
    client_id: str,
    ip: str,
    _: AdminKey,
    db: AsyncSession = Depends(get_db),
):
    """Generate a professional PDF IP Whitelist Authorization Certificate."""
    import io, os
    from reportlab.pdfgen import canvas as rl_canvas
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.units import cm

    result = await db.execute(select(ApiClient).where(cast(ApiClient.id, String) == str(client_id)))
    client = result.scalar_one_or_none()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    # ── Colors ─────────────────────────────────────────────────────────────────
    NAVY   = colors.HexColor("#0D1B3E")
    GOLD   = colors.HexColor("#C9A84C")
    LGOLD  = colors.HexColor("#F0D98A")
    WHITE  = colors.white
    LGRAY  = colors.HexColor("#F5F6F8")
    MGRAY  = colors.HexColor("#8E9BB5")
    DKGRAY = colors.HexColor("#333D52")
    GREEN  = colors.HexColor("#1A5C2E")
    GREENBG= colors.HexColor("#F0FFF4")

    W, H = A4
    ML = 2.2 * cm
    MR = 2.2 * cm
    CW = W - ML - MR

    buf = io.BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=A4)

    LOGO = os.path.join(os.path.dirname(__file__), "static", "company-logo.png")

    # ── Header ─────────────────────────────────────────────────────────────────
    c.setFillColor(NAVY)
    c.rect(0, H - 3.2*cm, W, 3.2*cm, fill=1, stroke=0)
    if os.path.exists(LOGO):
        c.drawImage(LOGO, ML, H - 2.9*cm, width=2.2*cm, height=2.2*cm,
                    preserveAspectRatio=True, mask="auto")
    c.setFillColor(WHITE)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(ML + 2.6*cm, H - 1.35*cm, "ALSHUMOOKH GLOBAL BANKING FINANCE & CREDIT")
    c.setFont("Helvetica", 8)
    c.setFillColor(LGOLD)
    c.drawString(ML + 2.6*cm, H - 1.85*cm,
                 "Technology & Compliance Division  |  api.alshumookh-pay.com  |  Dubai, UAE")
    c.setFillColor(GOLD)
    c.rect(0, H - 3.35*cm, W, 0.18*cm, fill=1, stroke=0)

    # ── Gold title banner ───────────────────────────────────────────────────────
    y = H - 4.0*cm
    c.setFillColor(GOLD)
    c.rect(ML, y, CW, 0.75*cm, fill=1, stroke=0)
    c.setFillColor(NAVY)
    c.setFont("Helvetica-Bold", 12)
    c.drawCentredString(W / 2, y + 0.2*cm, "IP WHITELIST AUTHORIZATION CERTIFICATE")
    y -= 0.6*cm

    # ── Cert number & date ──────────────────────────────────────────────────────
    cert_num = "ALSH-WL-" + str(client.id).upper()[:8] + "-" + ip.replace(".", "")
    issued = datetime.now(timezone.utc).strftime("%d %B %Y")
    c.setFont("Helvetica", 8)
    c.setFillColor(MGRAY)
    c.drawCentredString(W / 2, y, f"Certificate No: {cert_num}   |   Issued: {issued}")
    y -= 0.9*cm

    # ── Intro text ──────────────────────────────────────────────────────────────
    intro = (
        "This certificate confirms that the IP address specified herein has been formally reviewed, "
        "approved, and added to the authorized access whitelist of ALSHUMOOKH Global Banking Finance & Credit. "
        "The bearer of this certificate is authorized to establish connections to the Alshumookh Pay API "
        "gateway from the whitelisted IP address stated below."
    )
    c.setFont("Helvetica", 9)
    c.setFillColor(DKGRAY)
    words = intro.split()
    line = ""
    for w in words:
        test = (line + " " + w).strip()
        if c.stringWidth(test, "Helvetica", 9) <= CW:
            line = test
        else:
            c.drawCentredString(W / 2, y, line)
            y -= 0.44*cm
            line = w
    if line:
        c.drawCentredString(W / 2, y, line)
    y -= 0.7*cm

    # ── Main IP box ─────────────────────────────────────────────────────────────
    box_h = 2.8*cm
    c.setFillColor(GREENBG)
    c.roundRect(ML, y - box_h, CW, box_h, 6, fill=1, stroke=0)
    c.setStrokeColor(GREEN)
    c.setLineWidth(1.5)
    c.roundRect(ML, y - box_h, CW, box_h, 6, fill=0, stroke=1)

    c.setFont("Helvetica", 9)
    c.setFillColor(GREEN)
    c.drawCentredString(W / 2, y - 0.55*cm, "AUTHORIZED IP ADDRESS")
    c.setFont("Helvetica-Bold", 22)
    c.setFillColor(NAVY)
    c.drawCentredString(W / 2, y - 1.35*cm, ip)
    c.setFont("Helvetica", 8.5)
    c.setFillColor(GREEN)
    c.drawCentredString(W / 2, y - 1.95*cm, "STATUS: ACTIVE — AUTHORIZED FOR API ACCESS")
    y -= box_h + 0.7*cm

    # ── Details table ───────────────────────────────────────────────────────────
    rows = [
        ("Client Name",    client.name),
        ("Client ID",      str(client.id)),
        ("IP Address",     ip),
        ("Access Level",   "Full API Gateway Access — ISO 20022 / Settlement Channel"),
        ("Issued By",      "ALSHUMOOKH Global Banking Finance & Credit — Technology Division"),
        ("Date Issued",    issued),
        ("Valid Until",    datetime.now(timezone.utc).replace(year=datetime.now(timezone.utc).year + 1).strftime("%d %B %Y")),
        ("License No.",    "887065"),
    ]
    row_h = 0.52*cm
    col1_w = 5.5*cm

    for i, (label, value) in enumerate(rows):
        bg = LGRAY if i % 2 == 0 else WHITE
        c.setFillColor(bg)
        c.rect(ML, y - row_h, CW, row_h, fill=1, stroke=0)
        c.setStrokeColor(colors.HexColor("#DEE2EA"))
        c.setLineWidth(0.4)
        c.line(ML, y - row_h, ML + CW, y - row_h)
        c.setFont("Helvetica-Bold", 8.3)
        c.setFillColor(NAVY)
        c.drawString(ML + 0.3*cm, y - 0.35*cm, label)
        c.setFont("Helvetica", 8.3)
        c.setFillColor(DKGRAY)
        c.drawString(ML + col1_w, y - 0.35*cm, value[:80])
        y -= row_h

    y -= 0.5*cm

    # ── Legal statement ─────────────────────────────────────────────────────────
    c.setFillColor(colors.HexColor("#FFF8E8"))
    c.roundRect(ML, y - 1.6*cm, CW, 1.6*cm, 4, fill=1, stroke=0)
    c.setStrokeColor(GOLD)
    c.setLineWidth(1)
    c.roundRect(ML, y - 1.6*cm, CW, 1.6*cm, 4, fill=0, stroke=1)
    legal = (
        "This certificate is electronically issued under License No. 887065 and is valid for one (1) year from the date of issue. "
        "The authorized IP address is registered in the Alshumookh Pay security infrastructure and is monitored in accordance with ISO 27001:2022 "
        "and UAE CBUAE regulatory requirements. Unauthorized use or transfer of this certificate is strictly prohibited."
    )
    c.setFont("Helvetica", 7.8)
    c.setFillColor(colors.HexColor("#7A6000"))
    lwords = legal.split()
    ll = ""
    ly = y - 0.4*cm
    for w in lwords:
        test = (ll + " " + w).strip()
        if c.stringWidth(test, "Helvetica", 7.8) <= CW - 0.6*cm:
            ll = test
        else:
            c.drawString(ML + 0.3*cm, ly, ll)
            ly -= 0.38*cm
            ll = w
    if ll:
        c.drawString(ML + 0.3*cm, ly, ll)
    y -= 1.9*cm

    # ── Signature ───────────────────────────────────────────────────────────────
    c.setFont("Helvetica", 9)
    c.setFillColor(DKGRAY)
    c.drawString(ML, y, "Authorized by:")
    y -= 0.7*cm
    c.setFont("Helvetica-Bold", 10)
    c.setFillColor(NAVY)
    c.drawString(ML, y, "ALSHUMOOKH Global Banking Finance & Credit")
    y -= 0.44*cm
    c.setFont("Helvetica", 8.5)
    c.setFillColor(MGRAY)
    c.drawString(ML, y, "Technology & Compliance Division  |  api.alshumookh-pay.com")

    # ── Footer ──────────────────────────────────────────────────────────────────
    c.setFillColor(GOLD)
    c.rect(0, 1.4*cm, W, 0.13*cm, fill=1, stroke=0)
    c.setFillColor(NAVY)
    c.rect(0, 0, W, 1.4*cm, fill=1, stroke=0)
    c.setFillColor(LGOLD)
    c.setFont("Helvetica", 7)
    c.drawCentredString(W / 2, 0.75*cm,
        "ALSHUMOOKH GROUP  |  API World Tower, Office No. 2103/2104, Shaikh Zayed Road, Dubai, UAE  |  Lic. 887065  |  api.alshumookh-pay.com")
    c.setFont("Helvetica", 6.5)
    c.setFillColor(MGRAY)
    c.drawCentredString(W / 2, 0.38*cm, f"Certificate No: {cert_num}  —  This document is digitally authorized and legally binding.")

    c.save()
    buf.seek(0)

    safe_name = f"IP_Whitelist_Certificate_{ip.replace('.', '_')}.pdf"
    return Response(
        content=buf.read(),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}"'},
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


@router.get("/ip-investigation/{ip}")
async def ip_investigation(
    ip: str,
    _: AdminKey,
    db: AsyncSession = Depends(get_db),
):
    """Return all login failures + identifiers attempted from a given IP, plus unlock status and geo info."""
    import urllib.parse
    import time
    import httpx
    ip = urllib.parse.unquote(ip)

    res = await db.execute(
        select(AuditLog)
        .where(AuditLog.ip == ip)
        .order_by(AuditLog.created_at.desc())
        .limit(200)
    )
    logs = list(res.scalars().all())

    identifiers_tried: list[str] = []
    login_events: list[dict] = []
    for log in logs:
        details = log.details if isinstance(log.details, dict) else {}
        event_type = str(log.event_type or "")
        if event_type in {"CLIENT_LOGIN_FAILED", "SECURITY_CLIENT_LOGIN_FAILED"}:
            ident = details.get("identifier")
            if ident and ident not in identifiers_tried:
                identifiers_tried.append(str(ident))
        if "LOGIN" in event_type or "LOCKED" in event_type or "RATE_LIMITED" in event_type:
            login_events.append(serialize_log(log))

    from app.security import _login_lock_until, _login_failures
    now = time.time()
    lock_until = _login_lock_until.get(ip, 0)
    is_locked = lock_until > now
    lock_seconds_remaining = max(0, int(lock_until - now))

    # ── Geo lookup via ip-api.com (free, no key required) ──────────────────
    geo: dict = {}
    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            r = await client.get(
                f"http://ip-api.com/json/{ip}",
                params={"fields": "status,country,countryCode,regionName,city,zip,lat,lon,timezone,isp,org,as,proxy,hosting,mobile,query"},
            )
            if r.status_code == 200:
                data = r.json()
                if data.get("status") == "success":
                    geo = {
                        "country":     data.get("country"),
                        "country_code": data.get("countryCode"),
                        "region":      data.get("regionName"),
                        "city":        data.get("city"),
                        "zip":         data.get("zip"),
                        "lat":         data.get("lat"),
                        "lon":         data.get("lon"),
                        "timezone":    data.get("timezone"),
                        "isp":         data.get("isp"),
                        "org":         data.get("org"),
                        "as":          data.get("as"),
                        "is_proxy":    data.get("proxy", False),
                        "is_hosting":  data.get("hosting", False),
                        "is_mobile":   data.get("mobile", False),
                    }
    except Exception:
        pass

    return {
        "ip": ip,
        "is_locked": is_locked,
        "lock_seconds_remaining": lock_seconds_remaining,
        "identifiers_tried": identifiers_tried,
        "total_events_from_ip": len(logs),
        "login_events": login_events[:50],
        "geo": geo,
    }


@router.post("/ip-unlock/{ip}")
async def ip_unlock(
    ip: str,
    _: AdminKey,
    db: AsyncSession = Depends(get_db),
):
    """Manually clear the login lock for a given IP address."""
    import urllib.parse
    ip = urllib.parse.unquote(ip)
    clear_login_failures(ip)
    await log_event(
        db,
        "ADMIN_IP_UNLOCKED",
        {"ip": ip, "unlocked_by": "admin"},
        None,
    )
    return {"success": True, "ip": ip, "message": f"Login lock cleared for {ip}"}


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


# ════════════════════════════════════════════════════════════════════
#  TOP-UP ENGINE  —  Wallets, Cards, Transactions
# ════════════════════════════════════════════════════════════════════

# ── Wallets ──────────────────────────────────────────────────────────

@router.post("/topup/wallets")
async def topup_wallet_create(
    _: AdminKey,
    db: AsyncSession = Depends(get_db),
    name: str = Body(...),
    currency: str = Body("USDT"),
    network: str = Body("ethereum"),
    blockchain_address: str | None = Body(None),
    notes: str | None = Body(None),
):
    wallet = await topup_create_wallet(
        db, name=name, currency=currency, network=network,
        blockchain_address=blockchain_address, notes=notes,
    )
    return _topup_wallet_dict(wallet)


@router.get("/topup/wallets")
async def topup_wallet_list(_: AdminKey, db: AsyncSession = Depends(get_db)):
    wallets = await topup_list_wallets(db)
    return [_topup_wallet_dict(w) for w in wallets]


@router.get("/topup/wallets/{wallet_id}")
async def topup_wallet_get(wallet_id: str, _: AdminKey, db: AsyncSession = Depends(get_db)):
    wallet = await topup_get_wallet(db, wallet_id)
    if not wallet:
        raise HTTPException(status_code=404, detail="Wallet not found")
    return _topup_wallet_dict(wallet)


@router.patch("/topup/wallets/{wallet_id}/status")
async def topup_wallet_status(
    wallet_id: str,
    _: AdminKey,
    db: AsyncSession = Depends(get_db),
    status: str = Body(...),
):
    wallet = await topup_update_wallet_status(db, wallet_id, status)
    return _topup_wallet_dict(wallet)


# ── Cards ─────────────────────────────────────────────────────────────

@router.post("/topup/cards")
async def topup_card_create(
    _: AdminKey,
    db: AsyncSession = Depends(get_db),
    card_number: str = Body(...),
    wallet_id: str = Body(...),
    holder_name: str | None = Body(None),
    provider_name: str | None = Body(None),
    notes: str | None = Body(None),
):
    try:
        card = await topup_create_card(
            db, card_number=card_number, wallet_id=wallet_id,
            holder_name=holder_name, provider_name=provider_name, notes=notes,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _topup_card_dict(card)


@router.get("/topup/cards")
async def topup_card_list(_: AdminKey, db: AsyncSession = Depends(get_db)):
    cards = await topup_list_cards(db)
    return [_topup_card_dict(c) for c in cards]


@router.get("/topup/cards/{card_id}")
async def topup_card_get(card_id: str, _: AdminKey, db: AsyncSession = Depends(get_db)):
    card = await topup_get_card(db, card_id)
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")
    return _topup_card_dict(card)


@router.patch("/topup/cards/{card_id}/status")
async def topup_card_status(
    card_id: str,
    _: AdminKey,
    db: AsyncSession = Depends(get_db),
    status: str = Body(...),
):
    try:
        card = await topup_update_card_status(db, card_id, status)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return _topup_card_dict(card)


# ── Top-Up Request (Provider Endpoint) ───────────────────────────────

@router.post("/topup/request")
async def topup_request(
    _: AdminKey,
    db: AsyncSession = Depends(get_db),
    card_number: str = Body(...),
    amount: Decimal = Body(...),
    currency: str = Body("USDT"),
    provider_name: str | None = Body(None),
    provider_ref: str | None = Body(None),
):
    """
    Main top-up endpoint called by the provider.
    Body: { card_number, amount, currency, provider_name, provider_ref }
    """
    try:
        txn = await process_topup(
            db,
            card_number=card_number,
            amount=amount,
            currency=currency,
            provider_name=provider_name,
            provider_ref=provider_ref,
            raw_request={"card_number": card_number, "amount": str(amount), "currency": currency},
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _topup_txn_dict(txn)


# ── Transactions ──────────────────────────────────────────────────────

@router.get("/topup/transactions")
async def topup_txn_list(
    _: AdminKey,
    db: AsyncSession = Depends(get_db),
    card_id: str | None = None,
    limit: int = 100,
):
    txns = await topup_list_transactions(db, card_id=card_id, limit=limit)
    return [_topup_txn_dict(t) for t in txns]


# ── Serializers ───────────────────────────────────────────────────────

def _topup_wallet_dict(w: TopUpWallet) -> dict:
    return {
        "id": w.id,
        "name": w.name,
        "currency": w.currency,
        "balance": str(w.balance),
        "network": w.network,
        "blockchain_address": w.blockchain_address,
        "status": w.status,
        "notes": w.notes,
        "created_at": w.created_at.isoformat() if w.created_at else None,
    }


def _topup_card_dict(c: TopUpCard) -> dict:
    return {
        "id": c.id,
        "card_number": c.card_number,
        "wallet_id": c.wallet_id,
        "holder_name": c.holder_name,
        "provider_name": c.provider_name,
        "status": c.status,
        "notes": c.notes,
        "created_at": c.created_at.isoformat() if c.created_at else None,
    }


def _topup_txn_dict(t: TopUpTransaction) -> dict:
    return {
        "id": t.id,
        "reference": t.reference,
        "card_id": t.card_id,
        "card_number": t.card_number,
        "provider_name": t.provider_name,
        "amount": str(t.amount),
        "currency": t.currency,
        "status": t.status,
        "failure_reason": t.failure_reason,
        "provider_ref": t.provider_ref,
        "created_at": t.created_at.isoformat() if t.created_at else None,
    }


@router.get("/reports/transactions", response_class=HTMLResponse)
async def transactions_report(
    _: AdminKey,
    db: AsyncSession = Depends(get_db),
    order_id: str | None = None,
):
    import datetime as _dt

    # ── CSS shared across all report types ───────────────────────────
    _CSS = """
    *,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
    body{font-family:'Segoe UI',Arial,sans-serif;font-size:13px;color:#111827;background:#f4f7fb;padding:30px}
    .sheet{max-width:1200px;margin:0 auto;background:#fff;border:1px solid #d8e0ea;box-shadow:0 18px 50px rgba(15,23,42,.08);padding:36px}
    .letterhead{display:flex;justify-content:space-between;align-items:flex-start;border-bottom:3px solid #0D1B3E;padding-bottom:18px;margin-bottom:18px}
    .lh-left .brand{color:#C9A84C;font-size:11px;font-weight:900;letter-spacing:.12em;text-transform:uppercase}
    .lh-left h1{font-size:26px;color:#0D1B3E;margin:6px 0 4px}
    .lh-left .sub{color:#667085;font-size:12px}
    .lh-right{text-align:right;font-size:11px;color:#667085;line-height:1.8}
    .lh-right strong{color:#0D1B3E;font-size:12px}
    .badge-type{display:inline-block;padding:3px 10px;font-size:11px;font-weight:800;letter-spacing:.08em;border-radius:4px;margin-top:6px}
    .bt-order{background:#dbeafe;color:#1e40af}
    .bt-m1{background:#d1fae5;color:#065f46}
    .bt-payload{background:#fef3c7;color:#92400e}
    .bt-transfer{background:#ede9fe;color:#5b21b6}
    .metrics{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:12px;margin:20px 0}
    .metric{border:1px solid #d8e0ea;padding:14px;border-radius:8px;background:#fbfcff}
    .metric span{color:#667085;font-size:11px;display:block}
    .metric strong{display:block;margin-top:6px;font-size:22px;color:#0D1B3E}
    .sec-title{background:#0D1B3E;color:#C9A84C;font-size:11px;font-weight:700;letter-spacing:.14em;text-transform:uppercase;padding:6px 12px;margin:20px 0 0}
    table{width:100%;border-collapse:collapse;font-size:12px}
    th,td{border-bottom:1px solid #d8e0ea;padding:9px 8px;text-align:left;vertical-align:top;word-break:break-word}
    th{background:#f0f4fc;color:#2A3F72;font-weight:700;font-size:11px;text-transform:uppercase;letter-spacing:.06em}
    tr:nth-child(even) td{background:#f8fafc}
    .hash{font-family:'Courier New',monospace;font-size:10px;color:#1565C0;word-break:break-all}
    .url-link{color:#1565C0;font-size:10px;text-decoration:none}
    .url-link:hover{text-decoration:underline}
    .st{display:inline-block;padding:3px 8px;border-radius:5px;font-weight:800;font-size:11px}
    .COMPLETED,.CONFIRMED,.VERIFIED,.RECONCILED,.SENT{color:#0f8a5f;background:#e7f6ef}
    .PENDING,.PROCESSING,.CREATED,.PENDING_CONFIRMATION,.AWAITING_APPROVAL,.APPROVED,.BROADCASTING,.PARSED,.MANUAL_REVIEW{color:#ad6a00;background:#fff6e8}
    .FAILED,.REJECTED,.CANCELLED{color:#b83232;background:#fff0f0}
    .detail-grid{display:grid;grid-template-columns:1fr 1fr;gap:0;border:1px solid #d8e0ea;margin-top:0}
    .detail-row{display:contents}
    .detail-row .dk{background:#f0f4fc;font-weight:700;color:#2A3F72;padding:8px 12px;border-bottom:1px solid #d8e0ea;font-size:11px;text-transform:uppercase;letter-spacing:.05em}
    .detail-row .dv{padding:8px 12px;border-bottom:1px solid #d8e0ea;font-size:12px;color:#111}
    .detail-row .dv.mono{font-family:'Courier New',monospace;font-size:11px;word-break:break-all}
    .detail-row .dv.hi{color:#1565C0;font-family:'Courier New',monospace;font-size:10px;word-break:break-all;background:#EBF3FF}
    .bc-box{background:#E8F5E9;border:1.5px solid #1B7A4A;padding:12px 16px;margin:14px 0;text-align:center}
    .bc-box .bc-title{font-size:13px;font-weight:800;color:#1B7A4A;letter-spacing:.06em}
    .bc-box .bc-hash{font-family:'Courier New',monospace;font-size:11px;color:#1565C0;margin-top:4px;word-break:break-all}
    .bc-box .bc-url{font-size:11px;color:#555;margin-top:3px}
    .actions{max-width:1200px;margin:16px auto 0;display:flex;gap:10px;justify-content:flex-end}
    .btn{min-height:38px;padding:8px 18px;border:0;border-radius:6px;font-weight:800;font-size:12px;cursor:pointer;letter-spacing:.04em}
    .btn-print{background:#0D1B3E;color:#fff}
    .btn-close{background:#fff;color:#0D1B3E;border:2px solid #0D1B3E}
    @media print{body{background:#fff;padding:0}.sheet{border:0;box-shadow:none}.actions{display:none}}
    """

    now_str = _dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

    # ── SINGLE-RECORD LOOKUP (order_id provided) ─────────────────────
    if order_id:
        oid = str(order_id).strip()

        # 1. PaymentOrder
        r1 = await db.execute(select(PaymentOrder).where(cast(PaymentOrder.id, String) == oid))
        po = r1.scalar_one_or_none()
        if po:
            tx = getattr(po, "tx_hash", None)
            explorer = f"https://etherscan.io/tx/{tx.lstrip('0x') if tx else ''}" if tx else None
            st_val = po.status.value if hasattr(po.status, "value") else str(po.status)
            html = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>Transaction Report — {oid}</title><style>{_CSS}</style></head><body>
<div class="sheet">
  <div class="letterhead">
    <div class="lh-left">
      <div class="brand">ALSHUMOOKH GLOBAL BANKING FINANCE &amp; CREDIT</div>
      <h1>Transaction Report</h1>
      <div class="sub">Payment Order — Full Transaction Record</div>
      <span class="badge-type bt-order">PAYMENT ORDER</span>
    </div>
    <div class="lh-right">
      <strong>Reference</strong><br>{po.external_id or po.id}<br>
      <strong>Generated</strong><br>{now_str}<br>
      <strong>Status</strong><br><span class="st {st_val}">{st_val}</span>
    </div>
  </div>
  <div class="sec-title">Transaction Details</div>
  <div class="detail-grid">
    <div class="detail-row"><div class="dk">Transaction UUID</div><div class="dv mono">{po.id}</div></div>
    <div class="detail-row"><div class="dk">Payment Reference</div><div class="dv mono">{po.payment_reference or po.external_id or "-"}</div></div>
    <div class="detail-row"><div class="dk">Status</div><div class="dv"><span class="st {st_val}">{st_val}</span></div></div>
    <div class="detail-row"><div class="dk">Provider</div><div class="dv mono">{po.provider.value if hasattr(po.provider,"value") else po.provider}</div></div>
    <div class="detail-row"><div class="dk">Network</div><div class="dv mono">{po.network.value if hasattr(po.network,"value") else po.network}</div></div>
    <div class="detail-row"><div class="dk">Fiat Amount</div><div class="dv">{po.fiat_amount or "-"} {po.fiat_currency or ""}</div></div>
    <div class="detail-row"><div class="dk">Crypto Amount</div><div class="dv">{po.crypto_amount or "-"} {po.crypto_currency or ""}</div></div>
    <div class="detail-row"><div class="dk">Payer Email</div><div class="dv">{po.payer_email or "-"}</div></div>
    <div class="detail-row"><div class="dk">Sender Wallet</div><div class="dv mono">{po.user_wallet_address or "-"}</div></div>
    <div class="detail-row"><div class="dk">Receiver Wallet</div><div class="dv mono">{po.treasury_wallet_address or po.customer_wallet_address or "-"}</div></div>
    <div class="detail-row"><div class="dk">TX Hash</div><div class="dv {'hi' if tx else 'mono'}">{tx or "-"}</div></div>
    <div class="detail-row"><div class="dk">Provider Order ID</div><div class="dv mono">{po.provider_order_id or "-"}</div></div>
    <div class="detail-row"><div class="dk">External ID</div><div class="dv mono">{po.external_id or "-"}</div></div>
    <div class="detail-row"><div class="dk">Failure Reason</div><div class="dv">{po.failure_reason or "-"}</div></div>
    <div class="detail-row"><div class="dk">Created At (UTC)</div><div class="dv">{po.created_at}</div></div>
    <div class="detail-row"><div class="dk">Updated At (UTC)</div><div class="dv">{po.updated_at}</div></div>
  </div>
  {f'<div class="bc-box"><div class="bc-title">&#10003; BLOCKCHAIN TRANSACTION — ETHEREUM MAINNET</div><div class="bc-hash">TX HASH: {tx}</div><div class="bc-url">Verify: <a class="url-link" href="{explorer}" target="_blank">{explorer}</a></div></div>' if tx else ""}
</div>
<div class="actions">
  <button class="btn btn-print" onclick="window.print()">&#128424; Print / Save PDF</button>
  <button class="btn btn-close" onclick="window.close()">&#10005; Close</button>
</div></body></html>"""
            return HTMLResponse(html)

        # 2. M1TokenizationJob
        r2 = await db.execute(select(M1TokenizationJob).where(cast(M1TokenizationJob.id, String) == oid))
        job = r2.scalar_one_or_none()
        if job:
            st_val = str(job.status)
            xfer_id = str(job.outbound_transfer_id) if job.outbound_transfer_id else None
            # try to get TX hash from linked OutboundTransfer
            tx = None
            explorer = None
            if xfer_id:
                rx = await db.execute(select(OutboundTransfer).where(cast(OutboundTransfer.id, String) == xfer_id))
                xfer = rx.scalar_one_or_none()
                if xfer:
                    tx = xfer.tx_hash
                    explorer = xfer.explorer_url or (f"https://etherscan.io/tx/{tx.lstrip('0x')}" if tx else None)
            html = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>M1 Tokenization Report — {oid}</title><style>{_CSS}</style></head><body>
<div class="sheet">
  <div class="letterhead">
    <div class="lh-left">
      <div class="brand">ALSHUMOOKH GLOBAL BANKING FINANCE &amp; CREDIT</div>
      <h1>M1 Tokenization Report</h1>
      <div class="sub">EUR → SIG Settlement — Full Transaction Record</div>
      <span class="badge-type bt-m1">M1 TOKENIZATION</span>
    </div>
    <div class="lh-right">
      <strong>M1 Job ID</strong><br>{job.id}<br>
      <strong>Generated</strong><br>{now_str}<br>
      <strong>Status</strong><br><span class="st {st_val}">{st_val}</span>
    </div>
  </div>
  <div class="sec-title">M1 Job Details</div>
  <div class="detail-grid">
    <div class="detail-row"><div class="dk">M1 Job UUID</div><div class="dv mono">{job.id}</div></div>
    <div class="detail-row"><div class="dk">Sender Reference</div><div class="dv mono">{job.sender_reference or "-"}</div></div>
    <div class="detail-row"><div class="dk">Sender Full Name</div><div class="dv">{job.sender_name or "-"}</div></div>
    <div class="detail-row"><div class="dk">Sender IBAN</div><div class="dv mono">{job.sender_iban or "-"}</div></div>
    <div class="detail-row"><div class="dk">Job Status</div><div class="dv"><span class="st {st_val}">{st_val}</span></div></div>
    <div class="detail-row"><div class="dk">Settlement Network</div><div class="dv mono">{job.network or "ethereum"}</div></div>
    <div class="detail-row"><div class="dk">EUR Amount</div><div class="dv">{job.eur_amount or "-"} EUR</div></div>
    <div class="detail-row"><div class="dk">USD Converted</div><div class="dv">{job.usd_amount or "-"} USD</div></div>
    <div class="detail-row"><div class="dk">FX Rate EUR/USD</div><div class="dv">{job.fx_rate_eur_usd or "-"}</div></div>
    <div class="detail-row"><div class="dk">SIG Token Output</div><div class="dv">{job.usdt_amount or "-"} SIG</div></div>
    <div class="detail-row"><div class="dk">SIG Token Contract</div><div class="dv mono">0xdAC17F958D2ee523a2206206994597C13D831ec7</div></div>
    <div class="detail-row"><div class="dk">Destination Wallet</div><div class="dv mono">{job.destination_wallet or "-"}</div></div>
    <div class="detail-row"><div class="dk">Outbound Transfer ID</div><div class="dv mono">{xfer_id or "-"}</div></div>
    <div class="detail-row"><div class="dk">Linked Payload ID</div><div class="dv mono">{job.payload_id or "-"}</div></div>
    <div class="detail-row"><div class="dk">Blockchain TX Hash</div><div class="dv {'hi' if tx else 'mono'}">{tx or "-"}</div></div>
    <div class="detail-row"><div class="dk">Error Message</div><div class="dv">{job.error_message or "-"}</div></div>
    <div class="detail-row"><div class="dk">Created At (UTC)</div><div class="dv">{job.created_at}</div></div>
    <div class="detail-row"><div class="dk">Updated At (UTC)</div><div class="dv">{job.updated_at}</div></div>
  </div>
  {f'<div class="bc-box"><div class="bc-title">&#10003; BLOCKCHAIN TRANSACTION CONFIRMED — ETHEREUM MAINNET</div><div class="bc-hash">TX HASH: {tx}</div><div class="bc-url">Verify: <a class="url-link" href="{explorer}" target="_blank">{explorer}</a></div></div>' if tx else ""}
</div>
<div class="actions">
  <button class="btn btn-print" onclick="window.print()">&#128424; Print / Save PDF</button>
  <button class="btn btn-close" onclick="window.close()">&#10005; Close</button>
</div></body></html>"""
            return HTMLResponse(html)

        # 3. ExternalPayload
        r3 = await db.execute(select(ExternalPayload).where(cast(ExternalPayload.id, String) == oid))
        ep = r3.scalar_one_or_none()
        if ep:
            tx = ep.tx_hash
            explorer = ep.explorer_url or (f"https://etherscan.io/tx/{tx.lstrip('0x')}" if tx else None)
            st_val = str(ep.verification_status)
            html = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>Settlement Payload Report — {oid}</title><style>{_CSS}</style></head><body>
<div class="sheet">
  <div class="letterhead">
    <div class="lh-left">
      <div class="brand">ALSHUMOOKH GLOBAL BANKING FINANCE &amp; CREDIT</div>
      <h1>Settlement Payload Report</h1>
      <div class="sub">Inbound SWIFT Payload — Full Verification Record</div>
      <span class="badge-type bt-payload">SETTLEMENT PAYLOAD</span>
    </div>
    <div class="lh-right">
      <strong>Payload UUID</strong><br>{ep.id}<br>
      <strong>Generated</strong><br>{now_str}<br>
      <strong>Status</strong><br><span class="st {st_val}">{st_val}</span>
    </div>
  </div>
  <div class="sec-title">Payload Details</div>
  <div class="detail-grid">
    <div class="detail-row"><div class="dk">Payload UUID</div><div class="dv mono">{ep.id}</div></div>
    <div class="detail-row"><div class="dk">Transaction Reference</div><div class="dv mono">{ep.transaction_reference or "-"}</div></div>
    <div class="detail-row"><div class="dk">Verification Status</div><div class="dv"><span class="st {st_val}">{st_val}</span></div></div>
    <div class="detail-row"><div class="dk">Parsing Status</div><div class="dv">{ep.parsing_status or "-"}</div></div>
    <div class="detail-row"><div class="dk">Security Level</div><div class="dv">{ep.security_level or "-"}</div></div>
    <div class="detail-row"><div class="dk">Amount</div><div class="dv">{ep.amount or "-"} {ep.asset or ""}</div></div>
    <div class="detail-row"><div class="dk">Network</div><div class="dv mono">{ep.network_name or "-"}</div></div>
    <div class="detail-row"><div class="dk">Sender Wallet</div><div class="dv mono">{ep.sender_wallet or "-"}</div></div>
    <div class="detail-row"><div class="dk">Receiver Wallet</div><div class="dv mono">{ep.receiver_wallet or "-"}</div></div>
    <div class="detail-row"><div class="dk">Token Contract</div><div class="dv mono">{ep.token_contract or "0xdAC17F958D2ee523a2206206994597C13D831ec7"}</div></div>
    <div class="detail-row"><div class="dk">Settlement Type</div><div class="dv">{ep.settlement_type or "-"}</div></div>
    <div class="detail-row"><div class="dk">Authorization Code</div><div class="dv">{ep.authorization_code or "-"}</div></div>
    <div class="detail-row"><div class="dk">Block Number</div><div class="dv">{ep.block_number or "-"}</div></div>
    <div class="detail-row"><div class="dk">Confirmations</div><div class="dv">{ep.confirmations or "-"}</div></div>
    <div class="detail-row"><div class="dk">Review Decision</div><div class="dv">{ep.review_decision or "-"}</div></div>
    <div class="detail-row"><div class="dk">Review Note</div><div class="dv">{ep.review_note or "-"}</div></div>
    <div class="detail-row"><div class="dk">Blockchain TX Hash</div><div class="dv {'hi' if tx else 'mono'}">{tx or "-"}</div></div>
    <div class="detail-row"><div class="dk">Error Message</div><div class="dv">{ep.error_message or "-"}</div></div>
    <div class="detail-row"><div class="dk">Created At (UTC)</div><div class="dv">{ep.created_at}</div></div>
  </div>
  {f'<div class="bc-box"><div class="bc-title">&#10003; BLOCKCHAIN TRANSACTION VERIFIED — ETHEREUM MAINNET</div><div class="bc-hash">TX HASH: {tx}</div><div class="bc-url">Verify: <a class="url-link" href="{explorer}" target="_blank">{explorer}</a></div></div>' if tx else ""}
</div>
<div class="actions">
  <button class="btn btn-print" onclick="window.print()">&#128424; Print / Save PDF</button>
  <button class="btn btn-close" onclick="window.close()">&#10005; Close</button>
</div></body></html>"""
            return HTMLResponse(html)

        # 4. OutboundTransfer
        r4 = await db.execute(select(OutboundTransfer).where(cast(OutboundTransfer.id, String) == oid))
        xfer = r4.scalar_one_or_none()
        if xfer:
            tx = xfer.tx_hash
            explorer = xfer.explorer_url or (f"https://etherscan.io/tx/{tx.lstrip('0x')}" if tx else None)
            st_val = str(xfer.status)
            html = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>Outbound Transfer Report — {oid}</title><style>{_CSS}</style></head><body>
<div class="sheet">
  <div class="letterhead">
    <div class="lh-left">
      <div class="brand">ALSHUMOOKH GLOBAL BANKING FINANCE &amp; CREDIT</div>
      <h1>Outbound Transfer Report</h1>
      <div class="sub">SIG Token Blockchain Settlement — Full Record</div>
      <span class="badge-type bt-transfer">OUTBOUND TRANSFER</span>
    </div>
    <div class="lh-right">
      <strong>Transfer ID</strong><br>{xfer.id}<br>
      <strong>Generated</strong><br>{now_str}<br>
      <strong>Status</strong><br><span class="st {st_val}">{st_val}</span>
    </div>
  </div>
  <div class="sec-title">Transfer Details</div>
  <div class="detail-grid">
    <div class="detail-row"><div class="dk">Transfer UUID</div><div class="dv mono">{xfer.id}</div></div>
    <div class="detail-row"><div class="dk">Linked Order ID</div><div class="dv mono">{xfer.order_id or "-"}</div></div>
    <div class="detail-row"><div class="dk">Linked Payload ID</div><div class="dv mono">{xfer.payload_id or "-"}</div></div>
    <div class="detail-row"><div class="dk">Linked M1 Job ID</div><div class="dv mono">{xfer.tokenization_job_id or "-"}</div></div>
    <div class="detail-row"><div class="dk">Status</div><div class="dv"><span class="st {st_val}">{st_val}</span></div></div>
    <div class="detail-row"><div class="dk">Network</div><div class="dv mono">{xfer.network}</div></div>
    <div class="detail-row"><div class="dk">Asset</div><div class="dv">{xfer.asset}</div></div>
    <div class="detail-row"><div class="dk">Token Contract (SIG)</div><div class="dv mono">{xfer.contract_address or "0xdAC17F958D2ee523a2206206994597C13D831ec7"}</div></div>
    <div class="detail-row"><div class="dk">From Address</div><div class="dv mono">{xfer.from_address or "ALSHUMOOKH SIG TREASURY"}</div></div>
    <div class="detail-row"><div class="dk">To Address</div><div class="dv mono">{xfer.to_address}</div></div>
    <div class="detail-row"><div class="dk">Amount</div><div class="dv">{xfer.amount} {xfer.asset}</div></div>
    <div class="detail-row"><div class="dk">Blockchain TX Hash</div><div class="dv {'hi' if tx else 'mono'}">{tx or "-"}</div></div>
    <div class="detail-row"><div class="dk">Etherscan URL</div><div class="dv {'hi' if explorer else 'mono'}">{f'<a class="url-link" href="{explorer}" target="_blank">{explorer}</a>' if explorer else "-"}</div></div>
    <div class="detail-row"><div class="dk">Block Number</div><div class="dv">{xfer.block_number or "-"}</div></div>
    <div class="detail-row"><div class="dk">Confirmations</div><div class="dv">{xfer.confirmations or "-"}</div></div>
    <div class="detail-row"><div class="dk">Gas Used</div><div class="dv">{xfer.gas_used or "-"}</div></div>
    <div class="detail-row"><div class="dk">Approved By</div><div class="dv">{xfer.approved_by or "-"}</div></div>
    <div class="detail-row"><div class="dk">Approved At</div><div class="dv">{xfer.approved_at or "-"}</div></div>
    <div class="detail-row"><div class="dk">Broadcasted At</div><div class="dv">{xfer.broadcasted_at or "-"}</div></div>
    <div class="detail-row"><div class="dk">Completed At</div><div class="dv">{xfer.completed_at or "-"}</div></div>
    <div class="detail-row"><div class="dk">Error Message</div><div class="dv">{xfer.error_message or "-"}</div></div>
    <div class="detail-row"><div class="dk">Retry Count</div><div class="dv">{xfer.retry_count}</div></div>
    <div class="detail-row"><div class="dk">Created At (UTC)</div><div class="dv">{xfer.created_at}</div></div>
  </div>
  {f'<div class="bc-box"><div class="bc-title">&#10003; BLOCKCHAIN TRANSACTION CONFIRMED — ETHEREUM MAINNET</div><div class="bc-hash">TX HASH: {tx}</div><div class="bc-url">Verify: <a class="url-link" href="{explorer}" target="_blank">{explorer}</a></div></div>' if tx else ""}
</div>
<div class="actions">
  <button class="btn btn-print" onclick="window.print()">&#128424; Print / Save PDF</button>
  <button class="btn btn-close" onclick="window.close()">&#10005; Close</button>
</div></body></html>"""
            return HTMLResponse(html)

        # Nothing found in any table
        raise HTTPException(status_code=404, detail=f"No record found for ID: {oid}")

    # ── NO order_id → full overview of all PaymentOrders ─────────────
    stmt = select(PaymentOrder).order_by(PaymentOrder.created_at.desc())
    res = await db.execute(stmt)
    orders = list(res.scalars().all())

    completed = [o for o in orders if o.status == OrderStatus.COMPLETED]
    pending   = [o for o in orders if o.status in {OrderStatus.CREATED, OrderStatus.PENDING, OrderStatus.PROCESSING}]
    failed    = [o for o in orders if o.status == OrderStatus.FAILED]
    fiat_total   = sum(float(o.fiat_amount or 0) for o in completed)
    crypto_total = sum(float(o.crypto_amount or 0) for o in completed)

    rows = "".join(
        f"""<tr>
          <td class="hash">{o.external_id or o.id}</td>
          <td><span class="st {o.status.value}">{o.status.value}</span></td>
          <td>{o.provider.value}</td>
          <td>{o.network.value}</td>
          <td>{o.fiat_amount or "-"} {o.fiat_currency or ""}</td>
          <td>{o.crypto_amount or "-"} {o.crypto_currency or ""}</td>
          <td class="hash">{o.user_wallet_address or "-"}</td>
          <td class="hash">{getattr(o,"tx_hash",None) or "-"}</td>
          <td>{o.created_at}</td>
        </tr>"""
        for o in orders
    )

    return HTMLResponse(f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Transactions Report</title><style>{_CSS}</style></head><body>
<div class="sheet">
  <div class="letterhead">
    <div class="lh-left">
      <div class="brand">ALSHUMOOKH GLOBAL BANKING FINANCE &amp; CREDIT</div>
      <h1>Transactions Report</h1>
      <div class="sub">All Payment Orders — Production Gateway</div>
    </div>
    <div class="lh-right">
      <strong>Generated</strong><br>{now_str}<br>
      <strong>Total Orders</strong><br>{len(orders)}
    </div>
  </div>
  <div class="metrics">
    <div class="metric"><span>Total Orders</span><strong>{len(orders)}</strong></div>
    <div class="metric"><span>Completed</span><strong>{len(completed)}</strong></div>
    <div class="metric"><span>Pending</span><strong>{len(pending)}</strong></div>
    <div class="metric"><span>Failed</span><strong>{len(failed)}</strong></div>
    <div class="metric"><span>Fiat Total</span><strong>{round(fiat_total,2)}</strong></div>
    <div class="metric"><span>Crypto Total</span><strong>{round(crypto_total,6)}</strong></div>
  </div>
  <div class="sec-title">All Payment Orders</div>
  <table>
    <thead><tr>
      <th>Reference</th><th>Status</th><th>Provider</th><th>Network</th>
      <th>Fiat</th><th>Crypto</th><th>Wallet</th><th>TX Hash</th><th>Created</th>
    </tr></thead>
    <tbody>{rows}</tbody>
  </table>
</div>
<div class="actions">
  <button class="btn btn-print" onclick="window.print()">&#128424; Print / Save PDF</button>
</div></body></html>""")


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


def _m1job_swift(job: M1TokenizationJob) -> dict:
    """Serialize an M1TokenizationJob as a SWIFT-style record."""
    reference = job.sender_reference or str(job.id)
    return {
        "record_type": "M1_JOB",
        "id": str(job.id),
        "reference": reference,
        "trn": f"M1-{str(job.id).upper()[:18]}",
        "uetr": f"EUR-SIG-{str(job.id).upper()[:12]}",
        "status": job.status,
        "provider": "M1_TOKENIZATION",
        "network": job.network or "ethereum",
        "fiat_amount": str(job.eur_amount) if job.eur_amount else None,
        "fiat_currency": "EUR",
        "crypto_amount": str(job.usdt_amount) if job.usdt_amount else None,
        "crypto_currency": job.raw_data.get("target_asset", "SIG") if isinstance(job.raw_data, dict) else "SIG",
        "sender_name": job.sender_name,
        "sender_reference": job.sender_reference,
        "sender_iban": job.sender_iban,
        "destination_wallet": job.destination_wallet,
        "outbound_transfer_id": job.outbound_transfer_id,
        "fx_rate_eur_usd": str(job.fx_rate_eur_usd) if job.fx_rate_eur_usd else None,
        "usd_amount": str(job.usd_amount) if job.usd_amount else None,
        "payload_id": job.payload_id,
        "error_message": job.error_message,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "updated_at": job.updated_at.isoformat() if job.updated_at else None,
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
    transaction_reference, request_id, idempotency_key,
    sender_reference, M1 job ID.
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

    # ── Search M1TokenizationJob ─────────────────────────────────────────
    m1job_q = await db.execute(
        select(M1TokenizationJob).where(
            or_(
                cast(M1TokenizationJob.id, String).ilike(f"%{q}%"),
                cast(M1TokenizationJob.sender_reference, String).ilike(f"%{q}%"),
                cast(M1TokenizationJob.sender_name, String).ilike(f"%{q}%"),
                cast(M1TokenizationJob.sender_iban, String).ilike(f"%{q}%"),
                cast(M1TokenizationJob.destination_wallet, String).ilike(f"%{q}%"),
                cast(M1TokenizationJob.outbound_transfer_id, String).ilike(f"%{q}%"),
                cast(M1TokenizationJob.payload_id, String).ilike(f"%{q}%"),
            )
        ).order_by(M1TokenizationJob.created_at.desc()).limit(10)
    )
    for job in m1job_q.scalars().all():
        rec = _m1job_swift(job)
        rec["files"] = []
        rec["notes"] = []
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

    elif record_type == "M1_JOB":
        from sqlalchemy import select as sa_select
        result = await db.execute(
            sa_select(M1TokenizationJob).where(
                cast(M1TokenizationJob.id, String) == record_id
            )
        )
        rec = result.scalar_one_or_none()
        if not rec:
            raise HTTPException(status_code=404, detail="M1 tokenization job not found")
        valid_m1 = {s.value for s in M1TokenizationStatus}
        if new_status not in valid_m1:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid status for M1 job. Valid: {sorted(valid_m1)}",
            )
        rec.status = new_status
        await db.commit()
        await log_event(db, "M1_JOB_STATUS_UPDATED", details={
            "job_id": str(rec.id), "new_status": new_status, "updated_by": "admin_swift"
        })
        return {"ok": True, "record_id": record_id, "record_type": record_type, "status": new_status}

    else:
        raise HTTPException(status_code=400, detail="Invalid record_type. Use PAYMENT_ORDER, SETTLEMENT_PAYLOAD or M1_JOB")


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
        # Identity
        "id":                   ot.id,
        "order_id":             ot.order_id,
        "payload_id":           ot.payload_id,
        "tokenization_job_id":  ot.tokenization_job_id,
        # Transfer details
        "network":              ot.network,
        "asset":                ot.asset,
        "amount":               str(ot.amount),
        "to_address":           ot.to_address,
        "from_address":         ot.from_address,
        "contract_address":     ot.contract_address,
        # Blockchain
        "tx_hash":              ot.tx_hash,
        "block_number":         ot.block_number,
        "confirmations":        ot.confirmations,
        "gas_used":             ot.gas_used,
        "explorer_url":         ot.explorer_url,
        # Approval & status
        "status":               ot.status,
        "initiated_by":         ot.initiated_by,
        "approved_by":          ot.approved_by,
        "approved_at":          ot.approved_at.isoformat() if ot.approved_at else None,
        "cancelled_by":         ot.cancelled_by,
        "cancelled_at":         ot.cancelled_at.isoformat() if ot.cancelled_at else None,
        "cancel_reason":        ot.cancel_reason,
        # Notes & errors
        "notes":                ot.notes,
        "error_message":        ot.error_message,
        "retry_count":          ot.retry_count,
        "last_retry_at":        ot.last_retry_at.isoformat() if ot.last_retry_at else None,
        # Webhook
        "callback_url":         ot.callback_url,
        "webhook_sent_at":      ot.webhook_sent_at.isoformat() if ot.webhook_sent_at else None,
        "webhook_status_code":  ot.webhook_status_code,
        # Timestamps
        "created_at":           ot.created_at.isoformat() if ot.created_at else None,
        "updated_at":           ot.updated_at.isoformat() if ot.updated_at else None,
        "broadcasted_at":       ot.broadcasted_at.isoformat() if ot.broadcasted_at else None,
        "completed_at":         ot.completed_at.isoformat() if ot.completed_at else None,
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

    # Confirmation notification is handled by the pending-confirmation monitor.
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


@router.post("/outbound-transfers/{transfer_id}/force-check", tags=["admin-transfers"])
async def force_check_transfer_confirmation(
    transfer_id: str,
    _: AdminKey,
    db: AsyncSession = Depends(get_db),
):
    """
    Manually trigger a blockchain confirmation check for a specific PENDING_CONFIRMATION transfer.
    Useful when the background monitor hasn't updated yet or you want to refresh immediately.
    """
    from app.tasks.transfer_confirmations import check_pending_transfer_confirmations_once
    from app.transfer_service import ethereum_mainnet_client, base_client

    result = await db.execute(
        select(OutboundTransfer).where(OutboundTransfer.id == transfer_id)
    )
    ot = result.scalar_one_or_none()
    if not ot:
        raise HTTPException(status_code=404, detail="Transfer not found")

    if ot.status not in (
        OutboundTransferStatus.PENDING_CONFIRMATION.value,
        OutboundTransferStatus.BROADCASTING.value,
    ):
        raise HTTPException(
            status_code=400,
            detail=f"Transfer status is {ot.status}; only PENDING_CONFIRMATION or BROADCASTING can be force-checked",
        )

    if not ot.tx_hash:
        raise HTTPException(status_code=400, detail="Transfer has no TX hash to check")

    try:
        network = (ot.network or "ethereum").lower()
        if network in {"ethereum", "eth", "erc20"}:
            client = ethereum_mainnet_client()
            explorer_base = "https://etherscan.io/tx/"
        elif network == "base":
            client = base_client()
            explorer_base = "https://basescan.org/tx/"
        else:
            raise HTTPException(status_code=400, detail=f"Unsupported network for check: {network}")

        current_block = int(client.eth.block_number)
        receipt = client.eth.get_transaction_receipt(ot.tx_hash)

        if receipt is None:
            return {
                "transfer_id": transfer_id,
                "tx_hash": ot.tx_hash,
                "status": ot.status,
                "confirmations": 0,
                "message": "Transaction not yet mined — still pending in mempool",
                "current_block": current_block,
            }

        block_number = int(receipt["blockNumber"])
        on_chain_status = int(receipt.get("status", 1))
        gas_used = receipt.get("gasUsed")
        confirmations = max(0, current_block - block_number + 1)
        required = max(1, int(settings.transfer_confirmations_required or 12))

        ot.block_number = block_number
        ot.confirmations = confirmations
        if gas_used is not None:
            ot.gas_used = int(gas_used)
        if not ot.explorer_url:
            ot.explorer_url = f"{explorer_base}{ot.tx_hash}"

        if on_chain_status == 0:
            ot.status = OutboundTransferStatus.FAILED.value
            ot.error_message = "On-chain transaction reverted"
            await db.commit()
            await log_event(db, "OUTBOUND_TRANSFER_CHAIN_FAILED", {
                "transfer_id": ot.id, "tx_hash": ot.tx_hash,
                "block_number": block_number, "confirmations": confirmations,
            }, ot.order_id)
            return {"transfer_id": transfer_id, "status": "FAILED",
                    "message": "Transaction reverted on-chain", "block_number": block_number}

        if confirmations >= required:
            ot.status = OutboundTransferStatus.CONFIRMED.value
            ot.completed_at = datetime.now(timezone.utc)
            ot.error_message = None
            await db.commit()
            await log_event(db, "OUTBOUND_TRANSFER_CONFIRMED", {
                "transfer_id": ot.id, "tx_hash": ot.tx_hash, "asset": ot.asset,
                "network": ot.network, "block_number": block_number,
                "confirmations": confirmations,
            }, ot.order_id)
            return {
                "transfer_id": transfer_id, "status": "CONFIRMED",
                "tx_hash": ot.tx_hash, "block_number": block_number,
                "confirmations": confirmations,
                "explorer_url": ot.explorer_url,
                "message": f"✓ Confirmed with {confirmations} confirmations",
            }
        else:
            await db.commit()
            return {
                "transfer_id": transfer_id, "status": ot.status,
                "tx_hash": ot.tx_hash, "block_number": block_number,
                "confirmations": confirmations, "required": required,
                "message": f"Mined at block {block_number} — waiting for {required - confirmations} more confirmations",
            }

    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Blockchain check failed: {exc}")


@router.post("/outbound-transfers/{transfer_id}/rebroadcast", tags=["admin-transfers"])
async def rebroadcast_stuck_transfer(
    transfer_id: str,
    _: AdminKey,
    db: AsyncSession = Depends(get_db),
):
    """
    Re-broadcast a PENDING_CONFIRMATION transfer that appears stuck in the mempool.
    This re-signs and sends the same transfer with a fresh nonce and gas price.
    Use when the original TX has been stuck for a long time without being mined.
    """
    result = await db.execute(
        select(OutboundTransfer).where(OutboundTransfer.id == transfer_id)
    )
    ot = result.scalar_one_or_none()
    if not ot:
        raise HTTPException(status_code=404, detail="Transfer not found")
    if ot.status != OutboundTransferStatus.PENDING_CONFIRMATION.value:
        raise HTTPException(
            status_code=400,
            detail=f"Transfer status is {ot.status}; only PENDING_CONFIRMATION can be re-broadcast",
        )

    old_hash = ot.tx_hash
    ot.status = OutboundTransferStatus.APPROVED.value
    ot.approved_by = "admin (rebroadcast)"
    ot.approved_at = datetime.now(timezone.utc)
    ot.tx_hash = None
    ot.block_number = None
    ot.confirmations = 0
    ot.error_message = None
    await db.commit()

    try:
        ot = await broadcast_outbound_transfer(db, transfer_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Re-broadcast failed: {exc}")

    await log_event(db, "OUTBOUND_TRANSFER_REBROADCAST", {
        "transfer_id": ot.id, "old_tx_hash": old_hash,
        "new_tx_hash": ot.tx_hash, "network": ot.network,
    }, ot.order_id)

    return {
        **_transfer_dict(ot),
        "old_tx_hash": old_hash,
        "message": f"Re-broadcast successful. New TX: {ot.tx_hash}",
    }


@router.post("/outbound-transfers/{transfer_id}/force-complete", tags=["admin-transfers"])
async def force_complete_transfer(
    transfer_id: str,
    _: AdminKey,
    db: AsyncSession = Depends(get_db),
    payload: dict = Body(default_factory=dict),
):
    """
    Manually force a transfer to CONFIRMED status (admin override).
    Use only when you have independently verified the TX on Etherscan.
    Optionally supply: block_number, confirmations, notes.
    """
    result = await db.execute(
        select(OutboundTransfer).where(OutboundTransfer.id == transfer_id)
    )
    ot = result.scalar_one_or_none()
    if not ot:
        raise HTTPException(status_code=404, detail="Transfer not found")

    ot.status = OutboundTransferStatus.CONFIRMED.value
    ot.completed_at = datetime.now(timezone.utc)
    ot.error_message = None
    if payload.get("block_number"):
        ot.block_number = int(payload["block_number"])
    if payload.get("confirmations"):
        ot.confirmations = int(payload["confirmations"])
    if payload.get("tx_hash"):
        ot.tx_hash = str(payload["tx_hash"])
    if ot.tx_hash and not ot.explorer_url:
        network = (ot.network or "ethereum").lower()
        base = "https://etherscan.io/tx/" if network in {"ethereum", "eth"} else "https://basescan.org/tx/"
        ot.explorer_url = f"{base}{ot.tx_hash}"

    await db.commit()
    await log_event(db, "OUTBOUND_TRANSFER_FORCE_COMPLETED", {
        "transfer_id": ot.id, "tx_hash": ot.tx_hash,
        "force_completed_by": "admin",
        "notes": payload.get("notes", ""),
    }, ot.order_id)

    return {**_transfer_dict(ot), "message": "Transfer manually marked as CONFIRMED"}


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
    """List M1 tokenization jobs with full sender, receiver and blockchain details."""
    q = select(M1TokenizationJob).order_by(M1TokenizationJob.created_at.desc()).limit(limit)
    if status:
        q = q.where(M1TokenizationJob.status == status.upper())
    result = await db.execute(q)
    jobs = result.scalars().all()

    # Bulk-fetch all linked OutboundTransfers in one query
    ot_ids = [j.outbound_transfer_id for j in jobs if j.outbound_transfer_id]
    ot_map: dict = {}
    if ot_ids:
        ot_res = await db.execute(
            select(OutboundTransfer).where(OutboundTransfer.id.in_(ot_ids))
        )
        for ot in ot_res.scalars().all():
            ot_map[ot.id] = ot

    output = []
    for job in jobs:
        ot = ot_map.get(job.outbound_transfer_id) if job.outbound_transfer_id else None
        raw = job.raw_data or {}
        target_asset = str(raw.get("target_asset") or "SIG").upper()

        # Resolve tx_hash & blockchain details from OutboundTransfer
        tx_hash         = (ot.tx_hash        if ot else None) or raw.get("tx_hash")
        block_number    = (ot.block_number    if ot else None)
        confirmations   = (ot.confirmations   if ot else None)
        explorer_url    = (ot.explorer_url    if ot else None)
        contract_address= (ot.contract_address if ot else None)
        gas_used        = (ot.gas_used        if ot else None)
        approved_by     = (ot.approved_by     if ot else None)
        from_address    = (ot.from_address    if ot else None)
        ot_status       = (ot.status          if ot else None)

        # Build Etherscan URL if missing
        if tx_hash and not explorer_url:
            net = (job.network or "ethereum").lower()
            if net in ("ethereum", "eth", "erc20"):
                explorer_url = f"https://etherscan.io/tx/{tx_hash}"
            elif net in ("base",):
                explorer_url = f"https://basescan.org/tx/{tx_hash}"
            elif net in ("tron", "trx", "trc20"):
                explorer_url = f"https://tronscan.org/#/transaction/{tx_hash}"

        output.append({
            # ── Identity ──────────────────────────────────────────────────
            "id": job.id,
            "payload_id": job.payload_id,
            "outbound_transfer_id": job.outbound_transfer_id,
            # ── Sender ────────────────────────────────────────────────────
            "sender_reference": job.sender_reference,
            "sender_name": job.sender_name,
            "sender_iban": job.sender_iban,
            "sender_bank": raw.get("sender_bank") or raw.get("bank_name"),
            # ── Conversion ────────────────────────────────────────────────
            "eur_amount": str(job.eur_amount),
            "fx_rate": str(job.fx_rate_eur_usd) if job.fx_rate_eur_usd else None,
            "fx_rate_eur_usd": str(job.fx_rate_eur_usd) if job.fx_rate_eur_usd else None,
            "fx_provider": job.fx_provider,
            "usd_amount": str(job.usd_amount) if job.usd_amount else None,
            "usdt_amount": str(job.usdt_amount) if job.usdt_amount else None,
            "target_asset": target_asset,
            # ── Receiver / Blockchain ─────────────────────────────────────
            "network": job.network,
            "receiver_wallet": job.destination_wallet,
            "destination_wallet": job.destination_wallet,
            "operator_wallet": from_address,
            "tx_hash": tx_hash,
            "block_number": block_number,
            "confirmations": confirmations,
            "explorer_url": explorer_url,
            "contract_address": contract_address,
            "gas_used": gas_used,
            # ── Status ────────────────────────────────────────────────────
            "status": job.status,
            "outbound_status": ot_status,
            "approved_by": approved_by,
            "error_message": job.error_message,
            "notes": job.notes,
            # ── Timestamps ───────────────────────────────────────────────
            "created_at": job.created_at.isoformat() if job.created_at else None,
            "updated_at": job.updated_at.isoformat() if job.updated_at else None,
            "completed_at": job.completed_at.isoformat() if job.completed_at else None,
            # ── Raw ───────────────────────────────────────────────────────
            "raw_data": raw,
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

    # Allow "__treasury__" as shorthand for the configured treasury address
    if destination == "__treasury__":
        destination = (
            (settings.eth_treasury_address or "").strip()
            or (settings.treasury_wallet or "").strip()
            or ""
        )

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
        raw_data={"target_asset": str(body.get("target_asset") or "SIG").strip().upper()},
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
            override_asset=body.get("target_asset"),
            processed_by="admin",
            force=bool(body.get("force", False)),
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


@router.post("/tokenization-jobs/{job_id}/route-provider", tags=["admin-tokenization"])
async def route_tokenization_job_to_provider(
    job_id: str,
    request: Request,
    _: AdminKey,
    db: AsyncSession = Depends(get_db),
):
    """Route a tokenization job's EUR payload to an external liquidity provider (MoonPay, Circle, Stripe)."""
    result = await db.execute(
        select(M1TokenizationJob).where(M1TokenizationJob.id == job_id)
    )
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Tokenization job not found")

    body: dict = {}
    try:
        body = await request.json()
    except Exception:
        pass

    provider = str(body.get("provider") or "").lower().strip()
    allowed_providers = {"moonpay", "circle", "stripe"}
    if provider not in allowed_providers:
        raise HTTPException(status_code=400, detail=f"Provider must be one of: {', '.join(allowed_providers)}")

    eur_amount = float(job.eur_amount) if job.eur_amount else 0.0

    await log_event(
        db,
        "M1_JOB_ROUTED_TO_PROVIDER",
        {
            "job_id": job.id,
            "provider": provider,
            "eur_amount": str(job.eur_amount),
            "sender_reference": job.sender_reference,
            "sender_name": job.sender_name,
            "status": job.status,
        },
        None,
    )

    return {
        "routed": True,
        "job_id": job_id,
        "provider": provider,
        "eur_amount": eur_amount,
        "message": f"EUR {eur_amount:,.2f} payload queued for routing to {provider.upper()}. Integration pending activation.",
        "next_step": f"Connect {provider.upper()} API credentials in settings to enable automatic routing.",
    }


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


# ══════════════════════════════════════════════════════════════════════════════
# NOWPayments Integration Endpoints
# ══════════════════════════════════════════════════════════════════════════════

from app import nowpayments_service as nps


class CreatePaymentBody(BaseModel):
    price_amount: float
    price_currency: str = "usd"
    pay_currency: str = "usdterc20"
    order_id: str | None = None
    order_description: str | None = None
    ipn_callback_url: str | None = None
    success_url: str | None = None
    cancel_url: str | None = None
    is_fixed_rate: bool = False
    is_fee_paid_by_user: bool = False


class CreateInvoiceBody(BaseModel):
    price_amount: float
    price_currency: str = "usd"
    order_id: str | None = None
    order_description: str | None = None
    ipn_callback_url: str | None = None
    success_url: str | None = None
    cancel_url: str | None = None


class EstimateBody(BaseModel):
    amount: float
    currency_from: str
    currency_to: str


class PayoutWithdrawal(BaseModel):
    address: str
    currency: str
    amount: float
    ipn_callback_url: str | None = None


class CreatePayoutBody(BaseModel):
    withdrawals: list[PayoutWithdrawal]


def _np_require_key() -> None:
    """Raise 503 with a human-readable message when the API key is not configured."""
    if not settings.nowpayments_api_key:
        raise HTTPException(
            status_code=503,
            detail="NOWPAYMENTS_API_KEY is not configured. Add it to your Render environment variables and redeploy.",
        )


@router.get("/nowpayments/status")
async def nowpayments_api_status(_: AdminKey):
    """Check NOWPayments API availability and configuration."""
    configured = bool(settings.nowpayments_api_key)
    if not configured:
        # Return early without calling external API — JS will show the config warning
        return {"configured": False, "api_status": None, "supported_currencies_count": 0}
    try:
        status_data = await nps.get_status()
        currencies = await nps.get_currencies()
        return {
            "configured": True,
            "api_status": status_data,
            "supported_currencies_count": len(currencies),
        }
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"NOWPayments API error: {exc}")


@router.get("/nowpayments/currencies")
async def nowpayments_currencies(_: AdminKey):
    """Return list of supported currencies from NOWPayments."""
    _np_require_key()
    try:
        return {"currencies": await nps.get_currencies()}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.post("/nowpayments/estimate")
async def nowpayments_estimate(body: EstimateBody, _: AdminKey):
    """Estimate how much currency_to the user receives for amount of currency_from."""
    _np_require_key()
    try:
        result = await nps.get_estimate(body.amount, body.currency_from, body.currency_to)
        return result
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.post("/nowpayments/create-payment")
async def nowpayments_create_payment(body: CreatePaymentBody, _: AdminKey):
    """
    Create a crypto payment invoice.
    Returns: pay_address, payment_id, payment_status, pay_amount, pay_currency, etc.
    """
    _np_require_key()
    try:
        result = await nps.create_payment(
            price_amount=body.price_amount,
            price_currency=body.price_currency,
            pay_currency=body.pay_currency,
            order_id=body.order_id,
            order_description=body.order_description,
            ipn_callback_url=body.ipn_callback_url,
            success_url=body.success_url,
            cancel_url=body.cancel_url,
            is_fixed_rate=body.is_fixed_rate,
            is_fee_paid_by_user=body.is_fee_paid_by_user,
        )
        return result
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.post("/nowpayments/create-invoice")
async def nowpayments_create_invoice(body: CreateInvoiceBody, _: AdminKey):
    """
    Create a hosted invoice page that the client opens to pay.
    Returns: invoice_url, id, token_id, order_id, order_description, etc.
    """
    _np_require_key()
    try:
        result = await nps.create_invoice(
            price_amount=body.price_amount,
            price_currency=body.price_currency,
            order_id=body.order_id,
            order_description=body.order_description,
            ipn_callback_url=body.ipn_callback_url,
            success_url=body.success_url,
            cancel_url=body.cancel_url,
        )
        return result
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.get("/nowpayments/payment/{payment_id}")
async def nowpayments_payment_status(payment_id: str, _: AdminKey):
    """Get current status and details of a payment by its ID."""
    _np_require_key()
    try:
        return await nps.get_payment_status(payment_id)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.get("/nowpayments/payments")
async def nowpayments_list_payments(
    _: AdminKey,
    limit: int = 20,
    page: int = 0,
    sort_by: str = "created_at",
    order_by: str = "desc",
):
    """List all NOWPayments payments with pagination."""
    _np_require_key()
    try:
        return await nps.list_payments(limit=limit, page=page, sort_by=sort_by, order_by=order_by)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.post("/nowpayments/create-payout")
async def nowpayments_create_payout(body: CreatePayoutBody, _: AdminKey):
    """
    Create a mass payout to multiple crypto addresses in a single call.
    Requires Payouts API enabled on your NOWPayments account.
    """
    _np_require_key()
    try:
        withdrawals = [w.model_dump(exclude_none=True) for w in body.withdrawals]
        result = await nps.create_payout(withdrawals)
        return result
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.get("/nowpayments/payout/{payout_id}")
async def nowpayments_payout_status(payout_id: str, _: AdminKey):
    """Get status of a mass payout batch by ID."""
    _np_require_key()
    try:
        return await nps.get_payout_status(payout_id)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.post("/nowpayments/ipn-webhook", include_in_schema=False)
async def nowpayments_ipn_webhook(request: Request):
    """
    NOWPayments IPN (Instant Payment Notification) webhook.
    Verifies HMAC-SHA512 signature then processes payment status update.
    """
    import logging
    _logger = logging.getLogger("nowpayments.ipn")

    raw_body = await request.body()
    signature = request.headers.get("x-nowpayments-sig", "")

    if not nps.verify_ipn_signature(raw_body, signature):
        _logger.warning("NOWPayments IPN: invalid signature")
        raise HTTPException(status_code=400, detail="Invalid IPN signature")

    try:
        body = __import__("json").loads(raw_body)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    internal_status = nps.parse_ipn_status(body)
    payment_id = body.get("payment_id", "unknown")
    order_id = body.get("order_id", "")
    pay_amount = body.get("actually_paid", body.get("pay_amount", 0))
    pay_currency = body.get("pay_currency", "")

    _logger.info(
        "NOWPayments IPN: payment_id=%s order_id=%s status=%s amount=%s %s",
        payment_id, order_id, internal_status, pay_amount, pay_currency,
    )

    # TODO: persist IPN events to database / trigger settlement logic here
    return {"received": True, "payment_id": payment_id, "status": internal_status}
