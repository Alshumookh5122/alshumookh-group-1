"""
OTC Service — Live EUR/USDT rate fetching and quote management.
Uses Binance public API (no auth required for price data).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_DOWN

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import OtcQuote, OtcQuoteStatus, OtcRateSource

logger = logging.getLogger(__name__)

BINANCE_TICKER_URL = "https://api.binance.com/api/v3/ticker/price"
# EUR/USDT pair on Binance
EUR_USDT_SYMBOL = "EURUSDT"
# How many minutes to lock a rate after approval
RATE_LOCK_MINUTES = 30


# ─── Rate Fetching ────────────────────────────────────────────────────────────

async def fetch_live_rate_eur_usdt() -> dict:
    """Fetch current EUR/USDT rate from Binance. Returns dict with rate info."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.get(
                BINANCE_TICKER_URL,
                params={"symbol": EUR_USDT_SYMBOL},
            )
            resp.raise_for_status()
            data = resp.json()
            rate = Decimal(str(data["price"]))
            return {
                "symbol": EUR_USDT_SYMBOL,
                "rate": rate,
                "source": OtcRateSource.BINANCE.value,
                "raw": data,
                "fetched_at": datetime.now(timezone.utc).isoformat(),
            }
        except Exception as exc:
            logger.error("Binance rate fetch failed: %s", exc)
            raise RuntimeError(f"Failed to fetch EUR/USDT rate from Binance: {exc}") from exc


# ─── Quote Management ─────────────────────────────────────────────────────────

async def create_quote(
    db: AsyncSession,
    amount_eur: Decimal,
    client_id: str | None = None,
    fiat_deposit_id: str | None = None,
    manual_rate: Decimal | None = None,
    notes: str | None = None,
) -> OtcQuote:
    """
    Create a new OTC quote.
    If manual_rate is provided, uses it; otherwise fetches from Binance.
    """
    if manual_rate is not None:
        rate = manual_rate
        source = OtcRateSource.MANUAL.value
        raw_data = {"manual_rate": str(manual_rate)}
    else:
        rate_info = await fetch_live_rate_eur_usdt()
        rate = rate_info["rate"]
        source = rate_info["source"]
        raw_data = rate_info["raw"]

    amount_usdt = (amount_eur * rate).quantize(Decimal("0.000001"), rounding=ROUND_DOWN)

    quote = OtcQuote(
        client_id=client_id,
        fiat_deposit_id=fiat_deposit_id,
        amount_eur=amount_eur,
        rate_eur_usdt=rate,
        amount_usdt=amount_usdt,
        rate_source=source,
        raw_rate_data=raw_data,
        status=OtcQuoteStatus.REQUESTED.value,
        notes=notes,
    )
    db.add(quote)
    await db.commit()
    await db.refresh(quote)
    logger.info("OTC quote created: %s | %.6f EUR @ %.8f = %.6f USDT",
                quote.reference, amount_eur, rate, amount_usdt)
    return quote


async def approve_quote(db: AsyncSession, quote_id: str) -> OtcQuote:
    """Admin approves a quote — status moves REQUESTED → APPROVED."""
    result = await db.execute(select(OtcQuote).where(OtcQuote.id == quote_id))
    quote = result.scalar_one_or_none()
    if not quote:
        raise ValueError("Quote not found")
    if quote.status != OtcQuoteStatus.REQUESTED.value:
        raise ValueError(f"Quote is {quote.status}, cannot approve")
    quote.status = OtcQuoteStatus.APPROVED.value
    await db.commit()
    await db.refresh(quote)
    return quote


async def lock_quote(db: AsyncSession, quote_id: str) -> OtcQuote:
    """
    Lock an approved quote for execution.
    Rate is guaranteed for RATE_LOCK_MINUTES minutes.
    """
    result = await db.execute(select(OtcQuote).where(OtcQuote.id == quote_id))
    quote = result.scalar_one_or_none()
    if not quote:
        raise ValueError("Quote not found")
    if quote.status not in (OtcQuoteStatus.APPROVED.value, OtcQuoteStatus.REQUESTED.value):
        raise ValueError(f"Quote is {quote.status}, cannot lock")
    quote.status = OtcQuoteStatus.LOCKED.value
    quote.locked_until = datetime.now(timezone.utc) + timedelta(minutes=RATE_LOCK_MINUTES)
    await db.commit()
    await db.refresh(quote)
    return quote


async def execute_quote(db: AsyncSession, quote_id: str) -> OtcQuote:
    """Mark quote as executed after USDT transfer is initiated."""
    result = await db.execute(select(OtcQuote).where(OtcQuote.id == quote_id))
    quote = result.scalar_one_or_none()
    if not quote:
        raise ValueError("Quote not found")
    if quote.status != OtcQuoteStatus.LOCKED.value:
        raise ValueError(f"Quote is {quote.status}, must be LOCKED to execute")
    # Check lock expiry
    if quote.locked_until and datetime.now(timezone.utc) > quote.locked_until:
        quote.status = OtcQuoteStatus.EXPIRED.value
        await db.commit()
        raise ValueError("Quote lock has expired — please create a new quote")
    quote.status = OtcQuoteStatus.EXECUTED.value
    await db.commit()
    await db.refresh(quote)
    return quote


async def cancel_quote(db: AsyncSession, quote_id: str) -> OtcQuote:
    """Cancel a quote at any non-final stage."""
    result = await db.execute(select(OtcQuote).where(OtcQuote.id == quote_id))
    quote = result.scalar_one_or_none()
    if not quote:
        raise ValueError("Quote not found")
    if quote.status in (OtcQuoteStatus.EXECUTED.value, OtcQuoteStatus.CANCELLED.value):
        raise ValueError(f"Quote is already {quote.status}")
    quote.status = OtcQuoteStatus.CANCELLED.value
    await db.commit()
    await db.refresh(quote)
    return quote


async def refresh_quote_rate(db: AsyncSession, quote_id: str) -> OtcQuote:
    """Re-fetch Binance rate for a REQUESTED quote and recalculate USDT amount."""
    result = await db.execute(select(OtcQuote).where(OtcQuote.id == quote_id))
    quote = result.scalar_one_or_none()
    if not quote:
        raise ValueError("Quote not found")
    if quote.status != OtcQuoteStatus.REQUESTED.value:
        raise ValueError("Only REQUESTED quotes can be refreshed")

    rate_info = await fetch_live_rate_eur_usdt()
    rate = rate_info["rate"]
    quote.rate_eur_usdt = rate
    quote.amount_usdt = (quote.amount_eur * rate).quantize(Decimal("0.000001"), rounding=ROUND_DOWN)
    quote.rate_source = OtcRateSource.BINANCE.value
    quote.raw_rate_data = rate_info["raw"]
    await db.commit()
    await db.refresh(quote)
    return quote
