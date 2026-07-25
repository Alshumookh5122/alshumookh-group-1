"""
WhatsApp Notification Service — Twilio REST API
Sends instant WhatsApp alerts to the admin phone on key system events.

Required environment variables on Render:
  TWILIO_ACCOUNT_SID   — Your Twilio Account SID
  TWILIO_AUTH_TOKEN    — Your Twilio Auth Token
  TWILIO_WHATSAPP_FROM — Sender number, e.g. whatsapp:+14155238886 (Twilio sandbox)
                         or your approved WhatsApp Business number
  TWILIO_WHATSAPP_TO   — Admin phone, e.g. whatsapp:+971XXXXXXXXX
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


def _configured() -> bool:
    return bool(
        settings.twilio_account_sid
        and settings.twilio_auth_token
        and settings.twilio_whatsapp_to
    )


async def send_whatsapp(message: str) -> bool:
    """Send a WhatsApp message via Twilio REST API. Returns True on success."""
    if not _configured():
        logger.debug("WhatsApp notifications not configured — skipping")
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
            else:
                logger.warning("WhatsApp failed: %s %s", r.status_code, r.text[:200])
                return False
    except Exception as exc:
        logger.error("WhatsApp error: %s", exc)
        return False


# ── Notification Templates ────────────────────────────────────────────────────

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
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    tx_line   = f"TX Hash: {tx_hash}" if tx_hash else "TX Hash: Pending"
    amt_line  = f"{amount} {asset or ''}".strip() if amount else "Not specified"

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


async def notify_outbound_transfer(
    transfer_id: str,
    to_address: str,
    amount: str,
    asset: str,
    network: str,
    status: str,
) -> None:
    """Alert admin: outbound transfer status change."""
    now  = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    short_addr = f"{to_address[:10]}...{to_address[-6:]}" if len(to_address) > 16 else to_address
    msg = (
        f"ALSHUMOOKH - Outbound Transfer {status}\n\n"
        f"Amount: {amount} {asset}\n"
        f"Network: {network.upper()}\n"
        f"To: {short_addr}\n"
        f"Time: {now}\n\n"
        f"Dashboard: https://api.alshumookh-pay.com/dashboard/transfers"
    )
    await send_whatsapp(msg)
