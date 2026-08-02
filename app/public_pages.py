from __future__ import annotations

from decimal import Decimal
from html import escape
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy import String, cast, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.models import PaymentOrder

router = APIRouter(tags=['public'])
settings = get_settings()


def _public_base_url() -> str:
    return str(getattr(settings, 'public_base_url', None) or 'https://api.alshumookh-pay.com').rstrip('/')


def _money(amount: Decimal | None, currency: str | None) -> str:
    if amount is None:
        return f'- {currency or ""}'.strip()

    value = Decimal(str(amount))
    text = f'{value:,.8f}'.rstrip('0').rstrip('.')
    return f'{text} {currency or ""}'.strip()


def _qr_url(data: str, size: int = 260) -> str:
    return f'https://api.qrserver.com/v1/create-qr-code/?size={size}x{size}&data={quote(data)}'


async def _get_order(db: AsyncSession, transaction_id: str) -> PaymentOrder:
    result = await db.execute(
        select(PaymentOrder).where(cast(PaymentOrder.id, String) == str(transaction_id))
    )
    order = result.scalar_one_or_none()

    if not order:
        raise HTTPException(status_code=404, detail='Payment link not found')

    return order


def _direct_payment_html(order: PaymentOrder) -> str:
    wallet = order.user_wallet_address or '0xBD682cfD8382a90adfDd6745780D3D7959c4d939'
    amount = _money(order.crypto_amount, order.crypto_currency)
    network = order.network.value.upper()
    reference = order.external_id or str(order.id)
    logo_url = f'{_public_base_url()}/static/company-logo.png'
    qr_payload = '\n'.join(
        [
            'ALSHUMOOKH GLOBAL BANKING FINANCE & CREDIT',
            f'Payment Reference: {reference}',
            f'Amount: {amount}',
            f'Network: {network}',
            f'Wallet: {wallet}',
        ]
    )
    qr_url = _qr_url(qr_payload)

    return f'''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>ALSHUMOOKH Direct Crypto Payment</title>
  <style>
    :root {{ --bg:#eef2f6; --panel:#ffffff; --ink:#111827; --muted:#667085; --line:#d8e0ea; --brand:#1f5fd0; --sidebar:#0e1621; --gold:#b9892f; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; min-height:100vh; display:grid; place-items:center; padding:28px; color:var(--ink); font-family:Arial,sans-serif; background:linear-gradient(135deg,#eef2f6,#f8fbff); }}
    .card {{ width:min(980px,100%); display:grid; grid-template-columns:minmax(0,1fr) 320px; overflow:hidden; border:1px solid var(--line); border-radius:10px; background:var(--panel); box-shadow:0 24px 70px rgba(15,23,42,.14); }}
    .main {{ padding:34px; }}
    .side {{ padding:34px; color:white; background:linear-gradient(180deg,#172232,#0e1621); }}
    .brand {{ display:flex; gap:14px; align-items:center; margin-bottom:26px; }}
    .brand img {{ width:58px; height:58px; object-fit:contain; border-radius:8px; background:white; padding:6px; }}
    .fallback {{ width:58px; height:58px; display:none; align-items:center; justify-content:center; border-radius:8px; background:var(--brand); color:white; font-weight:900; }}
    .eyebrow {{ margin:0 0 8px; color:#7fa8ff; font-size:12px; font-weight:900; text-transform:uppercase; }}
    h1 {{ margin:0; font-size:34px; letter-spacing:0; }}
    p {{ color:var(--muted); line-height:1.6; }}
    .amount {{ margin:26px 0; padding:18px; border:1px solid var(--line); border-radius:8px; background:#f8fbff; }}
    .amount span {{ color:var(--muted); font-size:13px; }}
    .amount strong {{ display:block; margin-top:8px; font-size:30px; }}
    .row {{ margin-top:18px; }}
    .label {{ color:var(--muted); font-size:13px; font-weight:800; }}
    code {{ display:block; margin-top:8px; padding:13px; word-break:break-all; border:1px solid var(--line); border-radius:8px; background:#f8fafc; }}
    button {{ min-height:42px; margin-top:12px; padding:9px 14px; border:0; border-radius:7px; background:var(--brand); color:white; font-weight:900; cursor:pointer; }}
    .side img.qr {{ width:260px; height:260px; padding:10px; border-radius:10px; background:white; }}
    .warning {{ margin-top:18px; color:#f7d27d; font-size:13px; line-height:1.6; }}
    @media (max-width:820px) {{ .card {{ grid-template-columns:1fr; }} h1 {{ font-size:28px; }} }}
  </style>
</head>
<body>
  <section class="card">
    <main class="main">
      <div class="brand">
        <img src="{escape(logo_url)}" alt="ALSHUMOOKH Logo" onerror="this.style.display='none';this.nextElementSibling.style.display='flex';">
        <div class="fallback">AS</div>
        <div>
          <p class="eyebrow">ALSHUMOOKH GLOBAL</p>
          <h1>Direct Crypto Payment</h1>
        </div>
      </div>
      <p>Send only the selected token on the selected network to the wallet below.</p>
      <div class="amount">
        <span>Expected Amount</span>
        <strong>{escape(amount)}</strong>
      </div>
      <div class="row">
        <div class="label">Network</div>
        <code>{escape(network)}</code>
      </div>
      <div class="row">
        <div class="label">Ledger Destination Wallet</div>
        <code id="wallet">{escape(wallet)}</code>
        <button onclick="navigator.clipboard.writeText(document.getElementById('wallet').innerText)">Copy Wallet</button>
      </div>
      <div class="row">
        <div class="label">Payment Reference</div>
        <code>{escape(reference)}</code>
      </div>
    </main>
    <aside class="side">
      <p class="eyebrow">Scan to Pay</p>
      <img class="qr" src="{escape(qr_url)}" alt="Payment QR">
      <div class="warning">Wrong-network transfers may be unrecoverable. For Ethereum payments, send ERC-20 token only to this Ethereum wallet.</div>
    </aside>
  </section>
</body>
</html>'''


