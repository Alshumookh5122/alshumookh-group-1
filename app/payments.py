from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit_service import log_event
from app.config import settings
from app.database import get_db
from app.deps import AdminKey
from app.ledger_service import confirm_ledger_order, create_ledger_order, get_order, qr_url
from app.models import Network, PaymentOrder, Provider
from app.provider_service import get_provider
from app.schemas import (
    LedgerManualConfirm,
    LedgerOrderCreate,
    LedgerOrderResponse,
    LedgerPaymentStatus,
    OrderCreate,
    OrderRead,
    WidgetUrlRequest,
    WidgetUrlResponse,
)

router = APIRouter(prefix="/payments", tags=["payments"])


def clean_amount(value: Decimal | None) -> str:
    if value is None:
        return "0"
    return format(value.normalize(), "f")


def get_treasury_wallet(network: Network) -> str:
    if network == Network.ETHEREUM:
        address = (
            getattr(settings, "eth_treasury_address", None)
            or getattr(settings, "treasury_wallet_address", None)
            or getattr(settings, "default_wallet_address", None)
        )
    elif network == Network.TRON:
        address = (
            getattr(settings, "tron_treasury_address", None)
            or getattr(settings, "treasury_wallet_address", None)
            or getattr(settings, "default_wallet_address", None)
        )
    else:
        address = None

    if not address:
        raise HTTPException(
            status_code=400,
            detail=f"Treasury wallet address is not configured for {network.value}",
        )

    return address


def order_to_read(order: PaymentOrder) -> OrderRead:
    return OrderRead(
        id=str(order.id),
        external_id=order.external_id,
        provider=order.provider,
        side=order.side,
        status=order.status,
        network=order.network,
        fiat_currency=order.fiat_currency,
        crypto_currency=order.crypto_currency,
        fiat_amount=order.fiat_amount,
        crypto_amount=order.crypto_amount,
        user_wallet_address=order.user_wallet_address,
        treasury_wallet_address=order.treasury_wallet_address,
        payment_reference=order.payment_reference,
        tx_hash=order.tx_hash,
        created_at=order.created_at,
    )


@router.post("/transak/widget-url", response_model=WidgetUrlResponse)
async def create_transak_widget_url(payload: WidgetUrlRequest):
    provider = await get_provider(Provider.TRANSAK)
    widget_url = await provider.create_widget_url(
        payload.model_dump(mode="json", exclude_none=True)
    )
    return WidgetUrlResponse(widget_url=widget_url)


@router.post("/orders", response_model=OrderRead)
async def create_order(payload: OrderCreate, db: AsyncSession = Depends(get_db)):
    treasury_wallet_address = get_treasury_wallet(payload.network)

    order = PaymentOrder(
        external_id=payload.external_id,
        provider=payload.provider,
        side=payload.side,
        network=payload.network,
        fiat_currency=payload.fiat_currency,
        crypto_currency=payload.crypto_currency.upper(),
        fiat_amount=payload.fiat_amount,
        crypto_amount=payload.crypto_amount,
        user_wallet_address=payload.user_wallet_address,
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
            "network": order.network.value,
            "crypto_amount": str(order.crypto_amount),
            "crypto_currency": order.crypto_currency,
            "user_wallet_address": order.user_wallet_address,
            "treasury_wallet_address": order.treasury_wallet_address,
        },
        order.id,
    )

    return order_to_read(order)


@router.get("/orders/{order_id}", response_model=OrderRead)
async def read_order(order_id: str, db: AsyncSession = Depends(get_db)):
    return order_to_read(await get_order(db, order_id))


@router.post("/ledger/order", response_model=LedgerOrderResponse)
async def create_ledger_payment_order(
    payload: LedgerOrderCreate,
    db: AsyncSession = Depends(get_db),
):
    return await create_ledger_order(db, payload)


@router.get("/ledger/status/{order_id}", response_model=LedgerPaymentStatus)
async def ledger_payment_status(order_id: str, db: AsyncSession = Depends(get_db)):
    order = await get_order(db, order_id)
    return LedgerPaymentStatus(
        id=str(order.id),
        status=order.status,
        network=order.network,
        expected_amount=order.crypto_amount,
        treasury_wallet_address=order.treasury_wallet_address,
        tx_hash=order.tx_hash,
    )


@router.post("/ledger/confirm", response_model=OrderRead)
async def ledger_manual_confirm(
    payload: LedgerManualConfirm,
    _: AdminKey,
    db: AsyncSession = Depends(get_db),
):
    order = await confirm_ledger_order(db, payload.order_id, payload.tx_hash, payload.note)
    return order_to_read(order)


