"""
payloads.py
───────────
Settlement receiver pipeline:
  POST /api/v1/payloads/ingest          — external counterparty endpoint
  GET  /api/v1/admin/payloads           — admin list
  GET  /api/v1/admin/payloads/{id}      — admin detail
  POST /api/v1/admin/payloads/{id}/verify
  POST /api/v1/admin/payloads/{id}/mark-manual-review
"""
from __future__ import annotations

import json
import logging
import time

logger = logging.getLogger(__name__)
import uuid
import hmac
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import httpx
from fastapi import APIRouter, Body, Depends, Header, HTTPException, Request, status
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit_service import log_event
from app.auth import hash_api_key, require_admin_api_key, verify_settlement_access_token
from app.database import get_db
from app.deps import AdminKey
from app.models import ApiClient, ExternalPayload, OutboundTransferStatus, PayloadVerificationStatus, TransactionFile
from app.transfer_service import create_outbound_transfer
from app.payload_service import (
    detect_network,
    decrypt_payload_jwe,
    normalize_payload,
    payload_sha256,
    verify_payload_jws,
    verify_payload_hmac,
    verify_tx_on_chain,
)
from app.request_utils import get_client_ip
from app.schemas import PayloadReviewAction

log = logging.getLogger(__name__)

# ── Public ingest router ─────────────────────────────────────────────────────
ingest_router = APIRouter(prefix="/payloads", tags=["settlement-payloads"])

# ── Admin payload router ─────────────────────────────────────────────────────
admin_payloads_router = APIRouter(prefix="/admin/payloads", tags=["admin-payloads"])


