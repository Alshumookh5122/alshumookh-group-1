from __future__ import annotations

from decimal import Decimal
from html import escape
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import String, cast, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit_service import log_event
from app.config import settings
from app.database import get_db
from app.deps import AdminKey, ClientApiKey
from app.ledger_service import confirm_ledger_order, create_ledger_order, qr_url
from app.models import Network, OrderSide, PaymentOrder, Provider
from app.schemas import (
    LedgerManualConfirm,
    LedgerOrderCreate,
    LedgerOrderResponse,
    LedgerPaymentStatus,
    OrderCreate,
    OrderRead,
)

router = APIRouter(prefix="/payments", tags=["payments"])

ETHEREUM_LEDGER_WALLET = "0xBD682cfD8382a90adfDd6745780D3D7959c4d939"


def public_base_url() -> str:
    value = (
        getattr(settings, "public_base_url", None)
        or getattr(settings, "public_app_url", None)
        or "https://api.alshumookh-pay.com"
    )
    return str(value).rstrip("/")


def logo_url() -> str:
    configured = getattr(settings, "company_logo_url", None)

    if configured:
        return str(configured)

    return f"{public_base_url()}/static/company-logo.png"


def clean_amount(value: Decimal | None) -> str:
    if value is None:
        return "0"

    value = Decimal(str(value))

    if value == value.to_integral():
        return str(value.to_integral())

    return format(value.normalize(), "f")


def get_treasury_wallet(network: Network) -> str:
    try:
        return settings.get_treasury_address(network.value)
    except ValueError:
        if network == Network.ETHEREUM:
            return ETHEREUM_LEDGER_WALLET

        raise HTTPException(
            status_code=400,
            detail=f"Treasury wallet address is not configured for {network.value}",
        )


async def get_payment_order(db: AsyncSession, order_id: str) -> PaymentOrder:
    result = await db.execute(
        select(PaymentOrder).where(cast(PaymentOrder.id, String) == str(order_id))
    )
    order = result.scalar_one_or_none()

    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    return order


async def get_client_payment_order(
    db: AsyncSession,
    order_id: str,
    client: ClientApiKey,
) -> PaymentOrder:
    result = await db.execute(
        select(PaymentOrder).where(
            cast(PaymentOrder.id, String) == str(order_id),
            PaymentOrder.client_id == client.id,
        )
    )
    order = result.scalar_one_or_none()

    if not order:
        raise HTTPException(status_code=404, detail="Transaction not found")

    return order


def order_to_read(order: PaymentOrder) -> OrderRead:
    return OrderRead(
        id=str(order.id),
        external_id=order.external_id,
        provider=order.provider,
        side=order.side,
        status=order.status,
        network=order.network,
        fiat_currency=order.fiat_currency,
        fiat_amount=order.fiat_amount,
        crypto_currency=order.crypto_currency,
        crypto_amount=order.crypto_amount,
        user_wallet_address=order.user_wallet_address,
        customer_wallet_address=getattr(order, "customer_wallet_address", None),
        treasury_wallet_address=getattr(order, "treasury_wallet_address", None),
        payer_email=getattr(order, "payer_email", None),
        payment_reference=getattr(order, "payment_reference", None),
        coinbase_session_url=getattr(order, "coinbase_session_url", None),
        checkout_url=getattr(order, "checkout_url", None),
        provider_order_id=getattr(order, "provider_order_id", None),
        tx_hash=getattr(order, "tx_hash", None),
        failure_reason=order.failure_reason,
        created_at=order.created_at,
    )


def order_payment_url(order: PaymentOrder) -> str:
    return f"{public_base_url()}/pay/direct/{order.id}"


def order_client_payload(order: PaymentOrder) -> dict:
    return {
        "id": str(order.id),
        "external_id": order.external_id,
        "status": order.status.value,
        "provider": order.provider.value,
        "network": order.network.value,
        "fiat_currency": order.fiat_currency,
        "fiat_amount": str(order.fiat_amount) if order.fiat_amount is not None else None,
        "crypto_currency": order.crypto_currency,
        "crypto_amount": str(order.crypto_amount) if order.crypto_amount is not None else None,
        "treasury_wallet_address": getattr(order, "treasury_wallet_address", None)
        or order.user_wallet_address,
        "payment_reference": getattr(order, "payment_reference", None),
        "tx_hash": getattr(order, "tx_hash", None),
        "payment_url": order_payment_url(order),
        "qr_url": direct_qr_url(order),
        "created_at": order.created_at,
    }