def payment_page_html(order: PaymentOrder) -> str:
    if not order.treasury_wallet_address:
        raise HTTPException(status_code=400, detail="Order has no treasury wallet address")

    raw_amount = order.crypto_amount or Decimal("0")
    amount = clean_amount(raw_amount)

    qr = qr_url(
        order.treasury_wallet_address,
        raw_amount,
        order.network,
        order.crypto_currency,
    )

    status = order.status.value

    explorer = ""
    if order.tx_hash:
        if order.network.value == "ethereum":
            explorer = f"https://etherscan.io/tx/{order.tx_hash}"
        elif order.network.value == "tron":
            explorer = f"https://tronscan.org/#/transaction/{order.tx_hash}"

    return f"""
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>AL SHUMOOKH Secure Payment</title>
  <style>
    :root {{ --bg:#07111f; --card:#101c2f; --muted:#8ea0b8; --text:#eef5ff; --gold:#d7b46a; --green:#37d67a; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; font-family:Inter, Arial, sans-serif; background:radial-gradient(circle at top,#1a3156 0%,var(--bg) 45%,#050a12 100%); color:var(--text); }}
    .wrap {{ min-height:100vh; display:flex; align-items:center; justify-content:center; padding:28px; }}
    .card {{ width:100%; max-width:980px; background:rgba(16,28,47,.95); border:1px solid rgba(255,255,255,.08); border-radius:28px; overflow:hidden; box-shadow:0 30px 90px rgba(0,0,0,.45); }}
    .hero {{ padding:34px; background:linear-gradient(135deg,rgba(215,180,106,.22),rgba(26,49,86,.55)); display:flex; justify-content:space-between; gap:20px; }}
    .brand {{ font-size:14px; letter-spacing:.16em; color:var(--gold); font-weight:800; }}
    h1 {{ margin:10px 0 0; font-size:34px; }}
    .badge {{ padding:8px 12px; border-radius:999px; background:rgba(55,214,122,.15); color:var(--green); font-weight:800; height:max-content; }}
    .content {{ display:grid; grid-template-columns:1fr 320px; gap:28px; padding:34px; }}
    .box {{ background:rgba(255,255,255,.04); border:1px solid rgba(255,255,255,.08); border-radius:20px; padding:22px; margin-bottom:18px; }}
    .label {{ color:var(--muted); font-size:13px; text-transform:uppercase; letter-spacing:.08em; margin-bottom:8px; }}
    .value {{ font-size:22px; font-weight:800; word-break:break-word; }}
    .address {{ font-family:ui-monospace, Menlo, monospace; font-size:15px; line-height:1.55; color:#d8e6ff; word-break:break-all; }}
    button {{ cursor:pointer; border:none; border-radius:14px; padding:13px 16px; font-weight:800; background:var(--gold); color:#111; margin-top:12px; }}
    .qr {{ text-align:center; }}
    .qr img {{ width:260px; height:260px; background:white; padding:12px; border-radius:18px; }}
    .warning {{ color:#ffcf7a; font-size:14px; line-height:1.55; }}
    .muted {{ color:var(--muted); font-size:14px; line-height:1.6; }}
    .footer {{ padding:0 34px 34px; color:var(--muted); font-size:13px; }}
    a {{ color:#8bc7ff; }}
    @media (max-width:820px) {{ .content {{ grid-template-columns:1fr; }} .hero {{ display:block; }} h1 {{ font-size:28px; }} }}
  </style>
</head>
<body>
<div class="wrap"><div class="card">
  <div class="hero">
    <div>
      <div class="brand">AL SHUMOOKH GROUP</div>
      <h1>Secure Ledger Payment</h1>
      <p class="muted">Send only the exact token and network shown below.</p>
    </div>
    <div class="badge">{status}</div>
  </div>

  <div class="content">
    <div>
      <div class="box"><div class="label">Amount</div><div class="value">{amount} {order.crypto_currency}</div></div>
      <div class="box"><div class="label">Network</div><div class="value">{order.network.value.upper()}</div></div>
      <div class="box">
        <div class="label">Ledger Treasury Address</div>
        <div class="address" id="addr">{order.treasury_wallet_address}</div>
        <button onclick="copyAddress()">Copy Address</button>
      </div>
      <div class="box"><div class="label">Payment Reference</div><div class="value">{order.payment_reference or str(order.id)}</div></div>
      <div class="box warning">Important: USDT on Ethereum must be ERC-20. USDT on Tron must be TRC-20.</div>
      {f'<div class="box"><div class="label">Transaction</div><a href="{explorer}" target="_blank">View transaction</a></div>' if explorer else ''}
    </div>

    <div class="qr">
      <img src="{qr}" alt="Payment QR"/>
      <p class="muted">Scan or copy the address. Keep this page open until payment is confirmed.</p>
    </div>
  </div>

  <div class="footer">Order ID: {order.id} • Status endpoint: /api/v1/payments/ledger/status/{order.id}</div>
</div></div>

<script>
function copyAddress() {{
  navigator.clipboard.writeText(document.getElementById('addr').innerText);
  alert('Address copied');
}}
setInterval(async () => {{
  try {{
    const r = await fetch('/api/v1/payments/ledger/status/{order.id}');
    const j = await r.json();
    if (j.status === 'COMPLETED') location.reload();
  }} catch(e) {{}}
}}, 15000);
</script>
</body>
</html>
"""


@router.get("/pay/{order_id}", response_class=HTMLResponse, include_in_schema=False)
async def public_payment_page(order_id: str, db: AsyncSession = Depends(get_db)):
    order = await get_order(db, order_id)
    return HTMLResponse(payment_page_html(order))


@router.get("/pay/mock", response_class=HTMLResponse, include_in_schema=False)
async def mock_payment_page():
    return HTMLResponse("<h1>Transak Mock Payment</h1><p>Transak is in mock mode until partner approval is completed.</p>")