SETTLEMENT_PAYLOAD_SCHEMA = {
    "schema_name": "ALSHUMOOKH Settlement Payload v1",
    "endpoint": "/api/v1/payloads/ingest",
    "content_type": "application/json",
    "required_headers": {
        "Idempotency-Key": "Unique request key per payload",
        "X-API-Key": "Client API key, unless OAuth2 Bearer is required",
    },
    "recommended_headers": {
        "Authorization": "Bearer <OAuth2 access token from /api/v1/oauth/token>",
        "X-Timestamp": "Unix timestamp in seconds",
        "X-Signature": "HMAC-SHA256 over X-Timestamp + '.' + exact wire body",
        "X-JWS-Signature": "Detached compact JWS containing payload_hash=sha256(plaintext body)",
        "X-Client-Cert-Fingerprint": "mTLS certificate SHA-256 fingerprint forwarded by proxy",
    },
    "required_fields_for_automatic_verification": [
        "transaction_reference",
        "tx_hash",
        "sender_wallet",
        "receiver_wallet",
        "amount",
        "asset",
        "network",
        "token_contract",
    ],
    "supported_networks": ["ethereum", "base", "tron-placeholder"],
    "field_aliases": {
        "transaction_reference": ["transaction_reference", "transaction_id", "txRef", "reference", "ref", "transactionCode"],
        "tx_hash": ["tx_hash", "transaction_hash", "hash", "blockchain_hash", "txid"],
        "sender_wallet": ["sender_wallet", "from_wallet", "from", "source_wallet", "origin_wallet"],
        "receiver_wallet": ["receiver_wallet", "to_wallet", "to", "destination_wallet", "beneficiary_wallet"],
        "amount": ["amount", "value", "token_amount", "transfer_amount", "settlement_amount"],
        "asset": ["asset", "currency", "token", "symbol", "crypto_currency"],
        "network": ["network", "chain", "blockchain", "protocol"],
    },
    "example_payload": {
        "transaction_reference": "W2W-TEST-0001",
        "tx_hash": "0x...",
        "sender_wallet": "0xSenderWallet",
        "receiver_wallet": "0xReceiverMasterWallet",
        "amount": "100.00",
        "asset": "USDC",
        "network": "ethereum",
        "token_contract": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
        "timestamp": "2026-05-10T00:00:00Z",
        "settlement_type": "wallet_to_wallet",
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _client_ip(request: Request) -> str | None:
    return get_client_ip(request)


def _safe_decimal(value: Any) -> Decimal | None:
    try:
        if value is None or value == "":
            return None
        return Decimal(str(value))
    except Exception:
        return None


def _payload_response(ep: ExternalPayload) -> dict:
    return {
        "payload_id": ep.id,
        "transaction_reference": ep.transaction_reference,
        "tx_hash": ep.tx_hash,
        "sender_wallet": ep.sender_wallet,
        "receiver_wallet": ep.receiver_wallet,
        "amount": str(ep.amount) if ep.amount is not None else None,
        "asset": ep.asset,
        "network": ep.network_name,
        "verification_status": ep.verification_status,
        "security_level": ep.security_level,
        "auth_method": ep.auth_method,
        "jws_verified": ep.jws_verified,
        "jwe_decrypted": ep.jwe_decrypted,
        "mtls_verified": ep.mtls_verified,
        "parsing_status": ep.parsing_status,
        "client_ip": ep.client_ip,
        "api_client_id": ep.api_client_id,
        "review_priority": ep.review_priority,
        "review_decision": ep.review_decision,
        "reviewed_by": ep.reviewed_by,
        "reviewed_at": ep.reviewed_at.isoformat() if ep.reviewed_at else None,
        "hold_reason": ep.hold_reason,
        "created_at": ep.created_at.isoformat() if ep.created_at else None,
    }


def _payload_detail(ep: ExternalPayload) -> dict:
    base = _payload_response(ep)
    base.update({
        "raw_payload": ep.raw_payload,
        "pretty_payload": ep.pretty_payload,
        "parsed_payload": ep.parsed_payload,
        "headers": ep.headers_json,
        "blockchain_result": ep.blockchain_result,
        "block_number": ep.block_number,
        "confirmations": ep.confirmations,
        "explorer_url": ep.explorer_url,
        "verified_at": ep.verified_at.isoformat() if ep.verified_at else None,
        "error_message": ep.error_message,
        "token_contract": ep.token_contract,
        "settlement_type": ep.settlement_type,
        "authorization_code": ep.authorization_code,
        "callback_url": ep.callback_url,
        "payload_hash": ep.payload_hash,
        "auth_method": ep.auth_method,
        "jws_verified": ep.jws_verified,
        "jwe_decrypted": ep.jwe_decrypted,
        "mtls_verified": ep.mtls_verified,
        "review_priority": ep.review_priority,
        "review_decision": ep.review_decision,
        "review_note": ep.review_note,
        "reviewed_by": ep.reviewed_by,
        "reviewed_at": ep.reviewed_at.isoformat() if ep.reviewed_at else None,
        "hold_reason": ep.hold_reason,
        "updated_at": ep.updated_at.isoformat() if ep.updated_at else None,
    })
    return base


def _admin_actor(request: Request) -> str:
    return (
        request.headers.get("x-admin-actor")
        or request.headers.get("x-admin-user")
        or "admin_api_key"
    )


async def _load_payload(db: AsyncSession, payload_id: str) -> ExternalPayload:
    result = await db.execute(
        select(ExternalPayload).where(ExternalPayload.id == payload_id)
    )
    ep: ExternalPayload | None = result.scalar_one_or_none()
    if not ep:
        raise HTTPException(status_code=404, detail="Payload not found")
    return ep


async def _log_payload_review(
    db: AsyncSession,
    request: Request,
    ep: ExternalPayload,
    *,
    event_type: str,
    action: str,
    actor: str,
    note: str | None = None,
) -> None:
    await log_event(
        db,
        event_type,
        {
            "payload_id": ep.id,
            "action": action,
            "review_priority": ep.review_priority,
            "review_decision": ep.review_decision,
            "verification_status": ep.verification_status,
            "reviewed_by": actor,
            "note": note,
            "hold_reason": ep.hold_reason,
        },
        None,
        client_id=ep.api_client_id,
        endpoint=request.url.path,
        method=request.method,
        ip=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
        request_id=getattr(request.state, "request_id", None),
    )


async def _log_ingest_rejection(
    db: AsyncSession,
    request: Request,
    *,
    event_type: str,
    request_id: str,
    error_code: str,
    message: str,
    client: ApiClient | None = None,
    idempotency_key: str | None = None,
) -> None:
    await log_event(
        db,
        event_type,
        {
            "error_code": error_code,
            "message": message,
            "idempotency_key": idempotency_key,
            "client_name": getattr(client, "name", None),
        },
        None,
        client_id=getattr(client, "id", None),
        endpoint=request.url.path,
        method=request.method,
        ip=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
        status_code=None,
        request_id=request_id,
        error_message=message,
    )


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/v1/payloads/ingest
# ─────────────────────────────────────────────────────────────────────────────

@ingest_router.get("/schema", status_code=status.HTTP_200_OK)
async def settlement_payload_schema():
    """Public technical schema shared with counterparties. No secrets exposed."""
    return SETTLEMENT_PAYLOAD_SCHEMA


@ingest_router.post("/ingest", status_code=status.HTTP_200_OK)
async def ingest_payload(
    request: Request,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    authorization: str | None = Header(default=None, alias="Authorization"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    x_timestamp: str | None = Header(default=None, alias="X-Timestamp"),
    x_signature: str | None = Header(default=None, alias="X-Signature"),
    x_jws_signature: str | None = Header(default=None, alias="X-JWS-Signature"),
    x_client_cert_fingerprint: str | None = Header(default=None, alias="X-Client-Cert-Fingerprint"),
    db: AsyncSession = Depends(get_db),
):
    """
    Receive a structured or partially structured JSON payload from a
    counterparty. Validates API key + idempotency key (required).
    Validates HMAC signature when the client has hmac_required=True.
    """
    request_id = getattr(request.state, "request_id", None) or str(uuid.uuid4())
    received_at = datetime.now(tz=timezone.utc)

    # ── 1. Require API key or OAuth2 bearer token ───────────────────────────
    bearer_token = None
    if authorization and authorization.lower().startswith("bearer "):
        bearer_token = authorization.split(" ", 1)[1].strip()

    if not x_api_key and not bearer_token:
        await _log_ingest_rejection(
            db,
            request,
            event_type="PAYLOAD_REJECTED_AUTH",
            request_id=request_id,
            error_code="missing_credentials",
            message="X-API-Key or OAuth2 Bearer token is required",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": "missing_credentials",
                "message": "X-API-Key or OAuth2 Bearer token is required",
            },
        )

    # ── 2. Look up API client ────────────────────────────────────────────────
    auth_method = "api_key"
    if bearer_token:
        claims = verify_settlement_access_token(bearer_token)
        result = await db.execute(
            select(ApiClient).where(ApiClient.id == str(claims.get("sub") or ""))
        )
        auth_method = "oauth2_bearer"
    else:
        key_hash = hash_api_key(x_api_key or "")
        result = await db.execute(
            select(ApiClient).where(ApiClient.api_key_hash == key_hash)
        )
    client: ApiClient | None = result.scalar_one_or_none()

    if not client or not client.is_active:
        await _log_ingest_rejection(
            db,
            request,
            event_type="PAYLOAD_REJECTED_AUTH",
            request_id=request_id,
            error_code="invalid_api_key",
            message="API key is invalid or inactive",
            idempotency_key=idempotency_key,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "invalid_api_key", "message": "API key is invalid or inactive"},
        )

    if getattr(client, "oauth_required", False) and auth_method != "oauth2_bearer":
        await _log_ingest_rejection(
            db,
            request,
            event_type="PAYLOAD_REJECTED_AUTH",
            request_id=request_id,
            error_code="oauth_required",
            message="This client requires OAuth2 Bearer authentication",
            client=client,
            idempotency_key=idempotency_key,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "oauth_required", "message": "This client requires OAuth2 Bearer authentication"},
        )

    request_ip = _client_ip(request)
    if client.allowed_ips and request_ip not in client.allowed_ips:
        await _log_ingest_rejection(
            db,
            request,
            event_type="PAYLOAD_REJECTED_AUTH",
            request_id=request_id,
            error_code="ip_not_allowed",
            message="Client IP is not allowed for this API client",
            client=client,
            idempotency_key=idempotency_key,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "ip_not_allowed", "message": "Client IP is not allowed for this API client"},
        )

    # ── 3. Require Idempotency-Key ───────────────────────────────────────────
    if not idempotency_key:
        await _log_ingest_rejection(
            db,
            request,
            event_type="PAYLOAD_REJECTED_VALIDATION",
            request_id=request_id,
            error_code="missing_idempotency_key",
            message="Idempotency-Key header is required",
            client=client,
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "missing_idempotency_key", "message": "Idempotency-Key header is required"},
        )

    # ── 4. Check for duplicate idempotency key (same client) ────────────────
    dup_result = await db.execute(
        select(ExternalPayload).where(
            ExternalPayload.api_client_id == client.id,
            ExternalPayload.idempotency_key == idempotency_key,
        )
    )
    existing: ExternalPayload | None = dup_result.scalar_one_or_none()
    if existing:
        # Return original response idempotently
        return {
            "status": "payload_received",
            "payload_id": existing.id,
            "transaction_reference": existing.transaction_reference,
            "parsed": existing.parsing_status == "OK",
            "verification_status": existing.verification_status,
            "request_id": request_id,
            "idempotent": True,
            "message": "Duplicate Idempotency-Key — returning original response",
        }

    # ── 5. Read raw body ─────────────────────────────────────────────────────
    wire_body: bytes = await request.body()
    raw_body: bytes = wire_body
    wire_payload_hash = payload_sha256(wire_body)
    jwe_decrypted = False
    jws_verified = False
    mtls_verified = False

    # ── 5a. mTLS-ready fingerprint verification ─────────────────────────────
    forwarded_fingerprint = (
        x_client_cert_fingerprint
        or request.headers.get("x-forwarded-tls-client-cert-fingerprint")
        or request.headers.get("x-ssl-client-fingerprint")
    )
    expected_fingerprint = getattr(client, "mtls_cert_fingerprint", None)
    if expected_fingerprint:
        normalized_expected = expected_fingerprint.replace(":", "").lower().strip()
        normalized_seen = str(forwarded_fingerprint or "").replace(":", "").lower().strip()
        mtls_verified = bool(normalized_seen) and hmac.compare_digest(normalized_expected, normalized_seen)
    if getattr(client, "mtls_required", False) and not mtls_verified:
        await _log_ingest_rejection(
            db,
            request,
            event_type="PAYLOAD_REJECTED_AUTH",
            request_id=request_id,
            error_code="mtls_required",
            message="Valid client certificate fingerprint is required",
            client=client,
            idempotency_key=idempotency_key,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "mtls_required", "message": "Valid client certificate fingerprint is required"},
        )

    # ── 5b. Optional JWE envelope decryption ────────────────────────────────
    content_type = str(request.headers.get("content-type") or "").lower()
    should_decrypt_jwe = getattr(client, "jwe_required", False) or "jwe" in content_type
    if should_decrypt_jwe:
        try:
            raw_body, _jwe_meta = decrypt_payload_jwe(wire_body)
            jwe_decrypted = True
        except Exception as exc:
            await _log_ingest_rejection(
                db,
                request,
                event_type="PAYLOAD_REJECTED_VALIDATION",
                request_id=request_id,
                error_code="invalid_jwe",
                message=str(exc),
                client=client,
                idempotency_key=idempotency_key,
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": "invalid_jwe", "message": str(exc)},
            ) from exc

    # ── 6. Timestamp staleness check (if provided) ──────────────────────────
    if x_timestamp:
        try:
            ts = int(x_timestamp)
            age = abs(time.time() - ts)
            if age > 300:
                await _log_ingest_rejection(
                    db,
                    request,
                    event_type="PAYLOAD_REJECTED_AUTH",
                    request_id=request_id,
                    error_code="timestamp_expired",
                    message="X-Timestamp is older than 5 minutes",
                    client=client,
                    idempotency_key=idempotency_key,
                )
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail={"error": "timestamp_expired", "message": "X-Timestamp is older than 5 minutes"},
                )
        except ValueError:
            pass  # non-integer timestamp — ignore unless HMAC is required

    # ── 6a. JWS verification ────────────────────────────────────────────────
    if getattr(client, "jws_required", False) or x_jws_signature:
        jws_valid, jws_error = verify_payload_jws(
            raw_body=raw_body,
            compact_jws=x_jws_signature,
            public_key_pem=getattr(client, "jws_public_key_pem", None),
        )
        if not jws_valid:
            await _log_ingest_rejection(
                db,
                request,
                event_type="PAYLOAD_REJECTED_AUTH",
                request_id=request_id,
                error_code="invalid_jws",
                message=jws_error or "JWS signature verification failed",
                client=client,
                idempotency_key=idempotency_key,
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"error": "invalid_jws", "message": jws_error or "JWS signature verification failed"},
            )
        jws_verified = True

    # ── 7. HMAC verification ─────────────────────────────────────────────────
    security_level = "api_key_only" if auth_method == "api_key" else "oauth2_bearer"
    hmac_required: bool = getattr(client, "hmac_required", False)

    if hmac_required:
        if not x_timestamp or not x_signature:
            await _log_ingest_rejection(
                db,
                request,
                event_type="PAYLOAD_REJECTED_AUTH",
                request_id=request_id,
                error_code="hmac_required",
                message="This client requires X-Timestamp and X-Signature headers",
                client=client,
                idempotency_key=idempotency_key,
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={
                    "error": "hmac_required",
                    "message": "This client requires X-Timestamp and X-Signature headers",
                },
            )
        hmac_valid = verify_payload_hmac(
            raw_body=wire_body,
            x_timestamp=x_timestamp,
            x_signature=x_signature,
            hmac_secret=client.hmac_secret,
        )
        if not hmac_valid:
            await _log_ingest_rejection(
                db,
                request,
                event_type="PAYLOAD_REJECTED_AUTH",
                request_id=request_id,
                error_code="invalid_hmac",
                message="HMAC signature verification failed",
                client=client,
                idempotency_key=idempotency_key,
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"error": "invalid_hmac", "message": "HMAC signature verification failed"},
            )
        security_level = "hmac_verified"
    elif x_timestamp and x_signature:
        # Opportunistically verify HMAC even if not required
        hmac_valid = verify_payload_hmac(
            raw_body=wire_body,
            x_timestamp=x_timestamp,
            x_signature=x_signature,
            hmac_secret=client.hmac_secret,
        )
        security_level = "hmac_verified" if hmac_valid else security_level

    if jws_verified:
        security_level = f"{security_level}+jws"
    if jwe_decrypted:
        security_level = f"{security_level}+jwe"
    if mtls_verified:
        security_level = f"{security_level}+mtls"

    # ── 8. Parse the JSON body ───────────────────────────────────────────────
    parsed_ok = False
    raw_dict: dict = {}
    parse_error: str | None = None

    if raw_body:
        try:
            raw_dict = json.loads(raw_body.decode("utf-8", errors="replace"))
            if not isinstance(raw_dict, dict):
                raw_dict = {"_root": raw_dict}
            parsed_ok = True
        except json.JSONDecodeError as exc:
            parse_error = f"JSON parse error: {exc}"
    else:
        parse_error = "Empty body"

    # ── 9. Normalize known fields ────────────────────────────────────────────
    normalized: dict = {}
    if parsed_ok:
        normalized = normalize_payload(raw_dict)

    # ── 10. Store headers (safe subset) ─────────────────────────────────────
    safe_headers = {
        k: v for k, v in request.headers.items()
        if k.lower() not in {
            "x-api-key", "authorization", "x-signature", "x-jws-signature", "cookie",
        }
    }

    # ── 11. Build and persist ExternalPayload ────────────────────────────────
    pretty_json: str | None = None
    if parsed_ok:
        try:
            pretty_json = json.dumps(raw_dict, indent=2, ensure_ascii=False)
        except Exception:
            pass

    tx_hash = str(normalized.get("tx_hash") or "").strip() or None
    transaction_reference = str(normalized.get("transaction_reference") or "").strip() or None
    network_raw = str(normalized.get("network") or "").strip() or None
    network_detected = detect_network(raw_dict, normalized) or network_raw

    # Determine initial verification status
    if not parsed_ok:
        verification_status = PayloadVerificationStatus.RECEIVED.value
        parsing_status = "FAILED"
    elif tx_hash:
        verification_status = PayloadVerificationStatus.ALCHEMY_PENDING.value
        parsing_status = "OK"
    else:
        verification_status = PayloadVerificationStatus.AWAITING_TX_HASH.value
        parsing_status = "OK"

    ep = ExternalPayload(
        id=str(uuid.uuid4()),
        api_client_id=client.id,
        client_ip=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
        request_id=request_id,
        idempotency_key=idempotency_key,
        raw_payload=wire_body.decode("utf-8", errors="replace"),
        pretty_payload=pretty_json,
        headers_json=safe_headers,
        parsed_payload=normalized if parsed_ok else None,
        transaction_reference=transaction_reference,
        tx_hash=tx_hash,
        sender_wallet=str(normalized.get("sender_wallet") or "").strip() or None,
        receiver_wallet=str(normalized.get("receiver_wallet") or "").strip() or None,
        amount=_safe_decimal(normalized.get("amount")),
        asset=str(normalized.get("asset") or "").upper().strip() or None,
        network_name=network_detected,
        token_contract=str(normalized.get("token_contract") or "").lower().strip() or None,
        callback_url=str(normalized.get("callback_url") or "").strip() or None,
        settlement_type=str(normalized.get("settlement_type") or "").strip() or None,
        authorization_code=str(normalized.get("authorization_code") or "").strip() or None,
        payload_hash=payload_sha256(raw_body),
        parsing_status=parsing_status,
        verification_status=verification_status,
        security_level=security_level,
        auth_method=auth_method,
        jws_verified=jws_verified,
        jwe_decrypted=jwe_decrypted,
        mtls_verified=mtls_verified,
        error_message=parse_error,
    )

    db.add(ep)
    await db.commit()
    await db.refresh(ep)

    await log_event(
        db,
        "PAYLOAD_INGESTED",
        {
            "payload_id": ep.id,
            "client_id": client.id,
            "client_name": client.name,
            "transaction_reference": transaction_reference,
            "tx_hash": tx_hash,
            "network": network_detected,
            "parsing_status": parsing_status,
            "verification_status": verification_status,
            "security_level": security_level,
            "auth_method": auth_method,
            "wire_payload_hash": wire_payload_hash,
            "payload_hash": ep.payload_hash,
            "jws_verified": jws_verified,
            "jwe_decrypted": jwe_decrypted,
            "mtls_verified": mtls_verified,
        },
        None,
        client_id=client.id,
    )

    # ── 12. Return response ──────────────────────────────────────────────────
    if not parsed_ok:
        return {
            "status": "payload_received_unparsed",
            "payload_id": ep.id,
            "parsed": False,
            "request_id": request_id,
            "message": "Payload stored but requires manual review",
        }

    return {
        "status": "payload_received",
        "payload_id": ep.id,
        "transaction_reference": transaction_reference,
        "parsed": True,
        "request_id": request_id,
        "verification_status": verification_status,
    }


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/v1/admin/payloads
# ─────────────────────────────────────────────────────────────────────────────

