"""
NOWPayments integration service.
Handles: create payment, mass payout, auto-conversion, payment status, webhook verification.
Set NOWPAYMENTS_API_KEY and NOWPAYMENTS_IPN_SECRET in environment variables.
"""

import hashlib
import hmac
import json
import logging
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

BASE_URL = settings.nowpayments_api_url  # https://api.nowpayments.io/v1


def _headers() -> dict:
    return {
        "x-api-key": settings.nowpayments_api_key or "",
        "Content-Type": "application/json",
    }


def _configured() -> bool:
    return bool(settings.nowpayments_api_key)


# ── Status ─────────────────────────────────────────────────────────────────────

async def get_status() -> dict:
    """Check NOWPayments API availability."""
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(f"{BASE_URL}/status")
        return r.json()


async def get_currencies() -> list[str]:
    """Return list of supported currencies."""
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(f"{BASE_URL}/currencies", headers=_headers())
        data = r.json()
        return data.get("currencies", [])


async def get_min_amount(currency_from: str, currency_to: str) -> dict:
    """Return minimum payment amount for a currency pair."""
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(
            f"{BASE_URL}/min-amount",
            params={"currency_from": currency_from, "currency_to": currency_to},
            headers=_headers(),
        )
        return r.json()


# ── Create Payment ─────────────────────────────────────────────────────────────

async def create_payment(
    price_amount: float,
    price_currency: str,      # e.g. "usd", "eur"
    pay_currency: str,         # e.g. "usdtbsc", "usdcerc20", "btc"
    order_id: str | None = None,
    order_description: str | None = None,
    ipn_callback_url: str | None = None,
    success_url: str | None = None,
    cancel_url: str | None = None,
    is_fixed_rate: bool = False,
    is_fee_paid_by_user: bool = False,
) -> dict:
    """
    Create a crypto payment invoice.
    Returns payment object with pay_address, payment_id, payment_status, etc.
    """
    payload: dict[str, Any] = {
        "price_amount": price_amount,
        "price_currency": price_currency.lower(),
        "pay_currency": pay_currency.lower(),
        "is_fixed_rate": is_fixed_rate,
        "is_fee_paid_by_user": is_fee_paid_by_user,
    }
    if order_id:
        payload["order_id"] = order_id
    if order_description:
        payload["order_description"] = order_description
    if ipn_callback_url:
        payload["ipn_callback_url"] = ipn_callback_url
    if success_url:
        payload["success_url"] = success_url
    if cancel_url:
        payload["cancel_url"] = cancel_url

    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.post(f"{BASE_URL}/payment", headers=_headers(), json=payload)
        r.raise_for_status()
        return r.json()


async def get_payment_status(payment_id: str) -> dict:
    """Get current status of a payment."""
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(f"{BASE_URL}/payment/{payment_id}", headers=_headers())
        r.raise_for_status()
        return r.json()


async def list_payments(
    limit: int = 20,
    page: int = 0,
    sort_by: str = "created_at",
    order_by: str = "desc",
) -> dict:
    """List all payments with pagination."""
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(
            f"{BASE_URL}/payment/",
            headers=_headers(),
            params={"limit": limit, "page": page, "sortBy": sort_by, "orderBy": order_by},
        )
        r.raise_for_status()
        return r.json()


# ── Create Invoice (payment link) ─────────────────────────────────────────────

async def create_invoice(
    price_amount: float,
    price_currency: str,
    order_id: str | None = None,
    order_description: str | None = None,
    ipn_callback_url: str | None = None,
    success_url: str | None = None,
    cancel_url: str | None = None,
) -> dict:
    """
    Create a hosted invoice page (client clicks link and pays).
    Returns invoice_url the client opens to pay.
    """
    payload: dict[str, Any] = {
        "price_amount": price_amount,
        "price_currency": price_currency.lower(),
    }
    if order_id:
        payload["order_id"] = order_id
    if order_description:
        payload["order_description"] = order_description
    if ipn_callback_url:
        payload["ipn_callback_url"] = ipn_callback_url
    if success_url:
        payload["success_url"] = success_url
    if cancel_url:
        payload["cancel_url"] = cancel_url

    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.post(f"{BASE_URL}/invoice", headers=_headers(), json=payload)
        r.raise_for_status()
        return r.json()


# ── Mass Payout ────────────────────────────────────────────────────────────────

async def create_payout(
    withdrawals: list[dict],
    # Each dict: {"address": "0x...", "currency": "usdterc20", "amount": 100.0, "ipn_callback_url": "..."}
) -> dict:
    """
    Create mass payout to multiple addresses in one call.
    Requires Payouts API enabled in NOWPayments account.
    """
    payload = {"withdrawals": withdrawals}
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(f"{BASE_URL}/payout", headers=_headers(), json=payload)
        r.raise_for_status()
        return r.json()


async def get_payout_status(payout_id: str) -> dict:
    """Get status of a payout batch."""
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(f"{BASE_URL}/payout/{payout_id}", headers=_headers())
        r.raise_for_status()
        return r.json()


# ── Estimate / Auto-conversion ─────────────────────────────────────────────────

async def get_estimate(
    amount: float,
    currency_from: str,
    currency_to: str,
) -> dict:
    """Estimate how much currency_to the user will receive for amount of currency_from."""
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(
            f"{BASE_URL}/estimate",
            headers=_headers(),
            params={
                "amount": amount,
                "currency_from": currency_from.lower(),
                "currency_to": currency_to.lower(),
            },
        )
        r.raise_for_status()
        return r.json()


# ── Webhook / IPN Verification ─────────────────────────────────────────────────

def verify_ipn_signature(payload_bytes: bytes, signature: str) -> bool:
    """
    Verify NOWPayments IPN webhook signature.
    Uses NOWPAYMENTS_IPN_SECRET from settings.
    """
    secret = settings.nowpayments_ipn_secret
    if not secret:
        logger.warning("NOWPAYMENTS_IPN_SECRET not set — skipping signature check")
        return True  # allow in dev; tighten in prod

    try:
        body = json.loads(payload_bytes)
        # NOWPayments sorts keys before signing
        sorted_body = json.dumps(body, sort_keys=True, separators=(",", ":"))
        expected = hmac.new(
            secret.encode(),
            sorted_body.encode(),
            hashlib.sha512,
        ).hexdigest()
        return hmac.compare_digest(expected, signature)
    except Exception as exc:
        logger.error("IPN signature verification failed: %s", exc)
        return False


def parse_ipn_status(body: dict) -> str:
    """
    Map NOWPayments IPN payment_status to internal status string.
    Statuses: waiting → confirming → confirmed → sending → partially_paid → finished → failed → refunded → expired
    """
    status = body.get("payment_status", "").lower()
    mapping = {
        "finished":        "COMPLETED",
        "confirmed":       "CONFIRMED",
        "confirming":      "CONFIRMING",
        "sending":         "SENDING",
        "waiting":         "WAITING",
        "partially_paid":  "PARTIAL",
        "failed":          "FAILED",
        "refunded":        "REFUNDED",
        "expired":         "EXPIRED",
    }
    return mapping.get(status, status.upper())
