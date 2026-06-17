"""
Top-Up Engine Service
=====================
Handles creation and processing of top-up requests for prepaid cards.

Flow:
  Provider → POST /topup/request {card_number, amount}
           → validate card → credit wallet balance → return success
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    TopUpCard,
    TopUpCardStatus,
    TopUpTransaction,
    TopUpTransactionStatus,
    TopUpWallet,
    TopUpWalletStatus,
)


# ─── Wallet Operations ────────────────────────────────────────────────────────

async def create_wallet(
    db: AsyncSession,
    name: str,
    currency: str = "USDT",
    network: str = "ethereum",
    blockchain_address: str | None = None,
    notes: str | None = None,
) -> TopUpWallet:
    wallet = TopUpWallet(
        id=str(uuid.uuid4()),
        name=name,
        currency=currency.upper(),
        network=network,
        blockchain_address=blockchain_address,
        balance=Decimal("0"),
        status=TopUpWalletStatus.ACTIVE.value,
        notes=notes,
    )
    db.add(wallet)
    await db.commit()
    await db.refresh(wallet)
    return wallet


async def get_wallet(db: AsyncSession, wallet_id: str) -> TopUpWallet | None:
    result = await db.execute(select(TopUpWallet).where(TopUpWallet.id == wallet_id))
    return result.scalar_one_or_none()


async def list_wallets(db: AsyncSession) -> list[TopUpWallet]:
    result = await db.execute(
        select(TopUpWallet).order_by(TopUpWallet.created_at.desc())
    )
    return list(result.scalars().all())


async def update_wallet_status(
    db: AsyncSession, wallet_id: str, status: str
) -> TopUpWallet:
    wallet = await get_wallet(db, wallet_id)
    if not wallet:
        raise ValueError(f"Wallet {wallet_id} not found")
    wallet.status = status
    await db.commit()
    await db.refresh(wallet)
    return wallet


# ─── Card Operations ───────────────────────────────────────────────────────────

async def create_card(
    db: AsyncSession,
    card_number: str,
    wallet_id: str,
    holder_name: str | None = None,
    provider_name: str | None = None,
    notes: str | None = None,
) -> TopUpCard:
    # Validate wallet exists and is active
    wallet = await get_wallet(db, wallet_id)
    if not wallet:
        raise ValueError(f"Wallet {wallet_id} not found")
    if wallet.status != TopUpWalletStatus.ACTIVE.value:
        raise ValueError(f"Wallet {wallet_id} is not active")

    # Check card number uniqueness
    existing = await db.execute(
        select(TopUpCard).where(TopUpCard.card_number == card_number)
    )
    if existing.scalar_one_or_none():
        raise ValueError(f"Card number {card_number} already exists")

    card = TopUpCard(
        id=str(uuid.uuid4()),
        card_number=card_number,
        wallet_id=wallet_id,
        holder_name=holder_name,
        provider_name=provider_name,
        status=TopUpCardStatus.ACTIVE.value,
        notes=notes,
    )
    db.add(card)
    await db.commit()
    await db.refresh(card)
    return card


async def get_card_by_number(db: AsyncSession, card_number: str) -> TopUpCard | None:
    result = await db.execute(
        select(TopUpCard).where(TopUpCard.card_number == card_number)
    )
    return result.scalar_one_or_none()


async def get_card(db: AsyncSession, card_id: str) -> TopUpCard | None:
    result = await db.execute(select(TopUpCard).where(TopUpCard.id == card_id))
    return result.scalar_one_or_none()


async def list_cards(db: AsyncSession) -> list[TopUpCard]:
    result = await db.execute(
        select(TopUpCard).order_by(TopUpCard.created_at.desc())
    )
    return list(result.scalars().all())


async def update_card_status(
    db: AsyncSession, card_id: str, status: str
) -> TopUpCard:
    card = await get_card(db, card_id)
    if not card:
        raise ValueError(f"Card {card_id} not found")
    card.status = status
    await db.commit()
    await db.refresh(card)
    return card


# ─── Top-Up Processing ─────────────────────────────────────────────────────────

async def process_topup(
    db: AsyncSession,
    card_number: str,
    amount: Decimal,
    currency: str = "USDT",
    provider_name: str | None = None,
    provider_ref: str | None = None,
    raw_request: dict | None = None,
) -> TopUpTransaction:
    """
    Main top-up entry point called by the provider.
    1. Validates card exists and is active
    2. Validates wallet is active
    3. Credits wallet balance
    4. Records transaction as SUCCESS
    Returns the TopUpTransaction record.
    """
    amount = Decimal(str(amount)).quantize(Decimal("0.000001"), rounding=ROUND_DOWN)

    if amount <= 0:
        raise ValueError("Top-up amount must be greater than zero")

    # ── Validate card ──────────────────────────────────────────────────────────
    card = await get_card_by_number(db, card_number)

    if not card:
        txn = _build_failed_txn(
            card_id=None,
            card_number=card_number,
            amount=amount,
            currency=currency,
            provider_name=provider_name,
            provider_ref=provider_ref,
            raw_request=raw_request,
            reason="Card not found — rejected by system",
        )
        db.add(txn)
        await db.commit()
        await db.refresh(txn)
        return txn

    if card.status != TopUpCardStatus.ACTIVE.value:
        txn = _build_failed_txn(
            card_id=card.id,
            card_number=card_number,
            amount=amount,
            currency=currency,
            provider_name=provider_name,
            provider_ref=provider_ref,
            raw_request=raw_request,
            reason=f"Card is {card.status} — transaction rejected",
        )
        db.add(txn)
        await db.commit()
        await db.refresh(txn)
        return txn

    # ── Validate wallet ────────────────────────────────────────────────────────
    wallet = await get_wallet(db, card.wallet_id)

    if not wallet or wallet.status != TopUpWalletStatus.ACTIVE.value:
        txn = _build_failed_txn(
            card_id=card.id,
            card_number=card_number,
            amount=amount,
            currency=currency,
            provider_name=provider_name,
            provider_ref=provider_ref,
            raw_request=raw_request,
            reason="Associated wallet is inactive or missing",
        )
        db.add(txn)
        await db.commit()
        await db.refresh(txn)
        return txn

    # ── Credit wallet balance ──────────────────────────────────────────────────
    wallet.balance = (wallet.balance + amount).quantize(
        Decimal("0.000001"), rounding=ROUND_DOWN
    )

    # ── Record successful transaction ──────────────────────────────────────────
    txn = TopUpTransaction(
        id=str(uuid.uuid4()),
        card_id=card.id,
        card_number=card_number,
        provider_name=provider_name or card.provider_name,
        amount=amount,
        currency=currency.upper(),
        status=TopUpTransactionStatus.SUCCESS.value,
        provider_ref=provider_ref,
        raw_request=raw_request,
    )
    db.add(txn)
    await db.commit()
    await db.refresh(txn)
    return txn


async def list_transactions(
    db: AsyncSession,
    card_id: str | None = None,
    limit: int = 100,
) -> list[TopUpTransaction]:
    q = select(TopUpTransaction).order_by(TopUpTransaction.created_at.desc()).limit(limit)
    if card_id:
        q = q.where(TopUpTransaction.card_id == card_id)
    result = await db.execute(q)
    return list(result.scalars().all())


# ─── Helpers ───────────────────────────────────────────────────────────────────

def _build_failed_txn(
    card_id: str | None,
    card_number: str,
    amount: Decimal,
    currency: str,
    provider_name: str | None,
    provider_ref: str | None,
    raw_request: dict | None,
    reason: str,
) -> TopUpTransaction:
    return TopUpTransaction(
        id=str(uuid.uuid4()),
        card_id=card_id or "00000000-0000-0000-0000-000000000000",
        card_number=card_number,
        provider_name=provider_name,
        amount=amount,
        currency=currency.upper(),
        status=TopUpTransactionStatus.REJECTED.value,
        failure_reason=reason,
        provider_ref=provider_ref,
        raw_request=raw_request,
    )