@admin_payloads_router.get("", status_code=status.HTTP_200_OK)
async def list_payloads(
    _admin: AdminKey,
    db: AsyncSession = Depends(get_db),
    limit: int = 2000,
    offset: int = 0,
    verification_status: str | None = None,
):
    """List all settlement payloads (admin only)."""
    query = select(ExternalPayload).order_by(desc(ExternalPayload.created_at))

    if verification_status:
        query = query.where(ExternalPayload.verification_status == verification_status.upper())

    query = query.limit(min(limit, 200)).offset(offset)
    result = await db.execute(query)
    payloads = result.scalars().all()

    return {
        "payloads": [_payload_response(ep) for ep in payloads],
        "count": len(payloads),
        "offset": offset,
        "limit": limit,
    }


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/v1/admin/payloads/{payload_id}
# ─────────────────────────────────────────────────────────────────────────────

@admin_payloads_router.get("/{payload_id}", status_code=status.HTTP_200_OK)
async def get_payload(
    payload_id: str,
    _admin: AdminKey,
    db: AsyncSession = Depends(get_db),
):
    """Get full payload detail (admin only)."""
    ep = await _load_payload(db, payload_id)
    return _payload_detail(ep)


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/v1/admin/payloads/{payload_id}/verify
# ─────────────────────────────────────────────────────────────────────────────