@router.get("/client/orders")
async def client_orders(
    client: ClientApiKey,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(PaymentOrder)
        .where(PaymentOrder.client_id == client.id)
        .order_by(PaymentOrder.created_at.desc())
    )
    orders = result.scalars().all()

    return [order_client_payload(order) for order in orders]


@router.post("/client/direct-payment")
async def create_client_direct_payment(
    payload: OrderCreate,
    client: ClientApiKey,
    db: AsyncSession = Depends(get_db),
):
    treasury_wallet_address = get_treasury_wallet(payload.network)

    order = PaymentOrder(
        client_id=client.id,
        external_id=payload.external_id,
        provider=Provider.MANUAL,
        side=OrderSide.BUY,
        network=payload.network,
        fiat_currency=payload.fiat_currency.upper(),
        fiat_amount=payload.fiat_amount,
        crypto_currency=payload.crypto_currency.upper(),
        crypto_amount=payload.crypto_amount,
        user_wallet_address=treasury_wallet_address,
        customer_wallet_address=getattr(payload, "customer_wallet_address", None),
        treasury_wallet_address=treasury_wallet_address,
        payer_email=str(payload.payer_email) if payload.payer_email else None,
        payment_reference=payload.external_id,
    )

    db.add(order)
    await db.commit()
    await db.refresh(order)

    await log_event(
        db,
        "CLIENT_DIRECT_PAYMENT_CREATED",
        {
            "order_id": str(order.id),
            "external_id": order.external_id,
            "network": order.network.value,
            "crypto_amount": str(order.crypto_amount),
            "crypto_currency": order.crypto_currency,
            "treasury_wallet_address": treasury_wallet_address,
        },
        order.id,
        client_id=client.id,
    )

    return order_client_payload(order)


@router.post("/orders", response_model=OrderRead)
async def create_order(
    payload: OrderCreate,
    client: ClientApiKey,
    db: AsyncSession = Depends(get_db),
):
    configured_wallet = get_treasury_wallet(payload.network)

    treasury_wallet_address = (
        getattr(payload, "treasury_wallet_address", None)
        or payload.user_wallet_address
        or configured_wallet
    )

    order = PaymentOrder(
        client_id=client.id,
        external_id=payload.external_id,
        provider=payload.provider,
        side=payload.side,
        network=payload.network,
        fiat_currency=payload.fiat_currency.upper(),
        fiat_amount=payload.fiat_amount,
        crypto_currency=payload.crypto_currency.upper(),
        crypto_amount=payload.crypto_amount,
        user_wallet_address=payload.user_wallet_address or treasury_wallet_address,
        customer_wallet_address=payload.customer_wallet_address,
        treasury_wallet_address=treasury_wallet_address,
        payer_email=str(payload.payer_email) if payload.payer_email else None,
        payment_reference=payload.external_id,
    )

    db.add(order)
    await db.commit()
    await db.refresh(order)

    await log_event(
        db,
        "ORDER_CREATED",
        {
            "order_id": str(order.id),
            "external_id": order.external_id,
            "provider": order.provider.value,
            "network": order.network.value,
            "fiat_amount": str(order.fiat_amount),
            "fiat_currency": order.fiat_currency,
            "crypto_amount": str(order.crypto_amount),
            "crypto_currency": order.crypto_currency,
            "treasury_wallet_address": order.treasury_wallet_address,
        },
        order.id,
        client_id=client.id,
    )

    return order_to_read(order)


@router.get("/orders/{order_id}", response_model=OrderRead)
async def read_order(
    order_id: str,
    client: ClientApiKey,
    db: AsyncSession = Depends(get_db),
):
    order = await get_client_payment_order(db, order_id, client)
    return order_to_read(order)


@router.post("/ledger/order", response_model=LedgerOrderResponse)
async def create_ledger_payment_order(
    payload: LedgerOrderCreate,
    db: AsyncSession = Depends(get_db),
):
    return await create_ledger_order(db, payload)


