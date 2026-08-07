"""
ALSHUMOOKH — Circle Wire Deposit Service
=========================================
Handles:
  1. Circle account balance (USDC) fetching
  2. Wire deposit reference generation (SWIFT MT103 instructions)
  3. Webhook processing for wire.deposit.received events
  4. Auto-settlement: USDC received → transfer to Master Wallet
  5. Full audit trail per deposit

Circle Wire Flow:
  Client → SWIFT MT103 (with ALSH-CW-XXXXXXXX reference) → Circle Bank
  → Circle credits USDC to ALSHUMOOKH Circle wallet
  → Circle fires webhook → this service matches & settles
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import httpx
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import (
    CircleWireDeposit,
    CircleWireDepositStatus,
    FiatDeposit,
    FiatDepositStatus,
    FiatPaymentMethod,
)

logger = logging.getLogger(__name__)
settings = get_settings()

CIRCLE_API_BASE = "https://api.circle.com/v1"


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _circle_headers() -> dict:
    api_key = settings.circle_api_key or ""
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _is_configured() -> bool:
    return bool(settings.circle_api_key)


# ─── 1. Balance ───────────────────────────────────────────────────────────────

async def get_circle_balance() -> dict:
    """
    Fetch USDC (and other token) balances from Circle Programmable Wallet.
    Returns structured balance info for dashboard display.
    """
    if not _is_configured():
        return {"error": "Circle API key not configured", "balances": []}

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            # Try Programmable Wallets balance endpoint
            wallet_id = settings.circle_wallet_id
            if wallet_id:
                resp = await client.get(
                    f"{CIRCLE_API_BASE}/wallets/{wallet_id}/balances",
                    headers=_circle_headers(),
                )
                if resp.status_code == 200:
                    data = resp.json().get("data", {})
                    token_balances = data.get("tokenBalances", [])
                    usdc_balance = Decimal("0")
                    for tb in token_balances:
                        token = tb.get("token", {})
                        if token.get("symbol") == "USDC":
                            usdc_balance = Decimal(str(tb.get("amount", "0")))
                    return {
                        "wallet_id": wallet_id,
                        "wallet_address": settings.circle_wallet_address or "—",
                        "usdc_balance": str(usdc_balance),
                        "token_balances": token_balances,
                        "fetched_at": datetime.now(timezone.utc).isoformat(),
                        "source": "programmable_wallet",
                    }

            # Fallback: business account balances
            resp = await client.get(
                f"{CIRCLE_API_BASE}/businessAccount/balances",
                headers=_circle_headers(),
            )
            resp.raise_for_status()
            data = resp.json().get("data", {})
            available = data.get("available", [])
            usdc_balance = Decimal("0")
            for item in available:
                if item.get("currency") == "USD":
                    usdc_balance = Decimal(str(item.get("amount", "0")))
            return {
                "wallet_id": wallet_id or "business_account",
                "wallet_address": settings.circle_wallet_address or "—",
                "usdc_balance": str(usdc_balance),
                "token_balances": available,
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "source": "business_account",
            }

    except Exception as exc:
        logger.error("Circle balance fetch failed: %s", exc)
        return {
            "error": str(exc),
            "usdc_balance": "0",
            "balances": [],
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }


# ─── 2. Wire Deposit Instructions ─────────────────────────────────────────────

async def get_wire_instructions() -> dict:
    """
    Fetch Circle's wire deposit banking instructions (account number, routing, SWIFT BIC).
    These are the instructions we give to clients sending SWIFT MT103.
    """
    if not _is_configured():
        return {"error": "Circle API key not configured"}

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{CIRCLE_API_BASE}/businessAccount/banks/wires",
                headers=_circle_headers(),
            )
            if resp.status_code == 200:
                data = resp.json().get("data", [])
                return {"instructions": data, "fetched_at": datetime.now(timezone.utc).isoformat()}
            return {"error": f"Circle returned {resp.status_code}", "body": resp.text[:500]}
    except Exception as exc:
        logger.error("Circle wire instructions fetch failed: %s", exc)
        return {"error": str(exc)}


# ─── 3. Create Wire Deposit Record ────────────────────────────────────────────

async def create_wire_deposit(
    db: AsyncSession,
    amount_eur: Decimal,
    sender_name: str | None = None,
    sender_bank: str | None = None,
    sender_iban: str | None = None,
    sender_swift_bic: str | None = None,
    client_id: str | None = None,
    settlement_wallet: str | None = None,
    settlement_network: str = "ethereum",
    notes: str | None = None,
) -> CircleWireDeposit:
    """
    Create a new expected wire deposit with a unique SWIFT reference.
    The reference must be included by the client in the MT103 payment details field.
    """
    # Use master wallet as settlement destination if not specified
    if not settlement_wallet:
        settlement_wallet = (
            settings.master_wallet_ethereum
            or settings.eth_treasury_address
            or settings.treasury_wallet
        )

    deposit = CircleWireDeposit(
        amount_eur=amount_eur,
        sender_name=sender_name,
        sender_bank=sender_bank,
        sender_iban=sender_iban,
        sender_swift_bic=sender_swift_bic,
        client_id=client_id,
        settlement_wallet=settlement_wallet,
        settlement_network=settlement_network,
        status=CircleWireDepositStatus.PENDING.value,
        notes=notes,
    )
    db.add(deposit)
    await db.commit()
    await db.refresh(deposit)

    # Also create a linked FiatDeposit record for unified tracking
    fiat = FiatDeposit(
        amount_eur=amount_eur,
        sender_name=sender_name,
        sender_bank=sender_bank,
        sender_iban=sender_iban,
        payment_method=FiatPaymentMethod.SWIFT.value,
        bank_reference=deposit.swift_reference,
        client_id=client_id,
        status=FiatDepositStatus.PENDING.value,
        notes=f"Circle Wire Deposit — Ref: {deposit.swift_reference}",
    )
    db.add(fiat)
    await db.commit()
    await db.refresh(fiat)

    # Link fiat deposit back to wire deposit
    deposit.fiat_deposit_id = fiat.id
    await db.commit()
    await db.refresh(deposit)

    logger.info(
        "Circle wire deposit created: %s | %.2f EUR | ref: %s",
        deposit.id, amount_eur, deposit.swift_reference,
    )
    return deposit


# ─── 4. Process Circle Webhook ────────────────────────────────────────────────

async def process_circle_webhook(db: AsyncSession, payload: dict) -> dict:
    """
    Process incoming Circle webhook events.
    Handles: wire_deposit.received, payments.payment.paid, transfers.transfer.complete
    """
    event_type = payload.get("Type") or payload.get("type") or ""
    notification = payload.get("notification") or payload.get("data") or payload

    logger.info("Circle webhook received: type=%s", event_type)

    # Handle wire deposit received
    if "wire" in event_type.lower() or "deposit" in event_type.lower():
        return await _handle_wire_received(db, notification, event_type)

    # Handle payment confirmed
    if "payment" in event_type.lower():
        return await _handle_payment_confirmed(db, notification, event_type)

    return {"status": "ignored", "event_type": event_type}


async def _handle_wire_received(db: AsyncSession, data: dict, event_type: str) -> dict:
    """Match incoming wire to a CircleWireDeposit by reference code."""
    # Extract reference from Circle's notification
    description = (
        data.get("description", "")
        or data.get("trackingRef", "")
        or data.get("beneficiaryBank", {}).get("trackingRef", "")
        or ""
    )
    circle_payment_id = data.get("id") or data.get("paymentId") or ""
    amount_data = data.get("amount", {})
    amount_usdc = Decimal(str(amount_data.get("amount", "0"))) if amount_data else Decimal("0")
    currency = amount_data.get("currency", "USD") if amount_data else "USD"

    logger.info(
        "Wire received: circle_id=%s amount=%s %s ref=%s",
        circle_payment_id, amount_usdc, currency, description,
    )

    # Try to find matching wire deposit by swift_reference in description
    deposit: CircleWireDeposit | None = None
    if description:
        # Search for ALSH-CW-XXXXXXXX pattern in description
        result = await db.execute(
            select(CircleWireDeposit).where(
                CircleWireDeposit.status == CircleWireDepositStatus.PENDING.value
            ).order_by(desc(CircleWireDeposit.created_at))
        )
        all_pending = result.scalars().all()
        for d in all_pending:
            if d.swift_reference and d.swift_reference.upper() in description.upper():
                deposit = d
                break

    # If not matched by reference, try by circle_payment_id
    if not deposit and circle_payment_id:
        result = await db.execute(
            select(CircleWireDeposit).where(
                CircleWireDeposit.circle_payment_id == circle_payment_id
            )
        )
        deposit = result.scalar_one_or_none()

    if not deposit:
        logger.warning("No matching CircleWireDeposit found for ref=%s", description)
        return {
            "status": "unmatched",
            "message": "No pending wire deposit matched this reference",
            "circle_payment_id": circle_payment_id,
        }

    # Update deposit with received data
    deposit.status = CircleWireDepositStatus.RECEIVED.value
    deposit.amount_usdc = amount_usdc
    deposit.circle_payment_id = circle_payment_id
    deposit.circle_webhook_data = data

    # FX rate approximation (EUR→USDC)
    if deposit.amount_eur and amount_usdc:
        try:
            deposit.fx_rate = (amount_usdc / deposit.amount_eur).quantize(Decimal("0.00000001"))
        except Exception:
            pass

    # Update linked fiat deposit
    if deposit.fiat_deposit_id:
        result2 = await db.execute(
            select(FiatDeposit).where(FiatDeposit.id == deposit.fiat_deposit_id)
        )
        fiat = result2.scalar_one_or_none()
        if fiat:
            fiat.status = FiatDepositStatus.RECEIVED.value

    await db.commit()
    await db.refresh(deposit)

    logger.info(
        "Wire deposit matched & updated: %s | USDC: %s | ref: %s",
        deposit.id, amount_usdc, deposit.swift_reference,
    )

    # Trigger auto-settlement if wallet configured
    if deposit.settlement_wallet:
        settlement_result = await settle_wire_deposit(db, deposit.id)
        return {
            "status": "received_and_settling",
            "deposit_id": deposit.id,
            "swift_reference": deposit.swift_reference,
            "amount_usdc": str(amount_usdc),
            "settlement": settlement_result,
        }

    return {
        "status": "received",
        "deposit_id": deposit.id,
        "swift_reference": deposit.swift_reference,
        "amount_usdc": str(amount_usdc),
    }


async def _handle_payment_confirmed(db: AsyncSession, data: dict, event_type: str) -> dict:
    """Handle payment.paid events — same logic as wire but for payment intents."""
    circle_payment_id = data.get("id", "")
    result = await db.execute(
        select(CircleWireDeposit).where(
            CircleWireDeposit.circle_payment_id == circle_payment_id
        )
    )
    deposit = result.scalar_one_or_none()
    if not deposit:
        return {"status": "ignored", "reason": "no matching deposit"}

    amount_data = data.get("amount", {})
    amount_usdc = Decimal(str(amount_data.get("amount", "0"))) if amount_data else Decimal("0")

    deposit.status = CircleWireDepositStatus.RECEIVED.value
    deposit.amount_usdc = amount_usdc
    deposit.circle_webhook_data = data
    await db.commit()

    return {"status": "received", "deposit_id": deposit.id}


# ─── 5. Auto-Settlement ───────────────────────────────────────────────────────

async def settle_wire_deposit(db: AsyncSession, deposit_id: str) -> dict:
    """
    Transfer USDC from Circle wallet to our Master Wallet (ERC-20).
    Uses Circle Transfers API.
    """
    result = await db.execute(
        select(CircleWireDeposit).where(CircleWireDeposit.id == deposit_id)
    )
    deposit = result.scalar_one_or_none()
    if not deposit:
        return {"error": "Deposit not found"}

    if deposit.status not in (
        CircleWireDepositStatus.RECEIVED.value,
        CircleWireDepositStatus.PENDING.value,
    ):
        return {"error": f"Cannot settle deposit in status: {deposit.status}"}

    if not deposit.settlement_wallet:
        return {"error": "No settlement wallet configured"}

    if not _is_configured():
        return {"error": "Circle API key not configured"}

    amount_usdc = deposit.amount_usdc or deposit.amount_eur
    if not amount_usdc or amount_usdc <= 0:
        return {"error": "Invalid USDC amount"}

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            payload: dict[str, Any] = {
                "idempotencyKey": str(uuid.uuid4()),
                "source": {
                    "type": "wallet",
                    "id": settings.circle_wallet_id or settings.circle_wallet_set_id,
                },
                "destination": {
                    "type": "blockchain",
                    "address": deposit.settlement_wallet,
                    "chain": "ETH",
                },
                "amount": {
                    "amount": str(amount_usdc),
                    "currency": "USD",
                },
            }
            resp = await client.post(
                f"{CIRCLE_API_BASE}/transfers",
                json=payload,
                headers=_circle_headers(),
            )

            if resp.status_code in (200, 201):
                resp_data = resp.json().get("data", {})
                tx_hash = resp_data.get("transactionHash") or resp_data.get("id", "")
                deposit.status = CircleWireDepositStatus.SETTLED.value
                deposit.settlement_tx_hash = tx_hash
                await db.commit()
                logger.info(
                    "Circle wire settled: %s | %s USDC → %s | tx: %s",
                    deposit.id, amount_usdc, deposit.settlement_wallet, tx_hash,
                )
                return {
                    "status": "settled",
                    "tx_hash": tx_hash,
                    "amount_usdc": str(amount_usdc),
                    "destination": deposit.settlement_wallet,
                }
            else:
                error_msg = f"Circle transfer failed: {resp.status_code} — {resp.text[:300]}"
                logger.error(error_msg)
                deposit.notes = (deposit.notes or "") + f"\nSettlement error: {error_msg}"
                await db.commit()
                return {"error": error_msg}

    except Exception as exc:
        logger.error("Settlement exception: %s", exc)
        return {"error": str(exc)}


# ─── 6. List & Get ────────────────────────────────────────────────────────────

async def list_wire_deposits(
    db: AsyncSession,
    status: str | None = None,
    client_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[CircleWireDeposit]:
    q = select(CircleWireDeposit).order_by(desc(CircleWireDeposit.created_at))
    if status:
        q = q.where(CircleWireDeposit.status == status.upper())
    if client_id:
        q = q.where(CircleWireDeposit.client_id == client_id)
    q = q.limit(limit).offset(offset)
    result = await db.execute(q)
    return list(result.scalars().all())


async def get_wire_deposit(db: AsyncSession, deposit_id: str) -> CircleWireDeposit | None:
    result = await db.execute(
        select(CircleWireDeposit).where(CircleWireDeposit.id == deposit_id)
    )
    return result.scalar_one_or_none()


async def cancel_wire_deposit(db: AsyncSession, deposit_id: str, notes: str | None = None) -> dict:
    deposit = await get_wire_deposit(db, deposit_id)
    if not deposit:
        return {"error": "Deposit not found"}
    if deposit.status != CircleWireDepositStatus.PENDING.value:
        return {"error": f"Cannot cancel deposit in status: {deposit.status}"}
    deposit.status = CircleWireDepositStatus.CANCELLED.value
    if notes:
        deposit.notes = (deposit.notes or "") + f"\n{notes}"
    await db.commit()
    return {"status": "cancelled", "deposit_id": deposit_id}


# ─── 7. Dashboard Summary ─────────────────────────────────────────────────────

async def get_circle_summary(db: AsyncSession) -> dict:
    """Return a summary dict for dashboard display."""
    from sqlalchemy import func as sqlfunc

    result = await db.execute(
        select(
            CircleWireDeposit.status,
            sqlfunc.count(CircleWireDeposit.id).label("count"),
            sqlfunc.coalesce(sqlfunc.sum(CircleWireDeposit.amount_eur), 0).label("total_eur"),
            sqlfunc.coalesce(sqlfunc.sum(CircleWireDeposit.amount_usdc), 0).label("total_usdc"),
        ).group_by(CircleWireDeposit.status)
    )
    rows = result.all()
    summary: dict[str, Any] = {
        "by_status": {},
        "total_count": 0,
        "total_eur": Decimal("0"),
        "total_usdc": Decimal("0"),
    }
    for row in rows:
        summary["by_status"][row.status] = {
            "count": row.count,
            "total_eur": str(row.total_eur),
            "total_usdc": str(row.total_usdc),
        }
        summary["total_count"] += row.count
        summary["total_eur"] += Decimal(str(row.total_eur))
        summary["total_usdc"] += Decimal(str(row.total_usdc))

    summary["total_eur"] = str(summary["total_eur"])
    summary["total_usdc"] = str(summary["total_usdc"])
    return summary
