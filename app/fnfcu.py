from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit_service import log_event
from app.auth import hash_api_key
from app.config import get_settings
from app.database import get_db
from app.models import ApiClient, ExternalPayload, PayloadVerificationStatus
from app.payload_service import payload_sha256
from app.request_utils import get_client_ip


router = APIRouter(tags=["fnfcu-cash-transfer-v1"])
settings = get_settings()

REQUIRED_TRANSFER_FIELDS = (
    "TransferRequestID",
    "SendingName",
    "SendingAccount",
    "ReceivingName",
    "ReceivingAccount",
    "Amount",
    "ReceivingCurrency",
    "SendingCurrency",
)


def _client_ip(request: Request) -> str | None:
    return get_client_ip(request)


def _safe_decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, ValueError):
        return None


def _fingerprint(value: str | None) -> str | None:
    cleaned = str(value or "").strip()
    if not cleaned:
        return None
    return hashlib.sha256(cleaned.encode("utf-8")).hexdigest()


def _redact_fnfcu_payload(payload: dict[str, Any]) -> dict[str, Any]:
    redacted = json.loads(json.dumps(payload, default=str))
    details = redacted.get("Details")
    if isinstance(details, dict) and details.get("authToken"):
        details["authTokenFingerprint"] = _fingerprint(str(details.get("authToken")))
        details["authToken"] = "[REDACTED]"
    return redacted


def _fnfcu_response(ep: ExternalPayload, request_id: str, idempotent: bool = False) -> dict[str, Any]:
    parsed = ep.parsed_payload or {}
    transfer = parsed.get("fnfcu_transfer") if isinstance(parsed, dict) else {}
    return {
        "status": "received",
        "stage": "accepted",
        "transfer_request_id": ep.transaction_reference,
        "payload_id": ep.id,
        "verification_status": ep.verification_status,
        "beneficiary": (transfer or {}).get("receiving_name") or "ALSHUMOOKH",
        "amount": str(ep.amount) if ep.amount is not None else None,
        "currency": ep.asset,
        "request_id": request_id,
        "idempotent": idempotent,
        "message": "FNFCU CashTransfer.v1 request received and queued for operations review.",
    }


async def _require_api_client(
    request: Request,
    db: AsyncSession,
    x_api_key: str | None,
) -> ApiClient:
    key_hash = hash_api_key(x_api_key or "")
    result = await db.execute(select(ApiClient).where(ApiClient.api_key_hash == key_hash))
    client: ApiClient | None = result.scalar_one_or_none()
    request_id = getattr(request.state, "request_id", None)

    if not client or not client.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "invalid_api_key", "message": "API key is invalid or inactive"},
        )

    request_ip = _client_ip(request)
    if client.allowed_ips and request_ip not in client.allowed_ips:
        await log_event(
            db,
            "FNFCU_REJECTED_AUTH",
            {"error": "ip_not_allowed", "client_name": client.name},
            client_id=client.id,
            endpoint=request.url.path,
            method=request.method,
            ip=request_ip,
            user_agent=request.headers.get("user-agent"),
            status_code=403,
            request_id=request_id,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "ip_not_allowed", "message": "Client IP is not allowed for this API client"},
        )

    request.state.client_id = client.id
    request.state.client_name = client.name
    return client


