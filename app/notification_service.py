"""
Notification Service — WhatsApp (Twilio) + Webhook callbacks
Handles: payload alerts, transfer status, M1 job notifications.

Required env vars for WhatsApp:
  TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN,
  TWILIO_WHATSAPP_FROM, TWILIO_WHATSAPP_TO
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


# ── WhatsApp via Twilio ───────────────────────────────────────────────────────

def _whatsapp_configured() -> bool:
    return bool(
        settings.twilio_account_sid
        and settings.twilio_auth_token
        and settings.twilio_whatsapp_to
    )


async def send_whatsapp(message: str) -> bool:
    """Send WhatsApp message via Twilio REST API. Returns True on success."""
    if not _whatsapp_configured():
        logger.debug("WhatsApp not configured — skipping")
        return False
    url = (
        f"https://api.twilio.com/2010-04-01/Accounts/"
        f"{settings.twilio_account_sid}/Messages.json"
    )
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                url,
                auth=(settings.twilio_account_sid, settings.twilio_auth_token),
                data={
                    "From": settings.twilio_whatsapp_from,
                    "To":   settings.twilio_whatsapp_to,
                    "Body": message,
                },
            )
            if r.status_code in (200, 201):
                logger.info("WhatsApp notification sent")
                return True
            logger.warning("WhatsApp failed: %s %s", r.status_code, r.text[:200])
            return False
    except Exception as exc:
        logger.error("WhatsApp error: %s", exc)
        return False


# ── Webhook callback helper ───────────────────────────────────────────────────

async def _post_webhook(url: str | None, payload: dict) -> dict | None:
    """POST a JSON webhook to a callback URL. Returns response dict or None."""
    if not url:
        return None
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(url, json=payload)
            return {"status_code": r.status_code, "body": r.text[:500]}
    except Exception as exc:
        logger.warning("Webhook delivery failed to %s: %s", url, exc)
        return {"status_code": 0, "error": str(exc)}


# ── Transfer notifications ────────────────────────────────────────────────────

async def notify_transfer_completed(
    callback_url: str | None,
    transfer_id: str,
    tx_hash: str | None,
    amount: str,
    network: str,
    to_address: str,
    explorer_url: str | None = None,
    asset: str | None = None,
) -> dict | None:
    """Notify (webhook + WhatsApp) when an outbound transfer is confirmed on-chain."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    short_addr = f"{to_address[:10]}...{to_address[-6:]}" if len(to_address) > 16 else to_address
    asset_label = asset or "USDT"

    # WhatsApp
    msg = (
        f"ALSHUMOOKH - Transfer COMPLETED\n\n"
        f"Amount: {amount} {asset_label}\n"
        f"Network: {network.upper()}\n"
        f"To: {short_addr}\n"
        f"TX: {tx_hash or 'N/A'}\n"
        f"Time: {now}"
    )
    await send_whatsapp(msg)

    # Webhook
    return await _post_webhook(callback_url, {
        "event":       "transfer.completed",
        "transfer_id": transfer_id,
        "tx_hash":     tx_hash,
        "amount":      amount,
        "asset":       asset_label,
        "network":     network,
        "to_address":  to_address,
        "explorer_url": explorer_url,
        "timestamp":   datetime.now(timezone.utc).isoformat(),
    })