@admin_payloads_router.post("/{payload_id}/verify", status_code=status.HTTP_200_OK)
async def verify_payload(
    request: Request,
    payload_id: str,
    _admin: AdminKey,
    db: AsyncSession = Depends(get_db),
):
    """
    Trigger or re-trigger Alchemy/RPC verification for a payload that
    has a tx_hash. Updates the payload status in-place.
    """
    ep = await _load_payload(db, payload_id)

    if not ep.tx_hash:
        ep.verification_status = PayloadVerificationStatus.AWAITING_TX_HASH.value
        ep.error_message = "No tx_hash available — cannot verify"
        await db.commit()
        return {
            "payload_id": ep.id,
            "verification_status": ep.verification_status,
            "message": "No tx_hash present — marked as AWAITING_TX_HASH",
        }

    # Set to pending while we verify
    ep.verification_status = PayloadVerificationStatus.ALCHEMY_PENDING.value
    await db.commit()

    network = ep.network_name or "ethereum"
    blockchain_result = await verify_tx_on_chain(
        tx_hash=ep.tx_hash,
        network=network,
        expected_receiver=ep.receiver_wallet,
        expected_sender=ep.sender_wallet,
        expected_amount=ep.amount,
        expected_contract=ep.token_contract,
        expected_asset=ep.asset,
    )

    ep.blockchain_result = blockchain_result
    ep.block_number = blockchain_result.get("block_number")
    ep.confirmations = blockchain_result.get("confirmations")
    ep.explorer_url = blockchain_result.get("explorer_url")

    if blockchain_result.get("verified"):
        ep.verification_status = PayloadVerificationStatus.ALCHEMY_VERIFIED.value
        if (ep.confirmations or 0) >= 6:
            ep.verification_status = PayloadVerificationStatus.ON_CHAIN_CONFIRMED.value
        ep.verified_at = datetime.now(tz=timezone.utc)
        ep.error_message = None

        # Update on-chain fields from result if we got richer data
        on_chain = blockchain_result.get("on_chain") or {}
        if on_chain.get("amount") and ep.amount is None:
            try:
                ep.amount = Decimal(on_chain["amount"])
            except Exception:
                pass
        if on_chain.get("asset") and ep.asset is None:
            ep.asset = on_chain["asset"]
    else:
        chain_status = blockchain_result.get("status", "FAILED")
        if chain_status in {"TX_NOT_FOUND", "RECEIPT_PENDING"}:
            ep.verification_status = PayloadVerificationStatus.ALCHEMY_PENDING.value
        elif chain_status == "RPC_NOT_CONFIGURED":
            ep.verification_status = PayloadVerificationStatus.MANUAL_REVIEW.value
        elif chain_status == "TRON_PLACEHOLDER":
            ep.verification_status = PayloadVerificationStatus.MANUAL_REVIEW.value
        else:
            ep.verification_status = PayloadVerificationStatus.FAILED.value
        ep.error_message = blockchain_result.get("error")

    await db.commit()
    await db.refresh(ep)

    await log_event(
        db,
        "PAYLOAD_VERIFY_TRIGGERED",
        {
            "payload_id": ep.id,
            "tx_hash": ep.tx_hash,
            "network": network,
            "verification_status": ep.verification_status,
            "blockchain_result": blockchain_result,
        },
        None,
        client_id=ep.api_client_id,
        endpoint=request.url.path,
        method=request.method,
        ip=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
        request_id=getattr(request.state, "request_id", None),
    )

    return {
        "payload_id": ep.id,
        "tx_hash": ep.tx_hash,
        "verification_status": ep.verification_status,
        "blockchain_result": blockchain_result,
        "explorer_url": ep.explorer_url,
        "verified_at": ep.verified_at.isoformat() if ep.verified_at else None,
    }


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/v1/admin/payloads/{payload_id}/mark-manual-review
# ─────────────────────────────────────────────────────────────────────────────