def _validate_and_normalize(payload: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    details = payload.get("Details")
    transfer = payload.get("CashTransfer.v1")
    if not isinstance(details, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "invalid_payload", "message": "Details object is required"},
        )
    if not isinstance(transfer, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "invalid_payload", "message": "CashTransfer.v1 object is required"},
        )

    missing = [field for field in REQUIRED_TRANSFER_FIELDS if not str(transfer.get(field) or "").strip()]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "missing_fields", "fields": missing},
        )

    amount = _safe_decimal(transfer.get("Amount"))
    if amount is None or amount <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "invalid_amount", "message": "Amount must be a positive decimal value"},
        )

    receiving_name = str(transfer.get("ReceivingName") or "").strip()
    review_flags: list[str] = []
    if "ALSHUMOOKH" not in receiving_name.upper().replace(" ", ""):
        review_flags.append("beneficiary_name_requires_review")

    return {
        "schema": "FNFCU CashTransfer.v1",
        "transaction_reference": str(transfer.get("TransferRequestID") or "").strip(),
        "amount": str(amount),
        "asset": str(transfer.get("ReceivingCurrency") or transfer.get("SendingCurrency") or "").upper().strip(),
        "network": "fnfcu-rtgs",
        "settlement_type": "fnfcu_cash_transfer_v1",
        "sender_account": str(transfer.get("SendingAccount") or "").strip(),
        "receiver_account": str(transfer.get("ReceivingAccount") or "").strip(),
        "fnfcu_transfer": {
            "sending_name": str(transfer.get("SendingName") or "").strip(),
            "sending_account": str(transfer.get("SendingAccount") or "").strip(),
            "sending_institution": str(transfer.get("SendingInstitution") or "").strip(),
            "sending_currency": str(transfer.get("SendingCurrency") or "").upper().strip(),
            "receiving_name": receiving_name,
            "receiving_account": str(transfer.get("ReceivingAccount") or "").strip(),
            "receiving_institution": str(transfer.get("ReceivingInstitution") or "").strip(),
            "receiving_currency": str(transfer.get("ReceivingCurrency") or "").upper().strip(),
            "datetime": str(transfer.get("Datetime") or "").strip(),
            "description": str(transfer.get("Description") or "").strip(),
            "method": str(transfer.get("method") or "").strip(),
            "purpose": str(transfer.get("purpose") or "").strip(),
            "source": str(transfer.get("source") or "").strip(),
        },
        "details": {
            "transaction_url": str(details.get("transactionUrl") or "").strip(),
            "account_name": str(details.get("account_name") or "").strip(),
            "account_signatory": str(details.get("account_signatory") or "").strip(),
            "account_number": str(details.get("account_number") or "").strip(),
            "current_balance": str(details.get("currentbalance") or "").strip(),
            "from_currency": str(details.get("fromcurrency") or "").upper().strip(),
            "auth_token_fingerprint": _fingerprint(str(details.get("authToken") or "")),
        },
        "review_flags": review_flags,
    }, review_flags


@router.post("/transfer-request", status_code=status.HTTP_202_ACCEPTED)
async def receive_fnfcu_transfer_request(
    request: Request,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    if not x_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "missing_api_key", "message": "X-API-Key header is required"},
        )
    if not idempotency_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "missing_idempotency_key", "message": "Idempotency-Key header is required"},
        )

    client = await _require_api_client(request, db, x_api_key)
    request_id = getattr(request.state, "request_id", None) or str(uuid.uuid4())
    storage_idempotency_key = f"fnfcu:{idempotency_key}"

    dup_result = await db.execute(
        select(ExternalPayload).where(
            ExternalPayload.api_client_id == client.id,
            ExternalPayload.idempotency_key == storage_idempotency_key,
        )
    )
    existing: ExternalPayload | None = dup_result.scalar_one_or_none()
    if existing:
        return _fnfcu_response(existing, request_id, idempotent=True)

    raw_body = await request.body()
    try:
        payload = json.loads(raw_body.decode("utf-8", errors="replace"))
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "invalid_json", "message": "Request body must be valid JSON"},
        ) from exc

    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "invalid_payload", "message": "JSON root must be an object"},
        )

    details = payload.get("Details") if isinstance(payload.get("Details"), dict) else {}
    expected_token = str(getattr(settings, "fnfcu_auth_token", "") or "").strip()
    provided_token = str(details.get("authToken") or "").strip()
    token_verified = False
    review_flags: list[str] = []
    if expected_token:
        token_verified = bool(provided_token) and hmac.compare_digest(provided_token, expected_token)
        if not token_verified:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"error": "invalid_fnfcu_auth_token", "message": "Details.authToken is invalid"},
            )
    elif provided_token:
        review_flags.append("fnfcu_auth_token_received_without_server_reference")

    normalized, validation_flags = _validate_and_normalize(payload)
    review_flags.extend(validation_flags)
    if expected_token:
        normalized["details"]["auth_token_verified"] = token_verified
    else:
        normalized["details"]["auth_token_verified"] = None

    redacted_payload = _redact_fnfcu_payload(payload)
    safe_headers = {
        key: value
        for key, value in request.headers.items()
        if key.lower() not in {"x-api-key", "authorization", "cookie"}
    }

    review_priority = "HIGH" if review_flags else "NORMAL"
    hold_reason = "; ".join(review_flags) if review_flags else None
    verification_status = (
        PayloadVerificationStatus.MANUAL_REVIEW.value
        if review_flags
        else PayloadVerificationStatus.RECEIVED.value
    )
    security_level = "api_key_only+fnfcu_auth_token" if token_verified else "api_key_only"

    ep = ExternalPayload(
        id=str(uuid.uuid4()),
        api_client_id=client.id,
        client_ip=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
        request_id=request_id,
        idempotency_key=storage_idempotency_key,
        raw_payload=json.dumps(redacted_payload, ensure_ascii=False, default=str),
        pretty_payload=json.dumps(redacted_payload, indent=2, ensure_ascii=False, default=str),
        headers_json=safe_headers,
        parsed_payload=normalized,
        transaction_reference=normalized["transaction_reference"],
        sender_wallet=normalized["sender_account"],
        receiver_wallet=normalized["receiver_account"],
        amount=_safe_decimal(normalized["amount"]),
        asset=normalized["asset"],
        network_name=normalized["network"],
        settlement_type=normalized["settlement_type"],
        payload_hash=payload_sha256(raw_body),
        parsing_status="OK",
        verification_status=verification_status,
        security_level=security_level,
        auth_method="api_key",
        review_priority=review_priority,
        hold_reason=hold_reason,
    )

    db.add(ep)
    await db.commit()
    await db.refresh(ep)

    await log_event(
        db,
        "FNFCU_TRANSFER_REQUEST_RECEIVED",
        {
            "payload_id": ep.id,
            "transfer_request_id": ep.transaction_reference,
            "client_name": client.name,
            "currency": ep.asset,
            "review_flags": review_flags,
        },
        client_id=client.id,
        endpoint=request.url.path,
        method=request.method,
        ip=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
        status_code=status.HTTP_202_ACCEPTED,
        request_id=request_id,
    )

    return _fnfcu_response(ep, request_id)


