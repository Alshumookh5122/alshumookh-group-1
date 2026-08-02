"""
Fiat Deposit Service — manage incoming EUR payments via SEPA/SWIFT/Local.
"""
from __future__ import annotations

import logging
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    FiatDeposit,
    FiatDepositStatus,
    FiatPaymentMethod,
    OtcQuote,
    TransferRequest,
    TransferRequestStatus,
)

logger = logging.getLogger(__name__)


# ─── Fiat Deposit ─────────────────────────────────────────────────────────────

async def register_deposit(
    db: AsyncSession,
    amount_eur: Decimal,
    sender_name: str | None = None,
    sender_bank: str | None = None,
    sender_iban: str | None = None,
    payment_method: str = FiatPaymentMethod.SWIFT.value,
    bank_reference: str | None = None,
    client_id: str | None = None,
    notes: str | None = None,
) -> FiatDeposit:
    """Register a new incoming EUR deposit."""
    deposit = FiatDeposit(
        amount_eur=amount_eur,
        sender_name=sender_name,
        sender_bank=sender_bank,
        sender_iban=sender_iban,
        payment_method=payment_method,
        bank_reference=bank_reference,
        client_id=client_id,
        status=FiatDepositStatus.PENDING.value,
        notes=notes,
    )
    db.add(deposit)
    await db.commit()
    await db.refresh(deposit)
    logger.info("Fiat deposit registered: %s | %.6f EUR via %s",
                deposit.reference, amount_eur, payment_method)
    return deposit


async def confirm_deposit(db: AsyncSession, deposit_id: str) -> FiatDeposit:
    """Mark a deposit as RECEIVED (bank confirmed)."""
    result = await db.execute(select(FiatDeposit).where(FiatDeposit.id == deposit_id))
    deposit = result.scalar_one_or_none()
    if not deposit:
        raise ValueError("Deposit not found")
    if deposit.status != FiatDepositStatus.PENDING.value:
        raise ValueError(f"Deposit is {deposit.status}, cannot confirm")
    deposit.status = FiatDepositStatus.RECEIVED.value
    await db.commit()
    await db.refresh(deposit)
    return deposit


async def match_deposit(db: AsyncSession, deposit_id: str, transfer_request_id: str) -> FiatDeposit:
    """Link deposit to a TransferRequest and mark it MATCHED."""
    result = await db.execute(select(FiatDeposit).where(FiatDeposit.id == deposit_id))
    deposit = result.scalar_one_or_none()
    if not deposit:
        raise ValueError("Deposit not found")
    if deposit.status not in (FiatDepositStatus.PENDING.value, FiatDepositStatus.RECEIVED.value):
        raise ValueError(f"Deposit is {deposit.status}, cannot match")

    result2 = await db.execute(
        select(TransferRequest).where(TransferRequest.id == transfer_request_id)
    )
    tr = result2.scalar_one_or_none()
    if not tr:
        raise ValueError("TransferRequest not found")

    deposit.status = FiatDepositStatus.MATCHED.value
    tr.fiat_deposit_id = deposit_id
    tr.status = TransferRequestStatus.EUR_RECEIVED.value
    await db.commit()
    await db.refresh(deposit)
    return deposit


async def refund_deposit(db: AsyncSession, deposit_id: str, notes: str | None = None) -> FiatDeposit:
    """Mark a deposit as REFUNDED."""
    result = await db.execute(select(FiatDeposit).where(FiatDeposit.id == deposit_id))
    deposit = result.scalar_one_or_none()
    if not deposit:
        raise ValueError("Deposit not found")
    deposit.status = FiatDepositStatus.REFUNDED.value
    if notes:
        deposit.notes = notes
    await db.commit()
    await db.refresh(deposit)
    return deposit


# ─── Transfer Request ─────────────────────────────────────────────────────────

async def create_transfer_request(
    db: AsyncSession,
    amount_eur: Decimal,
    recipient_wallet: str,
    recipient_network: str = "TRC20",
    client_id: str | None = None,
    sender_name: str | None = None,
    notes: str | None = None,
) -> TransferRequest:
    """Create a new Transfer Request (starts lifecycle)."""
    tr = TransferRequest(
        client_id=client_id,
        amount_eur=amount_eur,
        recipient_wallet=recipient_wallet,
        recipient_network=recipient_network,
        sender_name=sender_name,
        status=TransferRequestStatus.CREATED.value,
        notes=notes,
    )
    db.add(tr)
    await db.commit()
    await db.refresh(tr)
    logger.info("TransferRequest created: %s | %.6f EUR → %s (%s)",
                tr.reference, amount_eur, recipient_wallet[:16], recipient_network)
    return tr


async def attach_quote_to_request(
    db: AsyncSession,
    transfer_request_id: str,
    otc_quote_id: str,
) -> TransferRequest:
    """Link an OTC quote to a transfer request."""
    result = await db.execute(
        select(TransferRequest).where(TransferRequest.id == transfer_request_id)
    )
    tr = result.scalar_one_or_none()
    if not tr:
        raise ValueError("TransferRequest not found")

    result2 = await db.execute(select(OtcQuote).where(OtcQuote.id == otc_quote_id))
    quote = result2.scalar_one_or_none()
    if not quote:
        raise ValueError("OtcQuote not found")

    tr.otc_quote_id = otc_quote_id
    tr.amount_usdt = quote.amount_usdt
    tr.status = TransferRequestStatus.QUOTE_APPROVED.value
    await db.commit()
    await db.refresh(tr)
    return tr


async def advance_transfer_status(
    db: AsyncSession,
    transfer_request_id: str,
    new_status: str,
    outbound_transfer_id: str | None = None,
) -> TransferRequest:
    """Move a TransferRequest to the next status."""
    result = await db.execute(
        select(TransferRequest).where(TransferRequest.id == transfer_request_id)
    )
    tr = result.scalar_one_or_none()
    if not tr:
        raise ValueError("TransferRequest not found")
    tr.status = new_status
    if outbound_transfer_id:
        tr.outbound_transfer_id = outbound_transfer_id
    await db.commit()
    await db.refresh(tr)
    return tr