@admin_payloads_router.post("/{payload_id}/mark-manual-review", status_code=status.HTTP_200_OK)
async def mark_manual_review(
    request: Request,
    payload_id: str,
    _admin: AdminKey,
    db: AsyncSession = Depends(get_db),
):
    """Flag a payload for manual review."""
    ep = await _load_payload(db, payload_id)
    ep.verification_status = PayloadVerificationStatus.MANUAL_REVIEW.value
    ep.review_decision = "MANUAL_REVIEW"
    ep.reviewed_by = _admin_actor(request)
    ep.reviewed_at = datetime.now(tz=timezone.utc)
    await db.commit()

    await _log_payload_review(
        db,
        request,
        ep,
        event_type="PAYLOAD_MARKED_MANUAL_REVIEW",
        action="MANUAL_REVIEW",
        actor=ep.reviewed_by or "admin_api_key",
    )

    return {
        "payload_id": ep.id,
        "verification_status": ep.verification_status,
        "message": "Payload flagged for manual review",
    }


# ─────────────────────────────────────────────────────────────────────────────
# DELETE /api/v1/admin/payloads/{payload_id}
# ─────────────────────────────────────────────────────────────────────────────

@admin_payloads_router.delete("/{payload_id}", status_code=status.HTTP_200_OK)
async def delete_payload(
    request: Request,
    payload_id: str,
    _admin: AdminKey,
    db: AsyncSession = Depends(get_db),
):
    """Permanently delete a settlement payload from the database."""
    ep = await _load_payload(db, payload_id)
    actor = _admin_actor(request)

    await log_event(
        db,
        "PAYLOAD_DELETED",
        {
            "payload_id": ep.id,
            "verification_status": ep.verification_status,
            "amount": str(ep.amount) if ep.amount else None,
            "deleted_by": actor,
        },
        client_id=ep.api_client_id,
        endpoint=request.url.path,
        method=request.method,
        ip=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
        request_id=getattr(request.state, "request_id", None),
    )

    await db.delete(ep)
    await db.commit()

    return {
        "payload_id": payload_id,
        "deleted": True,
        "message": "Settlement payload permanently deleted.",
        "deleted_by": actor,
    }


