from __future__ import annotations

from decimal import Decimal
from urllib.parse import quote

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit_service import log_event
from app.config import settings
from app.models import Network, OrderSide, OrderStatus, PaymentOrder, Provider
from app.schemas import LedgerOrderCreate, LedgerOrderResponse


def public_base_url() -> str:
    return (settings.public_base_url or "https://alshumookh-group-1.onrender.com").rstrip("/")


def ledger_address_for_network(network: Network) -> str:
    if network == Network.ETHEREUM:
        if not settings.eth_treasury_address or settings.eth_treasury_address == "0x0000000000000000000000000000000000000000":
            raise HTTPException(status_code=400, detail="ETH_TREASURY_ADDRESS is not configured")
        return settings.eth_treasury_address
    if network == Network.TRON:
        if not settings.tron_treasury_address or settings.tron_treasury_address.startswith("TXXXX"):
            raise HTTPException(status_code=400, detail="TRON_TREASURY_ADDRESS is not configured")
        return settings.tron_treasury_address
    raise HTTPException(status_code=400, detail="Unsupported network")


def qr_url(address: str, amount: Decimal | None, network: Network, token: str) -> str:
    label = f"AL SHUMOOKH {token} {network.value.upper()}"
    text = f"{token} {network.value.upper()} payment to {address}"
    if amount is not None:
        text += f" amount {amount}"
    payload = quote(f"{label}\n{text}\n{address}")
    return f"https://api.qrserver.com/v1/create-qr-code/?size=260x260&data={payload}"


async def create_ledger_order(db: AsyncSession, payload: LedgerOrderCreate) -> LedgerOrderResponse:
    treasury_address = ledger_address_for_network(payload.network)
    order = PaymentOrder(
        external_id=payload.external_id,
        provider=Provider.LEDGER,
        side=OrderSide.BUY,
        status=OrderStatus.PENDING,
        network=payload.network,
        fiat_currency=payload.fiat_currency,
        crypto_currency=payload.crypto_currency.upper(),
        fiat_amount=payload.fiat_amount,
        crypto_amount=payload.crypto_amount,
        user_wallet_address=payload.customer_wallet_address or "ledger-direct-payment",
        treasury_wallet_address=treasury_address,
        payer_email=str(payload.payer_email) if payload.payer_email else None,
        payment_reference=None,
        quote_json={
            "mode": "ledger_direct",
            "note": "Customer must send funds to the displayed Ledger treasury address. No private key is stored on server.",
        },
    )
    db.add(order)
    await db.flush()
    order.payment_reference = f"ALS-{str(order.id).split('-')[0].upper()}"
    await db.commit()
    await db.refresh(order)
    await log_event(db, "LEDGER_ORDER_CREATED", {"reference": order.payment_reference}, order.id)

    pay_url = f"{public_base_url()}/pay/{order.id}"
    return LedgerOrderResponse(
        id=str(order.id),
        status=order.status,
        network=order.network,
        crypto_currency=order.crypto_currency,
        crypto_amount=order.crypto_amount,
        treasury_wallet_address=treasury_address,
        payment_reference=order.payment_reference or "",
        payment_url=pay_url,
        qr_url=qr_url(treasury_address, order.crypto_amount, order.network, order.crypto_currency),
        warning="Send only the selected token on the selected network to this Ledger address. Wrong-network transfers may be unrecoverable.",
    )


async def get_order(db: AsyncSession, order_id: str) -> PaymentOrder:
    res = await db.execute(select(PaymentOrder).where(PaymentOrder.id == order_id))
    order = res.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return order


async def confirm_ledger_order(db: AsyncSession, order_id: str, tx_hash: str, note: str | None = None) -> PaymentOrder:
    order = await get_order(db, order_id)
    order.status = OrderStatus.COMPLETED
    order.tx_hash = tx_hash
    order.webhook_payload = {"manual_confirmation": True, "tx_hash": tx_hash, "note": note}
    await db.commit()
    await db.refresh(order)
    await log_event(db, "LEDGER_ORDER_MANUALLY_CONFIRMED", {"tx_hash": tx_hash, "note": note}, order.id)
    return order