async def notify_transfer_failed(
    callback_url: str | None,
    transfer_id: str,
    error_message: str,
    amount: str,
    network: str,
) -> dict | None:
    """Notify (webhook + WhatsApp) when an outbound transfer fails."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # WhatsApp
    msg = (
        f"ALSHUMOOKH - Transfer FAILED\n\n"
        f"Transfer ID: {transfer_id[:16]}...\n"
        f"Amount: {amount}\n"
        f"Network: {network.upper()}\n"
        f"Error: {error_message}\n"
        f"Time: {now}\n\n"
        f"Dashboard: https://api.alshumookh-pay.com/dashboard/transfers"
    )
    await send_whatsapp(msg)

    # Webhook
    return await _post_webhook(callback_url, {
        "event":         "transfer.failed",
        "transfer_id":   transfer_id,
        "error_message": error_message,
        "amount":        amount,
        "network":       network,
        "timestamp":     datetime.now(timezone.utc).isoformat(),
    })


# ── M1 Tokenization notifications ─────────────────────────────────────────────

async def notify_m1_job_ready(
    callback_url: str | None,
    job_id: str,
    eur_amount: str,
    usdt_amount: str,
    outbound_transfer_id: str | None = None,
) -> dict | None:
    """Notify when an M1 tokenization job is complete and ready for settlement."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # WhatsApp
    msg = (
        f"ALSHUMOOKH - M1 Job Ready\n\n"
        f"EUR Amount: {eur_amount}\n"
        f"USDT Amount: {usdt_amount}\n"
        f"Transfer ID: {outbound_transfer_id or 'N/A'}\n"
        f"Time: {now}\n\n"
        f"Dashboard: https://api.alshumookh-pay.com/dashboard/tokenization"
    )
    await send_whatsapp(msg)

    # Webhook
    return await _post_webhook(callback_url, {
        "event":                "m1.job.ready",
        "job_id":               job_id,
        "eur_amount":           eur_amount,
        "usdt_amount":          usdt_amount,
        "outbound_transfer_id": outbound_transfer_id,
        "timestamp":            datetime.now(timezone.utc).isoformat(),
    })


# ── Payload notifications ─────────────────────────────────────────────────────

async def notify_payload_received(
    payload_id: str,
    transaction_reference: str | None,
    client_name: str,
    amount: str | None,
    asset: str | None,
    network: str | None,
    tx_hash: str | None,
    verification_status: str,
    client_ip: str | None = None,
) -> None:
    """Alert admin: new payload arrived at ingest endpoint."""
    now      = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    tx_line  = f"TX Hash: {tx_hash}" if tx_hash else "TX Hash: Pending"
    amt_line = f"{amount} {asset or ''}".strip() if amount else "Not specified"
    msg = (
        f"ALSHUMOOKH - New Payload\n\n"
        f"Reference: {transaction_reference or 'N/A'}\n"
        f"Amount: {amt_line}\n"
        f"Network: {(network or 'N/A').upper()}\n"
        f"{tx_line}\n"
        f"Client: {client_name}\n"
        f"Status: {verification_status}\n"
        f"Time: {now}\n\n"
        f"Dashboard: https://api.alshumookh-pay.com/dashboard/payloads"
    )
    await send_whatsapp(msg)


async def notify_payload_approved(
    payload_id: str,
    transaction_reference: str | None,
    client_name: str,
    amount: str | None,
    asset: str | None,
    reviewed_by: str,
) -> None:
    """Alert admin: payload approved for settlement."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    msg = (
        f"ALSHUMOOKH - Payload APPROVED\n\n"
        f"Reference: {transaction_reference or payload_id}\n"
        f"Amount: {amount} {asset or ''}\n"
        f"Client: {client_name}\n"
        f"Approved by: {reviewed_by}\n"
        f"Time: {now}\n\n"
        f"Dashboard: https://api.alshumookh-pay.com/dashboard/payloads"
    )
    await send_whatsapp(msg)


async def notify_payload_verified(
    payload_id: str,
    transaction_reference: str | None,
    tx_hash: str,
    amount: str | None,
    asset: str | None,
    network: str | None,
) -> None:
    """Alert admin: on-chain verification confirmed."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    msg = (
        f"ALSHUMOOKH - On-Chain CONFIRMED\n\n"
        f"Reference: {transaction_reference or payload_id}\n"
        f"Amount: {amount} {asset or ''}\n"
        f"Network: {(network or '').upper()}\n"
        f"TX Hash: {tx_hash}\n"
        f"Status: VERIFIED ON-CHAIN\n"
        f"Time: {now}"
    )
    await send_whatsapp(msg)