@admin_payloads_router.post("/{payload_id}/review", status_code=status.HTTP_200_OK)
async def review_payload(
    request: Request,
    payload_id: str,
    _admin: AdminKey,
    payload: PayloadReviewAction = Body(...),
    db: AsyncSession = Depends(get_db),
):
    """Operational review workflow for settlement payloads."""
    ep = await _load_payload(db, payload_id)
    actor = _admin_actor(request)
    now = datetime.now(tz=timezone.utc)

    if payload.priority:
        ep.review_priority = payload.priority

    if payload.action == "APPROVE":
        ep.review_decision = "APPROVED"
        ep.hold_reason = None
        if ep.verification_status in {
            PayloadVerificationStatus.ON_CHAIN_CONFIRMED.value,
            PayloadVerificationStatus.ALCHEMY_VERIFIED.value,
            PayloadVerificationStatus.RECONCILED.value,
        }:
            ep.verification_status = PayloadVerificationStatus.RECONCILED.value
        else:
            ep.verification_status = PayloadVerificationStatus.MANUAL_REVIEW.value

        # Auto-create outbound transfer if payload has recipient + amount
        if ep.receiver_wallet and ep.amount and ep.amount > 0:
            try:
                network = (ep.network_name or "ethereum").lower()
                asset = (ep.asset or "USDT").upper()
                ot = await create_outbound_transfer(
                    db,
                    to_address=ep.receiver_wallet,
                    amount=ep.amount,
                    network=network,
                    asset=asset,
                    payload_id=ep.id,
                    initiated_by=actor,
                    notes=f"Auto-created from approved payload {ep.id}",
                )
                ot.status = OutboundTransferStatus.AWAITING_APPROVAL.value
                await db.commit()
            except Exception as _ot_err:
                logger.warning("Could not auto-create outbound transfer for payload %s: %s", ep.id, _ot_err)
    elif payload.action == "HOLD":
        ep.review_decision = "ON_HOLD"
        ep.hold_reason = payload.hold_reason
        ep.verification_status = PayloadVerificationStatus.MANUAL_REVIEW.value
    elif payload.action == "REJECT":
        ep.review_decision = "REJECTED"
        ep.hold_reason = None
        ep.verification_status = PayloadVerificationStatus.FAILED.value
    elif payload.action == "RECONCILE":
        ep.review_decision = "RECONCILED"
        ep.hold_reason = None
        ep.verification_status = PayloadVerificationStatus.RECONCILED.value
    elif payload.action == "NOTE":
        ep.review_decision = ep.review_decision or "NOTED"

    if payload.note:
        ep.review_note = payload.note

    ep.reviewed_by = actor
    ep.reviewed_at = now

    await db.commit()
    await db.refresh(ep)

    await _log_payload_review(
        db,
        request,
        ep,
        event_type="PAYLOAD_REVIEW_UPDATED",
        action=payload.action,
        actor=actor,
        note=payload.note,
    )

    return {
        "payload_id": ep.id,
        "verification_status": ep.verification_status,
        "review_priority": ep.review_priority,
        "review_decision": ep.review_decision,
        "reviewed_by": ep.reviewed_by,
        "reviewed_at": ep.reviewed_at.isoformat() if ep.reviewed_at else None,
        "hold_reason": ep.hold_reason,
        "message": f"Payload review action {payload.action} applied",
    }