@router.get("/ledger/status/{order_id}", response_model=LedgerPaymentStatus)
async def ledger_payment_status(
    order_id: str,
    db: AsyncSession = Depends(get_db),
):
    order = await get_payment_order(db, order_id)

    return LedgerPaymentStatus(
        id=str(order.id),
        status=order.status,
        network=order.network,
        expected_amount=order.crypto_amount,
        treasury_wallet_address=getattr(order, "treasury_wallet_address", None)
        or order.user_wallet_address,
        tx_hash=order.tx_hash,
        payment_reference=getattr(order, "payment_reference", None),
    )


@router.post("/ledger/confirm", response_model=OrderRead)
async def ledger_manual_confirm(
    payload: LedgerManualConfirm,
    _: AdminKey,
    db: AsyncSession = Depends(get_db),
):
    order = await confirm_ledger_order(
        db,
        payload.order_id,
        payload.tx_hash,
        payload.note,
    )
    return order_to_read(order)


@router.get("/moonpay/redirect/{order_id}", include_in_schema=False)
@router.get("/coinbase/redirect/{order_id}", include_in_schema=False, deprecated=True)
async def redirect_to_provider_checkout(
    order_id: str,
    db: AsyncSession = Depends(get_db),
):
    order = await get_payment_order(db, order_id)

    url = getattr(order, "checkout_url", None) or getattr(order, "coinbase_session_url", None)

    if not url:
        raise HTTPException(
            status_code=404,
            detail="Provider checkout URL not found for this order",
        )

    return RedirectResponse(url)


def direct_qr_url(order: PaymentOrder) -> str:
    wallet = (
        getattr(order, "treasury_wallet_address", None)
        or order.user_wallet_address
        or ETHEREUM_LEDGER_WALLET
    )
    amount = clean_amount(order.crypto_amount or Decimal("0"))

    payload = "\n".join(
        [
            "ALSHUMOOKH GLOBAL BANKING FINANCE & CREDIT",
            f"Reference: {getattr(order, 'payment_reference', None) or order.external_id or order.id}",
            f"Amount: {amount} {order.crypto_currency}",
            f"Network: {order.network.value.upper()}",
            f"Wallet: {wallet}",
        ]
    )

    return (
        "https://api.qrserver.com/v1/create-qr-code/"
        f"?size=260x260&data={quote(payload)}"
    )


def explorer_url(order: PaymentOrder) -> str:
    if not order.tx_hash:
        return ""

    if order.network.value == "ethereum":
        return f"https://etherscan.io/tx/{order.tx_hash}"

    if order.network.value == "base":
        return f"https://basescan.org/tx/{order.tx_hash}"

    if order.network.value == "tron":
        return f"https://tronscan.org/#/transaction/{order.tx_hash}"

    return ""


