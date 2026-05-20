"""
ledger_service.py
─────────────────
Ledger (direct crypto-payment) order helpers.
These are used by payments.py for the /ledger/* endpoints.
"""
from __future__ import annotations

import secrets
import uuid
from decimal import Decimal
from urllib.parse import quote

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, cast, String
from fastapi import HTTPException

from app.config import settings
from app.models import Network, OrderStatus, PaymentOrder, Provider


# ── Wallet helpers ─────────────────────────────────────────────────────────────

_NETWORK_WALLETS: dict[Network, str | None] = {
    Network.ETHEREUM: getattr(settings, "master_wallet_ethereum", None),
    Network.BASE:     getattr(settings, "master_wallet_base", None),
    Network.TRON:     getattr(settings, "master_wallet_tron", None),
}

_FALLBACK_ETHEREUM_WALLET = "0xBD682cfD8382a90adfDd6745780D3D7959c4d939"


def _treasury_wallet(network: Network) -> str:
    wallet = _NETWORK_WALLETS.get(network)
    if wallet:
        return wallet
    # Fallback to Ethereum wallet for all EVM chains
    return getattr(settings, "master_wallet_ethereum", None) or _FALLBACK_ETHEREUM_WALLET


# ── QR-code URL ────────────────────────────────────────────────────────────────

def qr_url(
    wallet_address: str,
    amount: Decimal | None,
    network: Network,
    crypto_currency: str = "USDC",
) -> str:
    """
    Return a QRServer.com URL encoding a structured payment payload.
    Used on the hosted payment page so the payer can scan and send.
    """
    amount_str = f"{amount:.6f}".rstrip("0").rstrip(".") if amount else "0"
    payload = "\n".join(
        [
            "ALSHUMOOKH GLOBAL BANKING FINANCE & CREDIT",
            f"Amount: {amount_str} {crypto_currency.upper()}",
            f"Network: {network.value.upper()}",
            f"Wallet: {wallet_address}",
        ]
    )
    return (
        "https://api.qrserver.com/v1/create-qr-code/"
        f"?size=260x260&data={quote(payload)}"
    )


# ── Payment-page URL ───────────────────────────────────────────────────────────

def _payment_url(order_id: str) -> str:
    base = (
        getattr(settings, "public_base_url", None)
        or getattr(settings, "public_app_url", None)
        or "https://api.alshumookh-pay.com"
    )
    return f"{str(base).rstrip('/')}/pay/{order_id}"


def _invoice_url(order_id: str) -> str | None:
    base = (
        getattr(settings, "public_base_url", None)
        or getattr(settings, "public_app_url", None)
        or "https://api.alshumookh-pay.com"
    )
    return f"{str(base).rstrip('/')}/invoice/{order_id}"


# ── Create ledger order ────────────────────────────────────────────────────────

async def create_ledger_order(db: AsyncSession, payload) -> dict:
    """
    Create a PaymentOrder for a direct on-chain (ledger) payment.

    `payload` should be a LedgerOrderCreate Pydantic model (or dict-like).
    Returns a dict that maps directly to LedgerOrderResponse.
    """
    network: Network = getattr(payload, "network", Network.ETHEREUM)
    treasury_wallet = _treasury_wallet(network)

    payment_ref = (
        getattr(payload, "external_id", None)
        or secrets.token_hex(8).upper()
    )

    order = PaymentOrder(
        id=str(uuid.uuid4()),
        provider=Provider.LEDGER,
        status=OrderStatus.PENDING,
        network=network,
        crypto_currency=getattr(payload, "crypto_currency", "USDC").upper(),
        crypto_amount=getattr(payload, "crypto_amount", None),
        fiat_currency=getattr(payload, "fiat_currency", "USD").upper(),
        fiat_amount=getattr(payload, "fiat_amount", None),
        payer_email=getattr(payload, "payer_email", None)
                    or getattr(payload, "customer_email", None),
        external_id=getattr(payload, "external_id", None),
        payment_reference=payment_ref,
        user_wallet_address=treasury_wallet,
        treasury_wallet_address=treasury_wallet,
        customer_wallet_address=getattr(payload, "customer_wallet_address", None),
    )

    db.add(order)
    await db.commit()
    await db.refresh(order)

    amount = order.crypto_amount
    payment_url = _payment_url(str(order.id))
    order_qr_url = qr_url(treasury_wallet, amount, network, order.crypto_currency)
    invoice_url = _invoice_url(str(order.id))

    warning = ""
    if not getattr(settings, "master_wallet_ethereum", None):
        warning = (
            "Treasury wallet is using a fallback address. "
            "Set MASTER_WALLET_ETHEREUM in your environment."
        )

    return {
        "id": str(order.id),
        "status": order.status,
        "network": order.network,
        "crypto_currency": order.crypto_currency,
        "crypto_amount": order.crypto_amount,
        "treasury_wallet_address": treasury_wallet,
        "payment_reference": payment_ref,
        "payment_url": payment_url,
        "qr_url": order_qr_url,
        "invoice_url": invoice_url,
        "receipt_url": None,
        "warning": warning,
    }


# ── Confirm ledger order ───────────────────────────────────────────────────────

async def confirm_ledger_order(
    db: AsyncSession,
    order_id: str,
    tx_hash: str,
    note: str | None = None,
) -> PaymentOrder:
    """
    Admin-triggered manual confirmation of a ledger order.
    Marks the order as COMPLETED and records the tx_hash.
    """
    result = await db.execute(
        select(PaymentOrder).where(cast(PaymentOrder.id, String) == str(order_id))
    )
    order: PaymentOrder | None = result.scalar_one_or_none()

    if not order:
        raise HTTPException(status_code=404, detail=f"Order {order_id} not found")

    if order.status == OrderStatus.COMPLETED:
        raise HTTPException(
            status_code=409,
            detail="Order is already COMPLETED",
        )

    order.tx_hash = tx_hash
    order.status = OrderStatus.COMPLETED

    if note:
        existing = order.failure_reason or ""
        order.failure_reason = (f"{existing}\nAdmin note: {note}").strip()

    await db.commit()
    await db.refresh(order)
    return order