@router.get('/pay/circle/{intent_id}', response_class=HTMLResponse, include_in_schema=False)
async def circle_payment_page(
    intent_id: str,
    addr: str = "",
    amount: float = 0.0,
    chain: str = "ETH",
    ref: str = "",
):
    """Hosted payment info page for Circle USDC payments."""
    safe_addr = escape(addr)
    safe_amount = f"{amount:.2f}"
    safe_chain = escape(chain)
    safe_ref = escape(ref)
    qr_url = _qr_url(safe_addr) if safe_addr else ""
    logo_url = f'{_public_base_url()}/static/company-logo.png'

    return HTMLResponse(f'''<!doctype html>
<html lang="en" dir="ltr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Circle USDC Payment — ALSHUMOOKH</title>
  <style>
    *{{box-sizing:border-box;margin:0;padding:0}}
    body{{font-family:system-ui,Arial,sans-serif;background:#0a0f1e;color:#e2e8f0;min-height:100vh;display:flex;align-items:center;justify-content:center;padding:20px}}
    .card{{background:#131c30;border:1px solid #1e2d4a;border-radius:16px;padding:32px;max-width:480px;width:100%;box-shadow:0 8px 32px rgba(0,0,0,.4)}}
    .logo{{height:48px;margin-bottom:20px;display:block}}
    h1{{font-size:20px;font-weight:700;color:#fff;margin-bottom:4px}}
    .subtitle{{color:#94a3b8;font-size:13px;margin-bottom:24px}}
    .amount-box{{background:#1652f020;border:2px solid #1652f0;border-radius:12px;padding:16px;text-align:center;margin-bottom:20px}}
    .amount-label{{font-size:12px;color:#94a3b8;margin-bottom:4px}}
    .amount-value{{font-size:32px;font-weight:800;color:#1652f0}}.amount-unit{{font-size:14px;color:#60a5fa;margin-top:4px}}
    .info-row{{display:flex;justify-content:space-between;align-items:center;padding:10px 0;border-bottom:1px solid #1e2d4a;font-size:13px}}
    .info-label{{color:#94a3b8}}
    .info-value{{color:#e2e8f0;font-weight:600;text-align:right;word-break:break-all;max-width:65%}}
    .addr-box{{background:#0d1526;border:1px solid #1e2d4a;border-radius:10px;padding:14px;margin:20px 0;word-break:break-all;font-family:monospace;font-size:13px;color:#60a5fa}}
    .copy-btn{{width:100%;background:#1652f0;color:#fff;border:none;border-radius:10px;padding:14px;font-size:15px;font-weight:700;cursor:pointer;margin-top:4px;transition:background .2s}}
    .copy-btn:hover{{background:#1240c4}}
    .copy-btn:active{{background:#0e35a8}}
    .qr{{display:block;margin:16px auto;border-radius:10px;border:4px solid #fff;width:160px;height:160px}}
    .warning{{background:#7c2d12;border:1px solid #dc2626;border-radius:8px;padding:12px;font-size:12px;color:#fca5a5;margin-top:16px;line-height:1.5}}
    .circle-badge{{display:inline-flex;align-items:center;gap:6px;background:#1652f020;border:1px solid #1652f060;border-radius:20px;padding:4px 12px;font-size:12px;color:#60a5fa;margin-bottom:20px}}
  </style>
</head>
<body>
  <div class="card">
    <img src="{logo_url}" alt="ALSHUMOOKH" class="logo" onerror="this.style.display='none'">
    <div class="circle-badge">● Circle Powered USDC Payment</div>
    <h1>Send USDC to complete payment</h1>
    <p class="subtitle">Reference: {safe_ref or intent_id[:16]}</p>

    <div class="amount-box">
      <div class="amount-label">Amount to Send</div>
      <div class="amount-value">{safe_amount}</div>
      <div class="amount-unit">USDC on {safe_chain} Network</div>
    </div>

    <div class="info-row">
      <span class="info-label">Network</span>
      <span class="info-value">{safe_chain}</span>
    </div>
    <div class="info-row">
      <span class="info-label">Token</span>
      <span class="info-value">USDC (USD Coin)</span>
    </div>
    <div class="info-row">
      <span class="info-label">Payment Reference</span>
      <span class="info-value">{safe_ref or "—"}</span>
    </div>

    <div style="margin-top:20px;margin-bottom:8px;font-size:13px;color:#94a3b8;font-weight:600;">Destination Address</div>
    <div class="addr-box" id="addrText">{safe_addr or "Loading…"}</div>
    <button class="copy-btn" onclick="copyAddr()">📋 Copy Address</button>

    {"<img src='" + qr_url + "' class='qr' alt='QR Code'>" if qr_url else ""}

    <div class="warning">
      ⚠️ Send <strong>USDC only</strong> on the <strong>{safe_chain} network</strong>.<br>
      Sending wrong tokens or using wrong network may result in permanent loss of funds.
    </div>
  </div>

  <script>
    function copyAddr() {{
      var t = document.getElementById('addrText').textContent.trim();
      if (!t || t === 'Loading…') return;
      navigator.clipboard.writeText(t).then(function() {{
        var b = document.querySelector('.copy-btn');
        b.textContent = '✓ Copied!';
        setTimeout(function(){{b.textContent='📋 Copy Address';}}, 2000);
      }});
    }}
  </script>
</body>
</html>''')


@router.get('/pay/direct/{transaction_id}', response_class=HTMLResponse, include_in_schema=False)
async def direct_payment_page(transaction_id: str, db: AsyncSession = Depends(get_db)):
    order = await _get_order(db, transaction_id)
    return HTMLResponse(_direct_payment_html(order))


@router.get('/pay/{transaction_id}', response_class=HTMLResponse, include_in_schema=False)
async def legacy_direct_payment_page(transaction_id: str, db: AsyncSession = Depends(get_db)):
    order = await _get_order(db, transaction_id)
    return HTMLResponse(_direct_payment_html(order))


@router.get('/pay/success', response_class=HTMLResponse, include_in_schema=False)
async def payment_success_page():
    return HTMLResponse(
        '''<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Payment Submitted</title></head>
<body style="margin:0;padding:40px;font-family:Arial,sans-serif;background:#0e1621;color:white">
  <h1>ALSHUMOOKH GLOBAL BANKING FINANCE & CREDIT</h1>
  <h2>Payment submitted</h2>
  <p>Your payment has been submitted. The dashboard will update after confirmation is received.</p>
  <a href="/dashboard" style="color:#8fb5ff">Open dashboard</a>
</body>
</html>'''
    )
