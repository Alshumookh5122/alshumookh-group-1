"""
partner_dispatch.py
────────────────────
ALSHUMOOKH — Outbound Partner Transfer Dispatcher

Sends wire transfer instructions FROM ALSHUMOOKH TO external partner bank APIs.
Currently supports:
  • Goodwill Global Group  (api.goodwillglobalgroup.com)
  • Generic JSON endpoint  (any partner following a similar schema)

Admin-only endpoint:
  POST /api/v1/admin/partner-transfer   — dispatch outbound transfer to partner API

The response (UETR, TRN, status) is stored in the audit log and returned to the caller.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import APIRouter, Body, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit_service import log_event
from app.database import get_db
from app.deps import AdminKey
from app.request_utils import get_client_ip

log = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/partner-transfer", tags=["partner-dispatch"])

# ─── Known partner endpoints ──────────────────────────────────────────────────

KNOWN_PARTNERS: dict[str, dict] = {
    "goodwill": {
        "name":        "Goodwill Global Group",
        "url":         "https://api.goodwillglobalgroup.com/api/public/v1/transfers",
        "status_url":  "https://api.goodwillglobalgroup.com/api/public/v1/transfers/{uetr}",
        "description": "Cross-border wire transfer via Global Server Funds (GSFDUS33)",
    },
}

# ─── Helpers ──────────────────────────────────────────────────────────────────

def _build_gsf_signature(raw_json: str, secret: str) -> tuple[str, str]:
    """
    Build HMAC-SHA256 signature for Goodwill Global Group (optional signing).
    Signing string: {timestamp}.{raw_json_body}
    Returns (timestamp_str, hex_signature)
    """
    ts = str(int(time.time()))
    base = f"{ts}.{raw_json}"
    sig = hmac.new(secret.encode(), base.encode(), hashlib.sha256).hexdigest()
    return ts, sig


def _admin_actor(request: Request) -> str:
    return (
        request.headers.get("x-admin-actor")
        or request.headers.get("x-admin-user")
        or "admin"
    )


# ─── Main dispatch endpoint ───────────────────────────────────────────────────

@router.post("", status_code=200)
async def dispatch_partner_transfer(
    request: Request,
    _admin: AdminKey,
    body: dict = Body(...),
    db: AsyncSession = Depends(get_db),
):
    """
    POST /api/v1/admin/partner-transfer

    Dispatch an outbound wire transfer from ALSHUMOOKH to an external partner bank API.

    ── Required fields ──────────────────────────────────────────────
    partner          : "goodwill" or any key in KNOWN_PARTNERS, OR omit + set target_url
    sender_bank      : Sending institution name
    sender_swift     : 8 or 11 character BIC
    receiver_bank    : Receiving institution name
    receiver_swift   : 8 or 11 character BIC
    receiver_account : Beneficiary account number
    receiver_name    : Beneficiary name
    amount           : Transfer amount (number > 0)

    ── Optional fields ───────────────────────────────────────────────
    api_key          : Partner API key (defaults to "SANDBOX" if not provided)
    target_url       : Override the partner endpoint URL
    sender_account   : Originating account
    sender_name      : Originator display name
    currency         : ISO 4217 (default: USD)
    purpose_code     : e.g. TRAD, SALA, INTC
    charge_bearer    : SHA, OUR, or BEN
    priority         : NORMAL or URGENT
    transfer_reference: Your own reference (auto-generated if not provided)
    signing_secret   : If set, adds X-GSF-Timestamp + X-GSF-Signature headers
    extra_headers    : Dict of additional headers to include
    note             : Internal note (stored in audit log only)
    """
    actor      = _admin_actor(request)
    client_ip  = get_client_ip(request)
    request_id = getattr(request.state, "request_id", None)

    # ── Resolve partner & target URL ───────────────────────────────────────
    partner_key: str = (body.get("partner") or "goodwill").lower().strip()
    partner_info = KNOWN_PARTNERS.get(partner_key, {})

    target_url: str = (
        (body.get("target_url") or "").strip()
        or partner_info.get("url", "")
    )
    if not target_url:
        raise HTTPException(
            status_code=400,
            detail={
                "error":   "missing_target_url",
                "message": "Provide 'partner' (e.g. 'goodwill') or 'target_url'.",
                "known_partners": list(KNOWN_PARTNERS.keys()),
            },
        )

    # ── Validate required fields ───────────────────────────────────────────
    required = ["sender_bank", "sender_swift", "receiver_bank",
                "receiver_swift", "receiver_account", "receiver_name", "amount"]
    missing = [f for f in required if not body.get(f)]
    if missing:
        raise HTTPException(
            status_code=422,
            detail={"error": "missing_required_fields", "fields": missing},
        )

    amount = body.get("amount")
    try:
        amount = float(amount)
        if amount <= 0:
            raise ValueError
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=422,
            detail={"error": "invalid_amount", "message": "amount must be a number greater than 0"},
        )

    # ── Build outbound payload ─────────────────────────────────────────────
    api_key    = (body.get("api_key") or "SANDBOX").strip()
    is_sandbox = api_key.upper() == "SANDBOX"

    transfer_ref = (
        (body.get("transfer_reference") or "").strip()
        or f"ALSH-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6].upper()}"
    )

    outbound: dict[str, Any] = {
        "api_key":          api_key,
        "sender_bank":      str(body["sender_bank"]).strip(),
        "sender_swift":     str(body["sender_swift"]).strip().upper(),
        "sender_name":      str(body.get("sender_name") or "ALSHUMOOKH GLOBAL").strip(),
        "receiver_bank":    str(body["receiver_bank"]).strip(),
        "receiver_swift":   str(body["receiver_swift"]).strip().upper(),
        "receiver_account": str(body["receiver_account"]).strip(),
        "receiver_name":    str(body["receiver_name"]).strip(),
        "amount":           amount,
        "currency":         str(body.get("currency") or "USD").strip().upper(),
        "transfer_reference": transfer_ref,
    }

    # Optional sender account
    if body.get("sender_account"):
        outbound["sender_account"] = str(body["sender_account"]).strip()

    # Optional extras
    for opt in ("purpose_code", "charge_bearer", "priority"):
        if body.get(opt):
            outbound[opt] = str(body[opt]).strip().upper()

    # ── Build request headers ──────────────────────────────────────────────
    headers: dict[str, str] = {
        "Content-Type": "application/json",
        "Accept":       "application/json",
        "X-App-Request": "True",
        "X-ALSHUMOOKH-Source": "partner-dispatch",
        "X-Request-ID": transfer_ref,
    }

    # Optional request signing (HMAC-SHA256)
    signing_secret: str = (body.get("signing_secret") or "").strip()
    if signing_secret:
        raw_json = json.dumps(outbound, separators=(",", ":"))
        ts, sig  = _build_gsf_signature(raw_json, signing_secret)
        headers["X-GSF-Timestamp"] = ts
        headers["X-GSF-Signature"] = sig
        headers["X-GSF-Key-Id"]    = outbound["sender_swift"]

    # Extra custom headers
    extra_headers: dict = body.get("extra_headers") or {}
    for k, v in extra_headers.items():
        headers[str(k)] = str(v)

    # ── Send request ───────────────────────────────────────────────────────
    delivery_status: str = "PENDING"
    response_status: int | None = None
    response_body:   dict | str = {}
    error_detail:    str = ""
    uetr:            str | None = None
    trn:             str | None = None

    log.info(
        "PARTNER_DISPATCH | actor=%s | partner=%s | url=%s | ref=%s | amount=%.2f %s | sandbox=%s",
        actor, partner_key, target_url, transfer_ref, amount,
        outbound["currency"], is_sandbox,
    )

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(target_url, json=outbound, headers=headers)

        response_status = resp.status_code

        try:
            response_body = resp.json()
        except Exception:
            response_body = resp.text[:3000]

        if resp.status_code < 400:
            delivery_status = "DELIVERED"
            if isinstance(response_body, dict):
                uetr = response_body.get("uetr")
                trn  = response_body.get("trn")
        else:
            delivery_status = "REJECTED"

    except httpx.ConnectError as exc:
        delivery_status = "CONNECTION_ERROR"
        error_detail    = str(exc)[:500]
    except httpx.TimeoutException:
        delivery_status = "TIMEOUT"
        error_detail    = "Request timed out after 30 seconds"
    except Exception as exc:
        delivery_status = "ERROR"
        error_detail    = f"{type(exc).__name__}: {str(exc)[:400]}"

    # ── Audit log ──────────────────────────────────────────────────────────
    await log_event(
        db,
        "PARTNER_TRANSFER_DISPATCHED",
        {
            "partner":           partner_key,
            "partner_name":      partner_info.get("name", partner_key),
            "target_url":        target_url,
            "transfer_reference": transfer_ref,
            "sender_swift":      outbound["sender_swift"],
            "receiver_swift":    outbound["receiver_swift"],
            "receiver_account":  outbound["receiver_account"],
            "amount":            amount,
            "currency":          outbound["currency"],
            "sandbox":           is_sandbox,
            "delivery_status":   delivery_status,
            "http_status":       response_status,
            "uetr":              uetr,
            "trn":               trn,
            "error":             error_detail or None,
            "actor":             actor,
            "note":              body.get("note") or None,
            "signed":            bool(signing_secret),
        },
        endpoint=request.url.path,
        method="POST",
        ip=client_ip,
        status_code=response_status,
        request_id=request_id,
    )

    # ── Return result ──────────────────────────────────────────────────────
    result: dict[str, Any] = {
        "transfer_reference": transfer_ref,
        "partner":            partner_key,
        "partner_name":       partner_info.get("name", partner_key),
        "target_url":         target_url,
        "delivery_status":    delivery_status,
        "http_status":        response_status,
        "sandbox":            is_sandbox,
        "dispatched_by":      actor,
        "dispatched_at":      datetime.now(timezone.utc).isoformat(),
    }

    if uetr:
        result["uetr"] = uetr
    if trn:
        result["trn"] = trn
    if isinstance(response_body, dict):
        result["partner_response"] = response_body
    elif response_body:
        result["partner_response_raw"] = str(response_body)[:1000]
    if error_detail:
        result["error"] = error_detail

    return result


# ─── List known partners ───────────────────────────────────────────────────────

@router.get("/partners", status_code=200)
async def list_known_partners(_admin: AdminKey):
    """
    GET /api/v1/admin/partner-transfer/partners
    List all pre-configured partner bank API endpoints.
    """
    return {
        "partners": [
            {
                "key":         k,
                "name":        v["name"],
                "url":         v["url"],
                "description": v.get("description", ""),
            }
            for k, v in KNOWN_PARTNERS.items()
        ]
    }
