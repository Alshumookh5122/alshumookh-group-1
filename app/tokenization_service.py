"""
ALSHUMOOKH — M1 Fund Tokenization Engine
Pipeline: EUR (SWIFT inbound) → USD (live FX) → SIG tokens (ERC-20 / Ethereum)

Flow:
  1. Receive M1 SWIFT/SEPA payload with EUR amount
  2. Fetch live EUR/USD FX rate
  3. Calculate SIG amount (1 SIG = 1 USD — reserve-backed)
  4. Create OutboundTransfer record with AWAITING_APPROVAL status
  5. Admin approves → broadcast_outbound_transfer()
  6. Update M1TokenizationJob to COMPLETED
  7. M1 Reserve grows with each EUR investment, giving SIG real liquidity
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit_service import log_event
from app.config import get_settings
from app.models import (
    M1TokenizationJob,
    M1TokenizationStatus,
    OutboundTransfer,
    OutboundTransferStatus,
)
from app.transfer_service import create_outbound_transfer

logger = logging.getLogger(__name__)
settings = get_settings()

# ─── FX providers (in priority order) ────────────────────────────────────────

_FX_PROVIDERS = [
    "frankfurter",
    "exchangerate_api",
    "ecb",
]


async def _fetch_eur_usd_frankfurter() -> tuple[Decimal, str]:
    """Fetch EUR/USD from Frankfurter (free, ECB data)."""
    async with httpx.AsyncClient(timeout=8, follow_redirects=True) as client:
        r = await client.get(
            "https://api.frankfurter.dev/v1/latest",
            params={"from": "EUR", "to": "USD"},
        )
        r.raise_for_status()
        data = r.json()
        rate = Decimal(str(data["rates"]["USD"]))
        return rate, "frankfurter"


async def _fetch_eur_usd_exchangerate_api() -> tuple[Decimal, str]:
    """Fetch EUR/USD from open.er-api.com (free tier)."""
    async with httpx.AsyncClient(timeout=8) as client:
        r = await client.get("https://open.er-api.com/v6/latest/EUR")
        r.raise_for_status()
        data = r.json()
        rate = Decimal(str(data["rates"]["USD"]))
        return rate, "exchangerate_api"


async def _fetch_eur_usd_ecb() -> tuple[Decimal, str]:
    """Parse the ECB XML daily feed as last resort."""
    import xml.etree.ElementTree as ET

    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(
            "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"
        )
        r.raise_for_status()
        root = ET.fromstring(r.text)
        ns = {"gesmes": "http://www.gesmes.org/xml/2002-08-01",
              "ecb": "http://www.ecb.int/vocabulary/2002-08-01/eurofxref"}
        for cube in root.iter("{http://www.ecb.int/vocabulary/2002-08-01/eurofxref}Cube"):
            if cube.attrib.get("currency") == "USD":
                return Decimal(cube.attrib["rate"]), "ecb"
    raise ValueError("USD rate not found in ECB feed")


async def fetch_live_eur_usd() -> tuple[Decimal, str]:
    """
    Fetch live EUR/USD rate with provider fallback chain.
    Returns (rate, provider_name).
    """
    errors: list[str] = []
    for provider in _FX_PROVIDERS:
        try:
            if provider == "frankfurter":
                return await _fetch_eur_usd_frankfurter()
            elif provider == "exchangerate_api":
                return await _fetch_eur_usd_exchangerate_api()
            elif provider == "ecb":
                return await _fetch_eur_usd_ecb()
        except Exception as exc:
            errors.append(f"{provider}: {exc}")
            logger.warning("FX provider %s failed: %s", provider, exc)

    raise RuntimeError(
        f"All FX providers failed: {'; '.join(errors)}"
    )


# ─── Tokenization job lifecycle ───────────────────────────────────────────────

async def create_tokenization_job(
    db: AsyncSession,
    *,
    eur_amount: Decimal,
    sender_reference: str | None = None,
    sender_name: str | None = None,
    sender_iban: str | None = None,
    payload_id: str | None = None,
    destination_wallet: str | None = None,
    network: str = "ethereum",
    notes: str | None = None,
    raw_data: dict | None = None,
) -> M1TokenizationJob:
    """Create a new M1 tokenization job in QUEUED status."""
    job = M1TokenizationJob(
        eur_amount=eur_amount,
        sender_reference=sender_reference,
        sender_name=sender_name,
        sender_iban=sender_iban,
        payload_id=payload_id,
        destination_wallet=destination_wallet,
        network=network,
        notes=notes,
        raw_data=raw_data,
        status=M1TokenizationStatus.QUEUED.value,
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)

    await log_event(
        db,
        "M1_TOKENIZATION_JOB_CREATED",
        {
            "job_id": job.id,
            "eur_amount": str(eur_amount),
            "sender_reference": sender_reference,
            "network": network,
        },
        None,
    )
    return job


async def process_tokenization_job(
    db: AsyncSession,
    job_id: str,
    *,
    override_destination: str | None = None,
    override_network: str | None = None,
    override_asset: str | None = None,
    processed_by: str = "system",
    force: bool = False,
) -> M1TokenizationJob:
    """
    Run the full EUR→USD→USDT/SIG tokenization pipeline for a queued job.
    Steps: QUEUED → FX_FETCHED → CONVERTING → SENDING → COMPLETED
    Set force=True to reprocess a COMPLETED job with a different asset (e.g. SIG).
    """
    result = await db.execute(
        select(M1TokenizationJob).where(M1TokenizationJob.id == job_id)
    )
    job = result.scalar_one_or_none()
    if not job:
        raise ValueError(f"M1TokenizationJob {job_id} not found")

    allowed_statuses = (
        M1TokenizationStatus.QUEUED.value,
        M1TokenizationStatus.FAILED.value,
    )
    if force:
        allowed_statuses = allowed_statuses + (M1TokenizationStatus.COMPLETED.value,)

    if job.status not in allowed_statuses:
        raise ValueError(f"Job is in status {job.status}, cannot process")

    job.processed_by = processed_by

    try:
        # ── Step 1: Fetch FX rate ──────────────────────────────
        job.status = M1TokenizationStatus.FX_FETCHED.value
        await db.commit()

        fx_rate, fx_provider = await fetch_live_eur_usd()
        usd_amount = (job.eur_amount * fx_rate).quantize(Decimal("0.000001"), rounding=ROUND_DOWN)

        job.fx_rate_eur_usd = fx_rate
        job.usd_amount = usd_amount
        job.fx_provider = fx_provider
        job.fx_fetched_at = datetime.now(tz=timezone.utc)
        await db.commit()

        await log_event(
            db,
            "M1_FX_RATE_FETCHED",
            {
                "job_id": job_id,
                "eur_amount": str(job.eur_amount),
                "fx_rate": str(fx_rate),
                "usd_amount": str(usd_amount),
                "provider": fx_provider,
            },
            None,
        )

        # ── Step 2: Calculate token output ────────────────────
        job.status = M1TokenizationStatus.CONVERTING.value
        target_asset = str(
            override_asset
            or (job.raw_data or {}).get("target_asset")
            or "SIG"
        ).strip().upper()
        if target_asset not in {"USDT", "SIG"}:
            raise ValueError("Tokenization target asset must be USDT or SIG")
        if target_asset == "SIG":
            # SIG: divide USD amount by M1 issuance price (e.g. 0.053266 USD/SIG)
            # This gives correct SIG output: 26,633,164.50 USD ÷ 0.053266 = 500,000,000 SIG
            token_precision = Decimal("0.000000000000000001")  # 18 decimals
            sig_price = settings.sig_m1_price_usd
            usdt_amount = (usd_amount / sig_price).quantize(token_precision, rounding=ROUND_DOWN)
        else:
            # USDT: 1:1 with USD
            token_precision = Decimal("0.000001")               # 6 decimals (USDT)
            usdt_amount = usd_amount.quantize(token_precision, rounding=ROUND_DOWN)
        job.usdt_amount = usdt_amount

        destination = override_destination or job.destination_wallet
        network = override_network or job.network or "ethereum"

        if not destination:
            raise ValueError(
                "destination_wallet is required for tokenization jobs. "
                "The client's receiving wallet address must be explicitly set on the job "
                "before processing. Falling back to treasury address is not allowed — "
                "it would cause a self-transfer (treasury → treasury)."
            )

        await db.commit()

        # ── Step 3: Create outbound transfer (AWAITING_APPROVAL) ─
        job.status = M1TokenizationStatus.SENDING.value
        await db.commit()

        ot = await create_outbound_transfer(
            db,
            to_address=destination,
            amount=usdt_amount,
            network=network,
            asset=target_asset,
            tokenization_job_id=job.id,
            payload_id=job.payload_id,
            initiated_by=processed_by,
            notes=f"M1 Tokenization Job {job.id} | EUR {job.eur_amount} → USD {usd_amount} → {target_asset} {usdt_amount}",
        )

        # Mark transfer as awaiting approval (admin must approve before broadcast)
        ot.status = OutboundTransferStatus.AWAITING_APPROVAL.value
        await db.commit()

        job.outbound_transfer_id = ot.id
        job.status = M1TokenizationStatus.COMPLETED.value
        job.completed_at = datetime.now(tz=timezone.utc)
        await db.commit()
        await db.refresh(job)

        await log_event(
            db,
            "M1_TOKENIZATION_COMPLETED",
            {
                "job_id": job_id,
                "eur_amount": str(job.eur_amount),
                "token_amount": str(usdt_amount),
                "target_asset": target_asset,
                "outbound_transfer_id": ot.id,
                "destination": destination,
                "network": network,
            },
            None,
        )

    except Exception as exc:
        job.status = M1TokenizationStatus.FAILED.value
        job.error_message = str(exc)
        await db.commit()
        await db.refresh(job)

        await log_event(
            db,
            "M1_TOKENIZATION_FAILED",
            {"job_id": job_id, "error": str(exc)},
            None,
        )
        raise

    return job


async def get_job_summary(db: AsyncSession, job_id: str) -> dict[str, Any]:
    """Return a rich summary dict for a tokenization job."""
    result = await db.execute(
        select(M1TokenizationJob).where(M1TokenizationJob.id == job_id)
    )
    job = result.scalar_one_or_none()
    if not job:
        raise ValueError(f"Job {job_id} not found")

    ot = None
    if job.outbound_transfer_id:
        r2 = await db.execute(
            select(OutboundTransfer).where(OutboundTransfer.id == job.outbound_transfer_id)
        )
        ot = r2.scalar_one_or_none()

    return {
        "job_id": job.id,
        "status": job.status,
        "sender_reference": job.sender_reference,
        "sender_name": job.sender_name,
        "eur_amount": str(job.eur_amount),
        "fx_rate_eur_usd": str(job.fx_rate_eur_usd) if job.fx_rate_eur_usd else None,
        "usd_amount": str(job.usd_amount) if job.usd_amount else None,
        "usdt_amount": str(job.usdt_amount) if job.usdt_amount else None,
        "target_asset": str((job.raw_data or {}).get("target_asset") or "SIG").upper(),
        "raw_data": job.raw_data or {},
        "network": job.network,
        "destination_wallet": job.destination_wallet,
        "fx_provider": job.fx_provider,
        "outbound_transfer": {
            "id": ot.id,
            "status": ot.status,
            "tx_hash": ot.tx_hash,
            "explorer_url": ot.explorer_url,
            "amount": str(ot.amount),
            "asset": ot.asset,
        } if ot else None,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        "error_message": job.error_message,
    }