@router.get("/transfers", status_code=status.HTTP_200_OK)
async def list_fnfcu_transfers(
    request: Request,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    db: AsyncSession = Depends(get_db),
    limit: int = 50,
) -> dict[str, Any]:
    client = await _require_api_client(request, db, x_api_key)
    query = (
        select(ExternalPayload)
        .where(
            ExternalPayload.api_client_id == client.id,
            ExternalPayload.settlement_type == "fnfcu_cash_transfer_v1",
        )
        .order_by(desc(ExternalPayload.created_at))
        .limit(min(max(limit, 1), 200))
    )
    result = await db.execute(query)
    transfers = result.scalars().all()
    return {
        "count": len(transfers),
        "transfers": [
            _fnfcu_response(ep, getattr(request.state, "request_id", None) or "", idempotent=False)
            for ep in transfers
        ],
    }


@router.get("/transfer/{transfer_id}", status_code=status.HTTP_200_OK)
async def get_fnfcu_transfer(
    transfer_id: str,
    request: Request,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    client = await _require_api_client(request, db, x_api_key)
    result = await db.execute(
        select(ExternalPayload).where(
            ExternalPayload.api_client_id == client.id,
            ExternalPayload.settlement_type == "fnfcu_cash_transfer_v1",
            (
                (ExternalPayload.id == transfer_id)
                | (ExternalPayload.transaction_reference == transfer_id)
            ),
        )
    )
    ep: ExternalPayload | None = result.scalar_one_or_none()
    if not ep:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"error": "transfer_not_found"})
    return _fnfcu_response(ep, getattr(request.state, "request_id", None) or "")


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/v1/cash-transfer-request
# FNFCU Cash Transfer Request API — Receiver Integration Guide V1.0
# Accepts the standard envelope format: schema_version / type / message_id
# ─────────────────────────────────────────────────────────────────────────────

ALSHUMOOKH_RECEIVER_PROFILE = {
    "receiver_institution": "ALSHUMOOKH GLOBAL BANKING FINANCE & CREDIT",
    "supported_currencies": ["USD", "EUR"],
    "required_payload_fields": ["receiver_wallet_address", "network"],
    "supported_networks": ["ethereum", "base", "tron"],
    "settlement_asset": "USDT",
    "endpoint": "https://api.alshumookh-pay.com/api/v1/cash-transfer-request",
    "schema_version": "1.0",
}


def _standard_success_response(ep: ExternalPayload, request_id: str, idempotent: bool = False) -> dict:
    """Standard FNFCU success acknowledgement as per Section 10.1."""
    return {
        "status": "success",
        "acknowledged": True,
        "message": "Validated and received. Transfer request queued for settlement review.",
        "receiver_reference": ep.id,
        "idempotency_key": ep.idempotency_key,
        "payload_id": ep.id,
        "transaction_reference": ep.transaction_reference,
        "amount": str(ep.amount) if ep.amount else None,
        "currency": ep.asset,
        "idempotent": idempotent,
        "request_id": request_id,
    }