# ─────────────────────────────────────────────────────────────────────────────
# M1 FUND INBOUND — Receive M1-grouped financial data from external senders
# Endpoint: POST /api/v1/payloads/m1-fund
# ─────────────────────────────────────────────────────────────────────────────

_M1_RECEIVER_ENTITY = "Alshumookh Alraeda Investment LLC"
_M1_RECEIVER_WALLET = "0xBD682cfD8382a90adfDd6745780D3D7959c4d939"
_M1_RECEIVER_IBAN   = "AE960260001015754367301"
_M1_RECEIVER_BIC    = "EBILAEADXXX"
_M1_RECEIVER_BANK   = "Emirates NBD — Sheikh Zayed Road, Dubai, UAE"


@ingest_router.post("/m1-fund", status_code=200, tags=["m1-fund-inbound"])
async def receive_m1_fund(
    request: Request,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    x_sender_id: str | None = Header(default=None, alias="X-Sender-ID"),
    x_idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    db: AsyncSession = Depends(get_db),
):
    """
    Inbound M1 Fund receiver endpoint.

    Accepts M1-grouped financial data (Model 3 JSON) from authorized senders.
    The API key is generated from the ALSHUMOOKH admin dashboard (API Clients section).

    Required header:
      X-API-Key  — Client API key generated from the ALSHUMOOKH dashboard

    Optional headers:
      X-Sender-ID      — Sender organisation identifier (overrides client name)
      Idempotency-Key  — Unique key per submission for deduplication
    """
    received_at = datetime.now(tz=timezone.utc)
    client_ip   = get_client_ip(request)

    # ── 1. Require API key ──────────────────────────────────────────────────
    if not x_api_key:
        raise HTTPException(
            status_code=401,
            detail={"error": "missing_api_key", "message": "X-API-Key header is required"},
        )

    # ── 2. Look up API Client from dashboard (same as ingest endpoint) ──────
    key_hash = hash_api_key(x_api_key.strip())
    client_result = await db.execute(
        select(ApiClient).where(ApiClient.api_key_hash == key_hash)
    )
    api_client: ApiClient | None = client_result.scalar_one_or_none()

    if not api_client or not api_client.is_active:
        raise HTTPException(
            status_code=401,
            detail={"error": "invalid_api_key", "message": "API key is invalid or inactive. Generate a key from the ALSHUMOOKH dashboard."},
        )

    # ── 3. Deduplication check (if Idempotency-Key provided) ────────────────
    if x_idempotency_key:
        dup = await db.execute(
            select(ExternalPayload).where(
                ExternalPayload.api_client_id == api_client.id,
                ExternalPayload.idempotency_key == x_idempotency_key,
                ExternalPayload.settlement_type == "M1_FUND_INBOUND",
            )
        )
        existing = dup.scalar_one_or_none()
        if existing:
            return {
                "status":       "ALREADY_RECEIVED",
                "m1_reference": existing.transaction_reference,
                "fund_id":      existing.id,
                "received_at":  existing.created_at.isoformat() if existing.created_at else None,
                "message":      "This M1 Fund was already received (idempotency key matched).",
            }

    # ── 4. Parse JSON body ──────────────────────────────────────────────────
    try:
        raw_bytes = await request.body()
        raw_str   = raw_bytes.decode("utf-8")
        payload   = json.loads(raw_str)
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail={"error": "invalid_json", "message": f"Request body must be valid JSON: {exc}"},
        )

    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=400,
            detail={"error": "invalid_payload", "message": "Payload must be a JSON object"},
        )

    # ── 5. Generate references ──────────────────────────────────────────────
    fund_id  = str(uuid.uuid4())
    stamp    = received_at.strftime("%Y%m%d-%H%M%S")
    m1_ref   = f"ALSH-M1-{stamp}-{fund_id[:6].upper()}"
    ph       = payload_sha256(raw_str)

    # ── 6. Extract key fields ───────────────────────────────────────────────
    m1_detail    = payload.get("grouped_m1_detail") or {}
    token_info   = payload.get("token") or {}
    payout       = payload.get("payout_structure") or {}
    verification = payload.get("verification") or {}

    raw_eur         = str(m1_detail.get("total_group_value_eur", "") or "").replace(",", "").strip()
    amount_dec      = _safe_decimal(raw_eur)
    sender_id       = (x_sender_id or "").strip() or api_client.name or "UNKNOWN_SENDER"
    receiver_wallet = str(payout.get("receiver_wallet") or _M1_RECEIVER_WALLET)
    tx_hash         = str(verification.get("hash_sha256") or "") or None

    try:
        pretty = json.dumps(payload, indent=2, ensure_ascii=False)
    except Exception:
        pretty = raw_str

    # ── 7. Persist ExternalPayload ──────────────────────────────────────────
    ep = ExternalPayload(
        id=fund_id,
        api_client_id=api_client.id,
        client_ip=client_ip,
        user_agent=request.headers.get("user-agent"),
        request_id=m1_ref,
        idempotency_key=x_idempotency_key,
        raw_payload=raw_str,
        pretty_payload=pretty,
        headers_json={k: v for k, v in request.headers.items()},
        parsed_payload=payload,
        transaction_reference=m1_ref,
        tx_hash=tx_hash,
        sender_wallet=sender_id,
        receiver_wallet=receiver_wallet,
        amount=amount_dec,
        asset="EUR",
        network_name="M1_FUND",
        token_contract=str(token_info.get("contract_address") or "") or None,
        settlement_type="M1_FUND_INBOUND",
        payload_hash=ph,
        parsing_status="PARSED",
        verification_status=PayloadVerificationStatus.RECEIVED.value,
        security_level="api_key_only",
        auth_method="api_key",
        review_priority="HIGH",
    )
    db.add(ep)

    # ── 6. Persist raw file as TransactionFile ──────────────────────────────
    file_bytes = raw_str.encode("utf-8")
    tf = TransactionFile(
        id=str(uuid.uuid4()),
        order_id=None,
        payload_id=fund_id,
        transaction_ref=m1_ref,
        filename=f"m1_fund_{stamp}_{fund_id[:8]}.json",
        content_type="application/json",
        file_data=file_bytes,
        file_size=len(file_bytes),
        description=(
            f"M1 Fund inbound | Ref: {m1_ref} | Client: {api_client.name} | "
            f"Sender: {sender_id} | Amount: {raw_eur or 'N/A'} EUR | Hash: {ph}"
        ),
        uploaded_by=api_client.name or sender_id,
    )
    db.add(tf)

    await db.commit()

    log.info("M1 Fund received | ref=%s | client=%s | sender=%s | amount_eur=%s | ip=%s",
             m1_ref, api_client.name, sender_id, raw_eur or "N/A", client_ip)

    # ── 7. Return receipt ───────────────────────────────────────────────────
    return {
        "status":        "RECEIVED",
        "m1_reference":  m1_ref,
        "fund_id":       fund_id,
        "received_at":   received_at.isoformat(),
        "payload_hash":  ph,
        "receiver": {
            "entity":  _M1_RECEIVER_ENTITY,
            "iban":    _M1_RECEIVER_IBAN,
            "bic":     _M1_RECEIVER_BIC,
            "bank":    _M1_RECEIVER_BANK,
            "wallet":  _M1_RECEIVER_WALLET,
            "network": "Ethereum Mainnet — ERC-20 USDT",
        },
        "acknowledged": {
            "amount_eur":    raw_eur or "NOT_SPECIFIED",
            "token":         token_info.get("symbol", "USDT"),
            "token_network": token_info.get("type", "ERC-20"),
            "contract":      token_info.get("contract_address", "0xdAC17F958D2ee523a2206206994597C13D831ec7"),
        },
        "next_steps": (
            "Your M1 Fund file has been received, logged, and queued for compliance review. "
            "ALSHUMOOKH will contact you at the registered address to confirm tokenization scheduling."
        ),
        "support": "ceo@alshumookhgroup.ae",
        "platform": "https://api.alshumookh-pay.com",
    }
