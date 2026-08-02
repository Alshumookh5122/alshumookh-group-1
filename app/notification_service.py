"""
ALSHUMOOKH — Notification & Webhook Delivery Service

Handles:
  • Internal ops email alerts (SMTP)
  • Outbound webhook delivery to counterparty callback URLs
  • Retry logic with exponential back-off (3 attempts)
  • Full audit trail for every delivery attempt
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import smtplib
import ssl
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


# ─── Internal Ops Notifications ───────────────────────────────────────────────

def notify_ops(subject: str, body: str) -> None:
    """Send an internal ops alert via SMTP (fire-and-forget, never raises)."""
    logger.info("notify_ops subject=%s to=%s", subject, settings.notify_to_email)
    try:
        _send_email(
            to=settings.notify_to_email,
            subject=f"[ALSHUMOOKH OPS] {subject}",
            body=body,
        )
    except Exception as exc:
        logger.warning("notify_ops email failed: %s", exc)


def notify_ops_transfer(
    event: str,
    transfer_id: str,
    details: dict[str, Any],
) -> None:
    """Alert ops team about an outbound transfer event."""
    lines = [
        f"Event     : {event}",
        f"Transfer  : {transfer_id}",
        f"Timestamp : {datetime.now(tz=timezone.utc).isoformat()}",
        "",
    ]
    for k, v in details.items():
        lines.append(f"{k:18}: {v}")
    notify_ops(f"Transfer {event} — {transfer_id}", "\n".join(lines))


def notify_ops_tokenization(
    event: str,
    job_id: str,
    details: dict[str, Any],
) -> None:
    """Alert ops team about an M1 tokenization event."""
    lines = [
        f"Event     : {event}",
        f"Job ID    : {job_id}",
        f"Timestamp : {datetime.now(tz=timezone.utc).isoformat()}",
        "",
    ]
    for k, v in details.items():
        lines.append(f"{k:18}: {v}")
    notify_ops(f"M1 Tokenization {event} — {job_id}", "\n".join(lines))


# ─── SMTP Email Delivery ───────────────────────────────────────────────────────

def _send_email(to: str, subject: str, body: str) -> None:
    """Send a plain-text email via configured SMTP."""
    if not settings.smtp_host:
        logger.debug("SMTP not configured — skipping email: %s", subject)
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = settings.notify_from_email
    msg["To"] = to
    msg.attach(MIMEText(body, "plain"))

    context = ssl.create_default_context()
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
        if settings.smtp_tls:
            server.starttls(context=context)
        if settings.smtp_user and settings.smtp_password:
            server.login(settings.smtp_user, settings.smtp_password)
        server.sendmail(settings.notify_from_email, to, msg.as_string())

    logger.info("Email sent: subject=%s to=%s", subject, to)


# ─── Outbound Webhook Delivery ────────────────────────────────────────────────

def _sign_payload(payload: bytes, secret: str) -> str:
    """HMAC-SHA256 signature for outbound webhook payloads."""
    return "sha256=" + hmac.new(
        secret.encode(),
        payload,
        hashlib.sha256,
    ).hexdigest()


async def deliver_webhook(
    url: str,
    event_type: str,
    data: dict[str, Any],
    *,
    secret: str | None = None,
    max_retries: int = 3,
    timeout: float = 10.0,
) -> dict[str, Any]:
    """
    Deliver a webhook to a counterparty callback URL.
    Retries up to max_retries times with exponential back-off.
    Returns a delivery result dict.
    """
    payload_dict = {
        "event": event_type,
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        "data": data,
    }
    raw = json.dumps(payload_dict, default=str).encode()

    headers = {
        "Content-Type": "application/json",
        "User-Agent": "ALSHUMOOKH-Webhook/1.0",
        "X-ALSHUMOOKH-Event": event_type,
    }
    if secret:
        headers["X-ALSHUMOOKH-Signature"] = _sign_payload(raw, secret)

    last_error: str | None = None
    status_code: int | None = None

    for attempt in range(1, max_retries + 1):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(url, content=raw, headers=headers)
                status_code = response.status_code

                if response.is_success:
                    logger.info(
                        "Webhook delivered: event=%s url=%s status=%d attempt=%d",
                        event_type, url, status_code, attempt,
                    )
                    return {
                        "delivered": True,
                        "status_code": status_code,
                        "attempts": attempt,
                        "url": url,
                        "event": event_type,
                    }

                last_error = f"HTTP {status_code}"
                logger.warning(
                    "Webhook non-2xx: event=%s url=%s status=%d attempt=%d",
                    event_type, url, status_code, attempt,
                )

        except Exception as exc:
            last_error = str(exc)
            logger.warning(
                "Webhook failed: event=%s url=%s attempt=%d error=%s",
                event_type, url, attempt, exc,
            )

        if attempt < max_retries:
            wait = 2 ** attempt  # 2s, 4s, 8s
            await asyncio.sleep(wait)

    return {
        "delivered": False,
        "status_code": status_code,
        "attempts": max_retries,
        "url": url,
        "event": event_type,
        "error": last_error,
    }


async def notify_transfer_completed(
    callback_url: str | None,
    transfer_id: str,
    tx_hash: str | None,
    amount: str,
    network: str,
    to_address: str,
    explorer_url: str | None = None,
    asset: str = "USDT",
) -> dict[str, Any] | None:
    """Send webhook + ops email on outbound transfer completion."""
    notify_ops_transfer(
        "COMPLETED",
        transfer_id,
        {
            "tx_hash": tx_hash or "N/A",
            "amount_usdt": amount,
            "amount": amount,
            "asset": asset,
            "network": network,
            "to_address": to_address,
            "explorer": explorer_url or "N/A",
        },
    )
    if not callback_url:
        return None
    return await deliver_webhook(
        url=callback_url,
        event_type="transfer.completed",
        data={
            "transfer_id": transfer_id,
            "tx_hash": tx_hash,
            "amount_usdt": amount,
            "amount": amount,
            "asset": asset,
            "network": network,
            "to_address": to_address,
            "explorer_url": explorer_url,
        },
    )


async def notify_transfer_failed(
    callback_url: str | None,
    transfer_id: str,
    error: str,
    amount: str,
    network: str,
) -> dict[str, Any] | None:
    """Send webhook + ops email on outbound transfer failure."""
    notify_ops_transfer(
        "FAILED",
        transfer_id,
        {"error": error, "amount_usdt": amount, "network": network},
    )
    if not callback_url:
        return None
    return await deliver_webhook(
        url=callback_url,
        event_type="transfer.failed",
        data={
            "transfer_id": transfer_id,
            "error": error,
            "amount_usdt": amount,
            "network": network,
        },
    )


async def notify_payload_verified(
    callback_url: str | None,
    payload_id: str,
    tx_hash: str,
    amount: str,
    asset: str,
    network: str,
) -> dict[str, Any] | None:
    """Notify counterparty that their settlement payload was on-chain verified."""
    if not callback_url:
        return None
    return await deliver_webhook(
        url=callback_url,
        event_type="payload.verified",
        data={
            "payload_id": payload_id,
            "tx_hash": tx_hash,
            "amount": amount,
            "asset": asset,
            "network": network,
        },
    )


async def notify_m1_job_ready(
    callback_url: str | None,
    job_id: str,
    eur_amount: str,
    usdt_amount: str,
    outbound_transfer_id: str,
) -> dict[str, Any] | None:
    """Notify that M1 tokenization job is ready for approval."""
    notify_ops_tokenization(
        "AWAITING_APPROVAL",
        job_id,
        {
            "eur_amount": eur_amount,
            "usdt_amount": usdt_amount,
            "transfer_id": outbound_transfer_id,
        },
    )
    if not callback_url:
        return None
    return await deliver_webhook(
        url=callback_url,
        event_type="m1.tokenization.ready",
        data={
            "job_id": job_id,
            "eur_amount": eur_amount,
            "usdt_amount": usdt_amount,
            "outbound_transfer_id": outbound_transfer_id,
        },
    )