def payment_page_html(order: PaymentOrder) -> str:
    treasury_wallet = (
        getattr(order, "treasury_wallet_address", None)
        or order.user_wallet_address
        or ETHEREUM_LEDGER_WALLET
    )

    raw_amount = order.crypto_amount or Decimal("0")
    amount = clean_amount(raw_amount)
    status = order.status.value
    coinbase_url = getattr(order, "checkout_url", None) or getattr(order, "coinbase_session_url", None)
    explorer = explorer_url(order)

    if coinbase_url:
        qr = qr_url(
            treasury_wallet,
            raw_amount,
            order.network,
            order.crypto_currency,
        )
    else:
        qr = direct_qr_url(order)

    coinbase_button = ""
    if coinbase_url:
        coinbase_button = f"""
        <div class="box">
          <div class="label">Fiat Payment</div>
          <div class="value">MoonPay Commerce</div>
          <a class="button-link" href="{escape(coinbase_url)}" target="_blank" rel="noopener">
            Pay with MoonPay
          </a>
        </div>
        """

    direct_link = f"{public_base_url()}/pay/direct/{order.id}"

    return f"""
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>ALSHUMOOKH GLOBAL BANKING FINANCE & CREDIT Secure Payment</title>
</head>
<body style="margin:0;background:#07111f;color:#eef5ff;font-family:Arial,sans-serif">
  <main style="min-height:100vh;display:flex;align-items:center;justify-content:center;padding:28px">
    <section style="width:100%;max-width:980px;background:#101c2f;border-radius:18px;overflow:hidden">
      <header style="padding:28px;background:#182b47;display:flex;justify-content:space-between;gap:18px">
        <div style="display:flex;gap:14px;align-items:center">
          <img src="{escape(logo_url())}" alt="AL SHUMOOKH GROUP Logo" style="width:92px;height:66px;object-fit:contain;background:#050505;border-radius:8px;padding:6px">
          <div>
            <div style="color:#d7b46a;font-weight:900;font-size:13px">ALSHUMOOKH GLOBAL BANKING FINANCE & CREDIT</div>
            <h1 style="margin:8px 0 0">Secure Payment</h1>
            <p style="color:#8ea0b8;margin:8px 0 0">Pay through MoonPay Commerce or direct crypto wallet transfer.</p>
          </div>
        </div>
        <strong style="color:#37d67a">{escape(status)}</strong>
      </header>

      <section style="display:grid;grid-template-columns:1fr 300px;gap:24px;padding:28px">
        <div>
          {coinbase_button}

          <div style="background:rgba(255,255,255,.05);padding:18px;border-radius:12px;margin-bottom:14px">
            <div style="color:#8ea0b8;font-size:13px">Amount</div>
            <strong style="font-size:24px">{escape(amount)} {escape(order.crypto_currency)}</strong>
          </div>

          <div style="background:rgba(255,255,255,.05);padding:18px;border-radius:12px;margin-bottom:14px">
            <div style="color:#8ea0b8;font-size:13px">Network</div>
            <strong style="font-size:24px">{escape(order.network.value.upper())}</strong>
          </div>

          <div style="background:rgba(255,255,255,.05);padding:18px;border-radius:12px;margin-bottom:14px">
            <div style="color:#8ea0b8;font-size:13px">Ledger Destination Wallet</div>
            <code id="addr" style="display:block;word-break:break-all;color:#d8e6ff;margin-top:8px">{escape(treasury_wallet)}</code>
            <button onclick="copyAddress()" style="margin-top:12px;padding:12px 14px;border:0;border-radius:8px;background:#d7b46a;color:#111;font-weight:800">Copy Wallet</button>
          </div>

          <div style="background:rgba(255,255,255,.05);padding:18px;border-radius:12px;margin-bottom:14px">
            <div style="color:#8ea0b8;font-size:13px">Payment Reference</div>
            <strong>{escape(str(order.payment_reference or order.external_id or order.id))}</strong>
          </div>

          <div style="background:rgba(255,207,122,.08);padding:18px;border-radius:12px;color:#ffcf7a">
            Send only {escape(order.crypto_currency)} on {escape(order.network.value.upper())}. Wrong-network transfers may be unrecoverable.
          </div>

          {f'<div style="background:rgba(255,255,255,.05);padding:18px;border-radius:12px;margin-top:14px"><a href="{escape(explorer)}" target="_blank" rel="noopener" style="color:#8bc7ff">View transaction</a></div>' if explorer else ''}
        </div>

        <aside style="text-align:center">
          <img src="{escape(qr)}" alt="Payment QR" style="width:260px;height:260px;background:white;padding:12px;border-radius:14px">
          <p style="color:#8ea0b8">Scan or copy the wallet address.</p>
          <a href="{escape(direct_link)}" style="color:#8bc7ff;word-break:break-all">{escape(direct_link)}</a>
        </aside>
      </section>

      <footer style="padding:0 28px 28px;color:#8ea0b8;font-size:13px">
        Order ID: {escape(str(order.id))}
      </footer>
    </section>
  </main>

<script>
function copyAddress() {{
  navigator.clipboard.writeText(document.getElementById('addr').innerText);
  alert('Wallet copied');
}}
</script>
</body>
</html>
"""


@router.get("/pay/{order_id}", response_class=HTMLResponse, include_in_schema=False)
async def public_payment_page(order_id: str, db: AsyncSession = Depends(get_db)):
    order = await get_payment_order(db, order_id)
    return HTMLResponse(payment_page_html(order))


@router.get("/pay/direct/{order_id}", response_class=HTMLResponse, include_in_schema=False)
async def public_direct_payment_page(order_id: str, db: AsyncSession = Depends(get_db)):
    order = await get_payment_order(db, order_id)
    return HTMLResponse(payment_page_html(order))