@router.get("/cash-transfer-request/profile", status_code=status.HTTP_200_OK)
async def fnfcu_receiver_profile() -> dict:
    """Return ALSHUMOOKH Receiver Profile — shared with FNFCU for integration setup."""
    return ALSHUMOOKH_RECEIVER_PROFILE


@router.post("/cash-transfer-request", status_code=status.HTTP_202_ACCEPTED)
async def receive_fnfcu_standard_transfer(
    request: Request,
    authorization: str | None = Header(default=None, alias="Authorization"),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Receive a Cash Transfer Request from FNFCU using the standard envelope
    defined in their Integration Guide V1.0.

    Authentication: Bearer token via Authorization header OR X-API-Key header.
    Idempotency:    Idempotency-Key header is required.
    Format:         application/json with schema_version=1.0
    """
    request_id = getattr(request.state, "request_id", None) or str(uuid.uuid4())

    # ── 1. Require Idempotency-Key ───────────────────────────────────────────
    if not idempotency_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "status": "error",
                "acknowledged": False,
                "error": {
                    "code": "MISSING_FIELD",
                    "message": "Idempotency-Key header is required",
                    "details": {"field": "Idempotency-Key", "expected": "string", "received": "null"},
                },
            },
        )

    # ── 2. Authenticate via Bearer token or API key ──────────────────────────
    bearer_token = None
    if authorization and authorization.lower().startswith("bearer "):
        bearer_token = authorization.split(" ", 1)[1].strip()

    effective_key = bearer_token or x_api_key
    if not effective_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "status": "error",
                "acknowledged": False,
                "error": {"code": "AUTH_FAILED", "message": "Authorization header (Bearer) or X-API-Key is required"},
            },
        )

    client = await _require_api_client(request, db, effective_key)

    # ── 3. Idempotency check ─────────────────────────────────────────────────
    storage_key = f"fnfcu-std:{idempotency_key}"
    dup = await db.execute(
        select(ExternalPayload).where(
            ExternalPayload.api_client_id == client.id,
            ExternalPayload.idempotency_key == storage_key,
        )
    )
    existing: ExternalPayload | None = dup.scalar_one_or_none()
    if existing:
        return _standard_success_response(existing, request_id, idempotent=True)

    # ── 4. Parse body ────────────────────────────────────────────────────────
    raw_body = await request.body()
    try:
        payload = json.loads(raw_body.decode("utf-8", errors="replace"))
    except json.JSONDecodeError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"status": "error", "acknowledged": False, "error": {"code": "TYPE_MISMATCH", "message": "Request body must be valid JSON"}},
        )

    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"status": "error", "acknowledged": False, "error": {"code": "TYPE_MISMATCH", "message": "JSON root must be an object"}},
        )

    # ── 5. Validate envelope required fields ─────────────────────────────────
    schema_version = str(payload.get("schema_version") or "").strip()
    msg_type       = str(payload.get("type") or "").strip()
    message_id     = str(payload.get("message_id") or "").strip()
    created_at_raw = str(payload.get("created_at") or "").strip()
    parties        = payload.get("parties") or {}
    amounts        = payload.get("amounts") or {}
    purpose        = payload.get("purpose") or {}
    recv_specific  = (payload.get("payload") or {}).get("receiver_specific") or {}

    missing = []
    if not schema_version:   missing.append("schema_version")
    if not msg_type:         missing.append("type")
    if not message_id:       missing.append("message_id")
    if not created_at_raw:   missing.append("created_at")
    if not parties.get("sender"):   missing.append("parties.sender")
    if not parties.get("receiver"): missing.append("parties.receiver")
    if not amounts.get("amount"):   missing.append("amounts.amount")
    if not amounts.get("currency"): missing.append("amounts.currency")

    if missing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "status": "error",
                "acknowledged": False,
                "error": {"code": "MISSING_FIELD", "message": "Required envelope fields are missing", "details": {"fields": missing}},
            },
        )

    # ── 6. Validate amount ───────────────────────────────────────────────────
    amount = _safe_decimal(amounts.get("amount"))
    if amount is None or amount <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "status": "error",
                "acknowledged": False,
                "error": {"code": "INVALID_AMOUNT", "message": "amounts.amount must be a positive decimal string", "details": {"field": "amounts.amount", "received": amounts.get("amount")}},
            },
        )

    # ── 7. Validate timestamp ────────────────────────────────────────────────
    try:
        datetime.fromisoformat(created_at_raw.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "status": "error",
                "acknowledged": False,
                "error": {"code": "INVALID_DATETIME", "message": "created_at must be ISO-8601 format", "details": {"field": "created_at", "received": created_at_raw}},
            },
        )

    # ── 8. Extract receiver_specific fields ──────────────────────────────────
    receiver_wallet = str(recv_specific.get("receiver_wallet_address") or "").strip() or None
    network         = str(recv_specific.get("network") or "ethereum").strip().lower()
    routing_code    = str(recv_specific.get("routing_code") or "").strip() or None

    sender   = parties.get("sender") or {}
    receiver = parties.get("receiver") or {}

    review_flags: list[str] = []
    if msg_type != "cash_transfer.request":
        review_flags.append(f"unexpected_message_type:{msg_type}")
    if not receiver_wallet:
        review_flags.append("receiver_wallet_address_missing_in_payload")

    # ── 9. Build normalized parsed payload ───────────────────────────────────
    normalized = {
        "schema": "FNFCU CashTransfer Standard V1.0",
        "schema_version": schema_version,
        "message_type": msg_type,
        "message_id": message_id,
        "correlation_id": str(payload.get("correlation_id") or "").strip() or None,
        "created_at": created_at_raw,
        "source": payload.get("source") or {},
        "sender": {
            "name": str(sender.get("name") or "").strip(),
            "account": str(sender.get("account") or "").strip(),
            "institution": str(sender.get("institution") or "").strip(),
        },
        "receiver": {
            "name": str(receiver.get("name") or "").strip(),
            "account": str(receiver.get("account") or "").strip(),
            "institution": str(receiver.get("institution") or "").strip(),
        },
        "amount": str(amount),
        "currency": str(amounts.get("currency") or "").upper().strip(),
        "purpose": {
            "category": str((purpose or {}).get("category") or "").strip(),
            "description": str((purpose or {}).get("description") or "").strip(),
            "source_of_funds": str((purpose or {}).get("source_of_funds") or "").strip(),
        },
        "receiver_specific": recv_specific,
        "receiver_wallet": receiver_wallet,
        "network": network,
        "routing_code": routing_code,
        "review_flags": review_flags,
    }

    # ── 10. Persist ──────────────────────────────────────────────────────────
    safe_headers = {k: v for k, v in request.headers.items() if k.lower() not in {"authorization", "x-api-key", "cookie"}}
    review_priority     = "HIGH" if review_flags else "NORMAL"
    hold_reason         = "; ".join(review_flags) if review_flags else None
    verification_status = (
        PayloadVerificationStatus.MANUAL_REVIEW.value if review_flags
        else PayloadVerificationStatus.RECEIVED.value
    )

    ep = ExternalPayload(
        id=str(uuid.uuid4()),
        api_client_id=client.id,
        client_ip=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
        request_id=request_id,
        idempotency_key=storage_key,
        raw_payload=raw_body.decode("utf-8", errors="replace"),
        pretty_payload=json.dumps(payload, indent=2, ensure_ascii=False, default=str),
        headers_json=safe_headers,
        parsed_payload=normalized,
        transaction_reference=message_id,
        sender_wallet=normalized["sender"]["account"],
        receiver_wallet=receiver_wallet,
        amount=amount,
        asset=normalized["currency"],
        network_name=network,
        settlement_type="fnfcu_standard_v1",
        payload_hash=payload_sha256(raw_body),
        parsing_status="OK",
        verification_status=verification_status,
        security_level="bearer_token" if bearer_token else "api_key_only",
        auth_method="bearer" if bearer_token else "api_key",
        review_priority=review_priority,
        hold_reason=hold_reason,
    )

    db.add(ep)
    await db.commit()
    await db.refresh(ep)

    await log_event(
        db,
        "FNFCU_STANDARD_TRANSFER_RECEIVED",
        {
            "payload_id": ep.id,
            "message_id": message_id,
            "client_name": client.name,
            "amount": str(amount),
            "currency": normalized["currency"],
            "network": network,
            "review_flags": review_flags,
        },
        client_id=client.id,
        endpoint=request.url.path,
        method=request.method,
        ip=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
        status_code=status.HTTP_202_ACCEPTED,
        request_id=request_id,
    )

    return _standard_success_response(ep, request_id)
