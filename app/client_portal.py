from __future__ import annotations

import re
import uuid
from decimal import Decimal
from html import escape

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy import String, cast, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit_service import log_event
from app.auth import (
    CLIENT_SESSION_COOKIE,
    CLIENT_SESSION_MAX_AGE,
    create_api_key,
    create_client_session_token,
    create_hmac_secret,
    get_client_session_payload,
    hash_api_key,
    hash_password,
    verify_password,
)
from app.config import get_settings
from app.database import get_db
from app.models import (
    ApiClient,
    ClientAccount,
    Network,
    OrderSide,
    OrderStatus,
    PaymentOrder,
    Provider,
)
from app.provider_service import get_provider, OnramperProvider
from app.request_utils import get_client_ip
from app.security import clear_login_failures, log_security_event, login_guard, register_failed_login

router = APIRouter(tags=["client-portal"])
settings = get_settings()

ETHEREUM_LEDGER_WALLET = "0xBD682cfD8382a90adfDd6745780D3D7959c4d939"
TRON_LEDGER_WALLET = "TLARV2U9NzuK9QfzV3PQjwabQTGiEEqjTn"


def _public_base_url() -> str:
    value = (
        getattr(settings, "public_base_url", None)
        or getattr(settings, "public_app_url", None)
        or "https://api.alshumookh-pay.com"
    )
    return str(value).rstrip("/")


def _logo_url() -> str:
    return f"{_public_base_url()}/static/company-logo.png"


def _request_ip(request: Request) -> str | None:
    return get_client_ip(request)


def _secure_cookie_context() -> bool:
    base_url = _public_base_url().lower()
    return settings.app_env == "production" or base_url.startswith("https://")


def _identifier(value: str | None) -> str:
    return str(value or "").strip().lower()


def _is_valid_identifier(value: str) -> bool:
    if not value or len(value) < 5:
        return False

    if "@" in value:
        return re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value) is not None

    digits_only = re.sub(r"[^\d+]", "", value)
    return len(digits_only) >= 7


def _network(value: str | None) -> Network:
    try:
        return Network(str(value or Network.ETHEREUM.value).lower())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Unsupported network") from exc


def _amount(value) -> Decimal:
    try:
        amount = Decimal(str(value))
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid amount") from exc

    if amount <= 0:
        raise HTTPException(status_code=400, detail="Amount must be greater than zero")

    return amount


def _ledger_address(network: Network) -> str:
    if network == Network.BASE and getattr(settings, "ledger_base_address", None):
        return str(settings.ledger_base_address)

    if network == Network.ETHEREUM:
        return str(
            getattr(settings, "ledger_ethereum_address", None)
            or getattr(settings, "eth_treasury_address", None)
            or getattr(settings, "treasury_wallet_address", None)
            or ETHEREUM_LEDGER_WALLET
        )

    if network == Network.TRON:
        return str(
            getattr(settings, "ledger_tron_address", None)
            or TRON_LEDGER_WALLET
        )

    raise HTTPException(
        status_code=400,
        detail=f"Ledger address is not configured for {network.value}",
    )


def _order_json(order: PaymentOrder) -> dict:
    payment_url = None

    if getattr(order, "checkout_url", None):
        payment_url = order.checkout_url
    elif getattr(order, "coinbase_session_url", None):
        payment_url = order.coinbase_session_url
    elif order.provider == Provider.MANUAL:
        payment_url = f"{_public_base_url()}/pay/direct/{order.id}"

    destination_address = (
        getattr(order, "treasury_wallet_address", None)
        or order.user_wallet_address
    )

    return {
        "id": str(order.id),
        "external_id": order.external_id,
        "provider": order.provider.value,
        "status": order.status.value,
        "network": order.network.value,
        "fiat_currency": order.fiat_currency,
        "fiat_amount": str(order.fiat_amount) if order.fiat_amount is not None else None,
        "crypto_currency": order.crypto_currency,
        "crypto_amount": str(order.crypto_amount) if order.crypto_amount is not None else None,
        "destination_address": destination_address,
        "payment_url": payment_url,
        "tx_hash": getattr(order, "tx_hash", None),
        "created_at": order.created_at,
    }


async def _current_account(request: Request, db: AsyncSession) -> ClientAccount:
    payload = get_client_session_payload(request)

    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")

    result = await db.execute(
        select(ClientAccount).where(
            cast(ClientAccount.id, String) == str(payload["account_id"]),
            cast(ClientAccount.api_client_id, String) == str(payload["api_client_id"]),
            ClientAccount.is_active.is_(True),
        )
    )
    account = result.scalar_one_or_none()

    if not account:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")

    request.state.client_id = account.api_client_id

    return account


def client_page() -> HTMLResponse:
    html = """<!doctype html>
<html lang="ar" dir="rtl">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>ALSHUMOOKH Client Portal</title>

  <style>
    :root {
      color-scheme: dark;
      --bg:         #07090f;
      --panel:      rgba(255,255,255,0.038);
      --panel-solid:#111827;
      --ink:        #e8edf5;
      --muted:      #8fa3be;
      --line:       rgba(255,255,255,0.08);
      --line-strong:rgba(255,255,255,0.14);
      --brand:      #4f8ef7;
      --brand-dark: #2563eb;
      --gold:       #d6b46c;
      --gold-dim:   rgba(214,180,108,0.15);
      --ok:         #34d399;
      --warn:       #fbbf24;
      --bad:        #f87171;
      --shadow:     0 8px 40px rgba(0,0,0,0.55);
      --glass:      rgba(255,255,255,0.04);
      --glass-border:rgba(255,255,255,0.09);
    }

    * { box-sizing:border-box; }
    html { scroll-behavior:smooth; font-size:clamp(13px,1.05vw,15px); }

    body {
      margin:0;
      min-height:100vh;
      color:var(--ink);
      font-family:'Segoe UI',Arial,Tahoma,sans-serif;
      font-size:0.9375rem;
      line-height:1.5;
      background:var(--bg);
      position:relative;
      overflow-x:hidden;
    }

    body::before, body::after {
      content:'';
      position:fixed;
      border-radius:50%;
      filter:blur(120px);
      pointer-events:none;
      z-index:0;
      animation:float 18s ease-in-out infinite;
    }
    body::before {
      width:600px; height:600px;
      top:-200px; left:-100px;
      background:radial-gradient(circle,rgba(37,99,235,.18) 0%,transparent 70%);
    }
    body::after {
      width:500px; height:500px;
      bottom:-150px; right:10%;
      background:radial-gradient(circle,rgba(214,180,108,.12) 0%,transparent 70%);
      animation-delay:-9s;
    }
    @keyframes float {
      0%,100% { transform:translate(0,0) scale(1); }
      33%      { transform:translate(30px,-40px) scale(1.05); }
      66%      { transform:translate(-20px,30px) scale(0.97); }
    }

    .shell {
      min-height:100vh;
      display:grid;
      grid-template-columns:clamp(260px,25vw,340px) minmax(0,1fr);
      position:relative;
      z-index:1;
    }

    .hero {
      position:sticky;
      top:0;
      height:100vh;
      display:flex;
      flex-direction:column;
      justify-content:space-between;
      padding:clamp(18px,2vw,30px) clamp(16px,1.8vw,24px);
      color:var(--ink);
      background:#080c14;
      border-left:1px solid var(--glass-border);
    }

    .brand-row {
      display:flex;
      gap:14px;
      align-items:center;
    }

    .brand-row img {
      width:76px;
      height:60px;
      object-fit:contain;
      border:1px solid rgba(214,180,108,.3);
      border-radius:8px;
      padding:6px;
      background:#06080b;
    }

    .mark {
      width:60px;
      height:60px;
      display:none;
      place-items:center;
      border-radius:8px;
      background:var(--gold);
      color:#111820;
      font-weight:900;
      font-size:18px;
    }

    .eyebrow {
      margin:0 0 6px;
      color:var(--gold);
      font-size:11px;
      font-weight:900;
      letter-spacing:.08em;
      text-transform:uppercase;
    }

    h1 {
      margin:16px 0 8px;
      font-size:clamp(20px,2vw,28px);
      line-height:1.2;
      color:var(--ink);
    }

    .hero p {
      color:var(--muted);
      line-height:1.7;
      margin:0;
      font-size:14px;
    }

    .trust-grid {
      display:grid;
      grid-template-columns:1fr 1fr;
      gap:10px;
      margin-top:22px;
    }

    .trust {
      min-height:72px;
      padding:12px;
      border:1px solid var(--glass-border);
      border-radius:8px;
      background:var(--glass);
      backdrop-filter:blur(8px);
    }

    .trust strong {
      display:block;
      margin-bottom:5px;
      color:var(--ink);
      font-size:13px;
    }

    .trust span {
      color:var(--muted);
      font-size:11px;
      line-height:1.5;
    }

    .payment-icons {
      display:flex;
      flex-wrap:wrap;
      gap:7px;
      margin-top:18px;
    }

    .pay-icon {
      min-height:30px;
      display:inline-flex;
      align-items:center;
      gap:6px;
      padding:5px 10px;
      border:1px solid rgba(214,180,108,.25);
      border-radius:7px;
      color:var(--gold);
      background:var(--gold-dim);
      font-size:11px;
      font-weight:900;
    }

    .content {
      width:min(1100px,100%);
      padding:clamp(14px,1.5vw,26px);
      display:grid;
      gap:clamp(12px,1.2vw,16px);
      min-width:0;
    }

    .topbar {
      border:1px solid var(--glass-border);
      border-radius:10px;
      background:var(--panel);
      backdrop-filter:blur(10px);
      box-shadow:var(--shadow);
      display:flex;
      justify-content:space-between;
      gap:16px;
      align-items:center;
      padding:18px 22px;
    }

    .panel {
      border:1px solid var(--glass-border);
      border-radius:10px;
      background:var(--panel);
      backdrop-filter:blur(10px);
      box-shadow:var(--shadow);
      padding:20px;
    }

    .topbar h2 {
      margin:0;
      font-size:22px;
      color:var(--ink);
    }

    .topbar p {
      margin:6px 0 0;
      color:var(--muted);
      line-height:1.5;
      font-size:13px;
    }

    .grid {
      display:grid;
      grid-template-columns:1.1fr .9fr;
      gap:16px;
    }

    .panel-head {
      display:flex;
      justify-content:space-between;
      gap:14px;
      align-items:flex-start;
      margin-bottom:16px;
      padding-bottom:14px;
      border-bottom:1px solid var(--line);
    }

    .panel h3 {
      margin:0;
      font-size:18px;
      color:var(--ink);
    }

    .panel p {
      margin:6px 0 0;
      color:var(--muted);
      line-height:1.5;
      font-size:13px;
    }

    .form-grid {
      display:grid;
      grid-template-columns:repeat(2,minmax(0,1fr));
      gap:12px;
    }

    .wide { grid-column:1 / -1; }

    label {
      display:grid;
      gap:6px;
      color:var(--muted);
      font-size:12px;
      font-weight:700;
    }

    input, select, button {
      min-height:40px;
      border:1px solid var(--glass-border);
      border-radius:7px;
      padding:8px 11px;
      font:inherit;
    }

    input, select {
      color:var(--ink);
      background:rgba(255,255,255,0.06);
      outline:none;
      transition:border-color .2s;
    }
    input:focus, select:focus {
      border-color:var(--brand);
    }
    select option {
      background:#111827;
      color:var(--ink);
    }

    button {
      cursor:pointer;
      color:var(--ink);
      background:var(--glass);
      border-color:var(--glass-border);
      font-weight:700;
      transition:opacity .2s;
    }
    button:hover { opacity:.85; }

    .primary {
      border-color:var(--brand-dark);
      background:linear-gradient(135deg,var(--brand-dark),#1d4ed8);
      color:#fff;
      box-shadow:0 4px 18px rgba(37,99,235,.35);
    }

    .gold {
      border-color:var(--gold);
      background:linear-gradient(135deg,#b8943a,var(--gold));
      color:#111820;
    }

    .ghost {
      border-color:var(--glass-border);
      background:var(--glass);
      color:var(--muted);
    }

    .result {
      margin-top:14px;
      padding:14px;
      border:1px solid var(--glass-border);
      border-radius:8px;
      background:rgba(255,255,255,0.04);
      word-break:break-word;
      font-size:13px;
    }

    .result a {
      color:var(--brand);
      font-weight:700;
    }

    .state {
      display:inline-flex;
      align-items:center;
      min-height:30px;
      padding:4px 10px;
      border-radius:7px;
      color:var(--brand);
      background:rgba(79,142,247,.12);
      font-size:12px;
      font-weight:700;
    }

    .table-wrap {
      overflow:auto;
      border:1px solid var(--glass-border);
      border-radius:8px;
    }

    table {
      width:100%;
      min-width:820px;
      border-collapse:collapse;
      background:transparent;
    }

    th, td {
      padding:11px 10px;
      border-bottom:1px solid var(--line);
      text-align:right;
      vertical-align:top;
      font-size:13px;
    }

    th {
      color:var(--muted);
      background:rgba(255,255,255,0.03);
      font-size:11px;
      font-weight:700;
      text-transform:uppercase;
      letter-spacing:.05em;
    }

    td { color:var(--ink); }

    .badge {
      display:inline-flex;
      min-height:22px;
      align-items:center;
      padding:2px 8px;
      border-radius:6px;
      font-size:11px;
      font-weight:700;
      background:rgba(255,255,255,0.07);
      color:var(--muted);
    }

    .badge.COMPLETED { color:var(--ok);   background:rgba(52,211,153,.12); }
    .badge.FAILED    { color:var(--bad);  background:rgba(248,113,113,.12); }
    .badge.PENDING,
    .badge.PROCESSING,
    .badge.CREATED   { color:var(--warn); background:rgba(251,191,36,.12); }

    .hidden { display:none !important; }

    @media (max-width:1100px) {
      .shell { grid-template-columns:clamp(220px,22vw,280px) minmax(0,1fr); }
    }

    @media (max-width:900px) {
      .shell { grid-template-columns:1fr; }
      .hero  { position:static; height:auto; }
      .grid  { grid-template-columns:1fr; }
    }

    @media (max-width:768px) {
      html { font-size:13px; }
      .content, .hero { padding:14px; }
      .topbar { flex-direction:column; align-items:stretch; }
      .panel-head { flex-direction:column; align-items:stretch; }
      .form-grid { grid-template-columns:1fr; }
      .trust-grid { grid-template-columns:1fr 1fr; }
    }

    @media (max-width:480px) {
      html { font-size:12px; }
      .content, .hero { padding:10px; }
      .trust-grid { grid-template-columns:1fr; }
      .form-grid, .trust-grid { grid-template-columns:1fr; }
      h1 { font-size:24px; }
    }
  </style>
</head>

<body>
  <div class="shell">
    <aside class="hero">
      <div>
        <div class="brand-row">
          <img src="__LOGO_URL__" alt="ALSHUMOOKH Logo" onerror="this.style.display='none';this.nextElementSibling.style.display='grid';">
          <div class="mark">AS</div>

          <div>
            <p class="eyebrow">ALSHUMOOKH GLOBAL</p>
            <strong>Banking Finance & Credit</strong>
          </div>
        </div>

        <h1 id="heroTitle">بوابة دفع آمنة لإنشاء روابط الدفع</h1>
        <p id="heroSubtitle">أنشئ روابط دفع (Crypto) أو عبر (MoonPay) وتابع جميع معاملاتك بشكل آمن وبدون مشاركة أي بيانات حساسة.</p>

        <div class="trust-grid">
          <div class="trust"><strong id="t1h">خصوصية العميل</strong><span id="t1s">كل حساب يرى معاملاته وروابطه فقط.</span></div>
          <div class="trust"><strong id="t2h">دفع عالمي</strong><span id="t2s">بطاقات، تحويل بنكي، SEPA، وكريبتو مباشر.</span></div>
          <div class="trust"><strong id="t3h">محفظة Ledger</strong><span id="t3s">توجيه الدفع إلى عنوان خزينة محدد.</span></div>
          <div class="trust"><strong id="t4h">تأكيدات تشغيلية</strong><span id="t4s">متابعة الحالة من الويبهوكات والإدارة.</span></div>
        </div>

        <div class="payment-icons">
          <span class="pay-icon">Visa</span>
          <span class="pay-icon">Mastercard</span>
          <span class="pay-icon">SEPA</span>
          <span class="pay-icon">Bank Transfer</span>
          <span class="pay-icon">Crypto</span>
        </div>
      </div>

      <div style="padding-top:24px;color:#8fa0b6;font-size:12px;line-height:1.6">
        ALSHUMOOKH GLOBAL BANKING FINANCE &amp; CREDIT<br>
        <span id="heroFoot">بوابة دفع آمنة ومحمية</span>
      </div>
    </aside>

    <main class="content">
      <section class="topbar">
        <div>
          <p class="eyebrow">Client Portal</p>
          <h2 id="pageTitle">مرحباً بك</h2>
          <p id="portalSubtitle">يمكنك إنشاء روابط دفع وتتبع جميع معاملاتك بسهولة وأمان.</p>
        </div>

        <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap;">
          <button id="langToggleBtn" class="ghost" type="button" onclick="toggleClientLang()" style="min-height:36px;padding:0 14px;font-size:12px;font-weight:900;">EN</button>
          <span id="apiState" class="state">جاهز</span>
          <button id="logoutButton" class="ghost" type="button">تسجيل خروج</button>
        </div>
      </section>

      <section class="grid">
        <!-- ── Circle Payment Panel ──────────────────────────────────────── -->
        <article class="panel">
          <div class="panel-head">
            <div>
              <h3 id="circleTitle">Circle USDC Payment</h3>
              <p id="circleSubtitle">رابط دفع عبر Circle — استلام USDC مباشرة إلى محفظة الشركة.</p>
            </div>
            <span class="state" style="background:#1652f0;color:#fff;">Circle</span>
          </div>

          <form id="circleForm" class="form-grid">
            <label id="lbl_circle_amount">قيمة الدفع (USD)
              <input name="fiat_amount" type="number" min="1" step="0.01" value="100" required>
            </label>

            <label id="lbl_circle_network">شبكة USDC
              <select name="network">
                <option value="ethereum" selected>Ethereum (ETH)</option>
                <option value="base">Base</option>
                <option value="polygon">Polygon</option>
              </select>
            </label>

            <label class="wide" id="lbl_circle_ext">رقم مرجعي (اختياري)
              <input name="external_id" placeholder="INV-1001">
            </label>

            <button class="primary wide" id="btn_circle_submit" type="submit">إنشاء رابط Circle</button>
          </form>

          <div id="circleResult" class="result hidden"></div>
        </article>

        <!-- ── MoonPay Panel (Sandbox) ───────────────────────────────────── -->
        <article class="panel">
          <div class="panel-head">
            <div>
              <h3 id="mpTitle">MoonPay Widget Link</h3>
              <p id="mpSubtitle">رابط دفع MoonPay — بطاقة ائتمان أو تحويل بنكي.</p>
            </div>
            <span class="state">Fiat to Crypto</span>
          </div>

          <form id="coinbaseForm" class="form-grid">
            <label id="lbl_fiat_amount">قيمة الدفع
              <input name="fiat_amount" type="number" min="1" step="0.01" value="100" required>
            </label>

            <label id="lbl_fiat_currency">عملة الدفع
              <input name="fiat_currency" value="USD" required>
            </label>

            <label id="lbl_crypto_currency_mp">عملة الشراء
              <select name="crypto_currency">
                <option value="USDC" selected>USDC</option>
                <option value="ETH">ETH</option>
                <option value="USDT">USDT</option>
              </select>
            </label>

            <label id="lbl_network_mp">شبكة التحويل
              <select name="network">
                <option value="ethereum" selected>Ethereum</option>
                <option value="base">Base</option>
              </select>
            </label>

            <label id="lbl_country">الدولة
              <input name="country" placeholder="US">
            </label>

            <label id="lbl_subdivision">الولاية/الإمارة
              <input name="subdivision" placeholder="CA">
            </label>

            <label class="wide" id="lbl_ext_mp">رقم مرجعي (اختياري)
              <input name="external_id" placeholder="INV-1001">
            </label>

            <button class="primary wide" id="btn_moonpay_submit" type="submit">إنشاء رابط MoonPay</button>
          </form>

          <div id="coinbaseResult" class="result hidden"></div>
        </article>

        <article class="panel">
          <div class="panel-head">
            <div>
              <h3 id="directTitle">Direct Crypto Payment</h3>
              <p id="directSubtitle">رابط دفع مباشر إلى محفظة Ledger الخاصة بالشركة.</p>
            </div>
            <span class="state">ETH / USDT / TRC-20</span>
          </div>

          <!-- Network Switcher -->
          <div style="display:flex;gap:8px;margin-bottom:14px;">
            <button type="button" id="clientNetEth" onclick="clientSwitchNetwork('ethereum')"
              style="flex:1;min-height:42px;border-radius:8px;font-weight:800;font-size:13px;background:#6366f1;border:2px solid #6366f1;color:#fff;cursor:pointer;">
              🔷 Ethereum (ERC-20)
            </button>
            <button type="button" id="clientNetTron" onclick="clientSwitchNetwork('tron')"
              style="flex:1;min-height:42px;border-radius:8px;font-weight:800;font-size:13px;background:#f8fafc;border:2px solid #d8e0ea;color:#374151;cursor:pointer;">
              🔴 TRON (TRC-20)
            </button>
          </div>

          <!-- Ethereum Wallet Card -->
          <div id="clientEthCard" style="background:linear-gradient(135deg,#1e1b4b,#312e81);border:1.5px solid #6366f1;border-radius:10px;padding:12px 14px;margin-bottom:14px;">
            <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px;">
              <span style="background:#6366f1;color:#fff;border-radius:6px;padding:2px 10px;font-size:11px;font-weight:800;">ERC-20</span>
              <span style="color:#a5b4fc;font-size:12px;">Ethereum Mainnet — USDT / USDC / ETH</span>
            </div>
            <code style="color:#e0e7ff;word-break:break-all;display:block;margin:8px 0;font-size:12px;">0xBD682cfD8382a90adfDd6745780D3D7959c4d939</code>
            <button type="button" id="btnCopyEth" onclick="navigator.clipboard.writeText('0xBD682cfD8382a90adfDd6745780D3D7959c4d939')"
              style="background:#6366f1;border:none;color:#fff;border-radius:6px;padding:5px 14px;font-size:12px;cursor:pointer;">نسخ عنوان ETH</button>
          </div>

          <!-- TRON Wallet Card (hidden by default) -->
          <div id="clientTronCard" style="display:none;background:linear-gradient(135deg,#064e3b,#065f46);border:1.5px solid #10b981;border-radius:10px;padding:12px 14px;margin-bottom:14px;">
            <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px;">
              <span style="background:#10b981;color:#fff;border-radius:6px;padding:2px 10px;font-size:11px;font-weight:800;">TRC-20</span>
              <span style="color:#6ee7b7;font-size:12px;">TRON Network — USDT TRC-20</span>
            </div>
            <div id="tronWarning" style="background:rgba(255,165,0,.15);border:1px solid rgba(255,165,0,.3);border-radius:6px;padding:7px 10px;margin-bottom:8px;font-size:11px;color:#fcd34d;">
              ⚠️ أرسل USDT TRC-20 فقط — لا ETH أو ERC-20
            </div>
            <code style="color:#d1fae5;word-break:break-all;display:block;margin:8px 0;font-size:12px;">TLARV2U9NzuK9QfzV3PQjwabQTGiEEqjTn</code>
            <button type="button" id="btnCopyTron" onclick="navigator.clipboard.writeText('TLARV2U9NzuK9QfzV3PQjwabQTGiEEqjTn')"
              style="background:#10b981;border:none;color:#fff;border-radius:6px;padding:5px 14px;font-size:12px;cursor:pointer;">نسخ عنوان TRON</button>
          </div>

          <form id="directForm" class="form-grid">
            <label id="lbl_crypto_amount">قيمة الدفع
              <input name="crypto_amount" type="number" min="0.000001" step="0.000001" value="10" required>
            </label>

            <label id="lbl_crypto_currency_d">العملة
              <select id="clientCurrencySelect" name="crypto_currency">
                <option value="USDT" selected>USDT</option>
                <option value="USDC">USDC</option>
                <option value="ETH">ETH</option>
              </select>
            </label>

            <input type="hidden" name="network" id="clientNetworkHidden" value="ethereum">

            <label id="lbl_ext_d">رقم مرجعي (اختياري)
              <input name="external_id" placeholder="DIRECT-1001">
            </label>

            <button class="gold wide" id="btn_direct_submit" type="submit">إنشاء رابط دفع مباشر</button>
          </form>

          <div id="directResult" class="result hidden"></div>
        </article>
      </section>

      <!-- ── Onramper — Card & Bank Transfer ──────────────────────────── -->
      <section class="panel" style="border-top:3px solid #00c26f;">
        <div class="panel-head">
          <div>
            <h3 id="onramperTitle" style="color:#00c26f;">Onramper — بطاقة ائتمان وتحويل بنكي</h3>
            <p id="onramperSubtitle">ادفع ببطاقة Visa/Mastercard، تحويل بنكي، Apple Pay أو Google Pay — يختار تلقائياً أفضل مزود متاح من 30+ مزود.</p>
          </div>
          <span class="state" style="background:rgba(0,194,111,.12);color:#00c26f;">30+ Providers</span>
        </div>

        <form id="onramperForm" class="form-grid">
          <label id="lbl_onr_amount">المبلغ
            <input name="fiat_amount" type="number" min="20" step="1" value="200" required>
          </label>

          <label id="lbl_onr_fiat">العملة الورقية
            <select name="fiat_currency">
              <option value="USD" selected>USD — دولار</option>
              <option value="EUR">EUR — يورو</option>
              <option value="GBP">GBP — جنيه</option>
              <option value="AED">AED — درهم</option>
              <option value="SAR">SAR — ريال</option>
            </select>
          </label>

          <label id="lbl_onr_crypto">العملة المشفرة
            <select name="crypto">
              <option value="USDC" selected>USDC</option>
              <option value="USDT">USDT</option>
              <option value="ETH">ETH</option>
              <option value="BTC">BTC</option>
            </select>
          </label>

          <label id="lbl_onr_network">الشبكة
            <select name="network">
              <option value="ethereum" selected>Ethereum (ERC-20)</option>
              <option value="base">Base</option>
              <option value="polygon">Polygon</option>
              <option value="tron">Tron (TRC-20)</option>
            </select>
          </label>

          <label class="wide" id="lbl_onr_ext">رقم مرجعي (اختياري)
            <input name="external_id" placeholder="INV-2001">
          </label>

          <button class="primary wide" id="btn_onramper_submit" type="submit"
            style="background:linear-gradient(135deg,#00a85a,#00c26f);border-color:#00c26f;">
            إنشاء رابط دفع بالبطاقة / التحويل البنكي
          </button>
        </form>

        <div id="onramperResult" class="result hidden"></div>
      </section>

      <!-- API Key Section -->
      <section class="panel">
        <div class="panel-head">
          <div>
            <h3 id="apiKeyTitle">🔑 API Integration Key</h3>
            <p id="apiKeySubtitle">استخدم هذا المفتاح لربط نظامك مع منصة ALSHUMOOKH عبر API.</p>
          </div>
          <span class="state" id="apiKeyBadge">API Access</span>
        </div>

        <div style="background:var(--glass);border:1px solid var(--glass-border);border-radius:8px;padding:16px;margin-bottom:14px;">
          <p id="apiKeyDesc" style="margin:0 0 12px;font-size:13px;color:var(--muted);">
            إذا كنت تستخدم نظام API خاص بك للربط مع منصتنا، يمكنك إنشاء أو تجديد مفتاح API الخاص بك هنا.
            هذا المفتاح يُستخدم في الـ Header: <code style="background:rgba(255,255,255,0.1);padding:2px 6px;border-radius:4px;font-size:12px;color:var(--gold);">X-API-Key</code>
          </p>

          <div style="display:grid;gap:10px;">
            <div>
              <label style="font-size:12px;font-weight:800;color:var(--muted);margin-bottom:4px;display:block;" id="lbl_api_key">مفتاح API</label>
              <div style="display:flex;gap:8px;align-items:center;">
                <input id="apiKeyDisplay" type="text" readonly
                  value="••••••••••••••••••••••••••••••••"
                  style="flex:1;font-family:monospace;font-size:13px;background:rgba(255,255,255,0.06);border:1px solid var(--glass-border);border-radius:6px;padding:10px 12px;color:var(--ink);">
                <button type="button" id="btnCopyApiKey" onclick="copyApiKey()"
                  style="min-height:42px;padding:0 16px;background:#6366f1;border:none;color:#fff;border-radius:6px;font-size:13px;font-weight:700;cursor:pointer;">
                  <span id="btnCopyApiKeyLabel">نسخ</span>
                </button>
              </div>
            </div>

            <div>
              <label style="font-size:12px;font-weight:800;color:var(--muted);margin-bottom:4px;display:block;" id="lbl_client_id">Client ID</label>
              <div style="display:flex;gap:8px;align-items:center;">
                <input id="clientIdDisplay" type="text" readonly
                  value="••••••••••••••••••••••••••••••••"
                  style="flex:1;font-family:monospace;font-size:13px;background:rgba(255,255,255,0.06);border:1px solid var(--glass-border);border-radius:6px;padding:10px 12px;color:var(--ink);">
                <button type="button" onclick="copyClientId()"
                  style="min-height:42px;padding:0 16px;background:#0f8a5f;border:none;color:#fff;border-radius:6px;font-size:13px;font-weight:700;cursor:pointer;">
                  <span id="btnCopyClientIdLabel">نسخ</span>
                </button>
              </div>
            </div>
          </div>

          <div style="margin-top:14px;display:flex;gap:10px;flex-wrap:wrap;">
            <button type="button" id="btnRevealKey" onclick="revealApiKey()"
              style="min-height:40px;padding:0 18px;background:#1f5fd0;border:none;color:#fff;border-radius:7px;font-size:13px;font-weight:700;cursor:pointer;">
              👁 <span id="btnRevealLabel">عرض المفتاح</span>
            </button>
            <button type="button" id="btnRotateKey" onclick="rotateApiKey()"
              style="min-height:40px;padding:0 18px;background:rgba(184,50,50,0.15);border:1.5px solid #b83232;color:#f87171;border-radius:7px;font-size:13px;font-weight:700;cursor:pointer;">
              🔄 <span id="btnRotateLabel">تجديد المفتاح</span>
            </button>
          </div>

          <div id="apiKeyWarning" style="display:none;margin-top:12px;padding:10px 14px;background:rgba(251,191,36,0.1);border:1px solid rgba(251,191,36,0.35);border-radius:7px;font-size:12px;color:var(--warn);">
            ⚠️ <span id="apiKeyWarningText">سيتم عرض المفتاح مرة واحدة فقط — احفظه في مكان آمن.</span>
          </div>

          <details style="margin-top:16px;">
            <summary id="apiDocsToggle" style="cursor:pointer;font-size:13px;font-weight:800;color:#1f5fd0;">📖 كيفية الاستخدام (API Documentation)</summary>
            <div style="margin-top:12px;background:#1e1b4b;border-radius:8px;padding:14px;font-family:monospace;font-size:12px;color:#e0e7ff;overflow-x:auto;">
              <div style="color:#6ee7b7;margin-bottom:8px;"># POST — إرسال معاملة عبر API</div>
              <div>curl -X POST https://api.alshumookh-pay.com/api/v1/payloads/ingest \\</div>
              <div style="padding-right:12px;">  -H "Content-Type: application/json" \\</div>
              <div style="padding-right:12px;">  -H "X-API-Key: <span style="color:#fcd34d;">YOUR_API_KEY</span>" \\</div>
              <div style="padding-right:12px;">  -H "X-Client-ID: <span style="color:#fcd34d;">YOUR_CLIENT_ID</span>" \\</div>
              <div style="padding-right:12px;">  -d '{</div>
              <div style="padding-right:24px;">"sender_reference": "REF-001",</div>
              <div style="padding-right:24px;">"amount": 1000.00,</div>
              <div style="padding-right:24px;">"currency": "USDT",</div>
              <div style="padding-right:24px;">"network": "ERC20",</div>
              <div style="padding-right:24px;">"receiver_wallet": "0xBD682cfD8382a90adfDd6745780D3D7959c4d939",</div>
              <div style="padding-right:24px;">"transaction_hash": "0x_TX_HASH"</div>
              <div style="padding-right:12px;">}'</div>
            </div>
          </details>
        </div>
      </section>

      <section class="panel">
        <div class="panel-head">
          <div>
            <h3 id="txTitle">سجل المعاملات</h3>
            <p id="txSubtitle">هذه القائمة تعرض معاملات هذا الحساب فقط.</p>
          </div>
          <button id="refreshButton" class="ghost" type="button" data-ar="تحديث" data-en="Refresh">تحديث</button>
        </div>

        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th id="th_ref">المرجع</th>
                <th id="th_type">النوع</th>
                <th id="th_status">الحالة</th>
                <th id="th_network">شبكة التحويل</th>
                <th id="th_fiat">Fiat</th>
                <th id="th_crypto">Crypto</th>
                <th id="th_link">رابط الدفع</th>
                <th id="th_date">التاريخ</th>
              </tr>
            </thead>
            <tbody id="ordersBody"></tbody>
          </table>
        </div>
      </section>
    </main>
  </div>

  <script>
    // ── Global error diagnostics ────────────────────────────────────────────
    window.addEventListener('error', function(ev) {
      console.error('[portal] JS error:', ev.message, 'at', ev.filename, ev.lineno);
    });
    window.addEventListener('unhandledrejection', function(ev) {
      console.error('[portal] Unhandled promise rejection:', ev.reason);
    });

    // ── Language Strings ────────────────────────────────────────────────────
    const CL = {
      ar: {
        heroTitle: 'بوابة دفع آمنة لإنشاء روابط الدفع',
        heroSubtitle: 'أنشئ روابط دفع (Crypto) أو عبر (MoonPay) وتابع جميع معاملاتك بشكل آمن وبدون مشاركة أي بيانات حساسة.',
        heroFoot: 'بوابة دفع آمنة ومحمية',
        portalSubtitle: 'يمكنك إنشاء روابط دفع وتتبع جميع معاملاتك بسهولة وأمان.',
        t1h:'خصوصية العميل', t1s:'كل حساب يرى معاملاته وروابطه فقط.',
        t2h:'دفع عالمي', t2s:'بطاقات، تحويل بنكي، SEPA، وكريبتو مباشر.',
        t3h:'محفظة Ledger', t3s:'توجيه الدفع إلى عنوان خزينة محدد.',
        t4h:'تأكيدات تشغيلية', t4s:'متابعة الحالة من الويبهوكات والإدارة.',
        mpTitle:'MoonPay Commerce Link',
        mpSubtitle:'رابط دفع عبر MoonPay Commerce للتسوية إلى محفظة الشركة.',
        directTitle:'Direct Crypto Payment',
        directSubtitle:'رابط دفع مباشر إلى محفظة Ledger الخاصة بالشركة. اختر Ethereum أو TRON.',
        tronWarning:'⚠️ أرسل USDT TRC-20 فقط على شبكة TRON — لا ETH أو ERC-20',
        btnCopyEth:'نسخ عنوان ETH', btnCopyTron:'نسخ عنوان TRON',
        apiKeyTitle:'🔑 API Integration Key',
        apiKeySubtitle:'استخدم هذا المفتاح لربط نظامك مع منصة ALSHUMOOKH عبر API.',
        apiKeyDesc:'إذا كنت تستخدم نظام API خاص بك للربط مع منصتنا، يمكنك عرض أو تجديد مفتاح API الخاص بك هنا. هذا المفتاح يُستخدم في الـ Header: X-API-Key',
        lbl_api_key:'مفتاح API', lbl_client_id:'Client ID',
        btnCopyApiKeyLabel:'نسخ', btnCopyClientIdLabel:'نسخ',
        btnRevealLabel:'عرض المفتاح', btnRotateLabel:'تجديد المفتاح',
        apiKeyWarningText:'سيتم عرض المفتاح مرة واحدة فقط — احفظه في مكان آمن.',
        apiDocsToggle:'📖 كيفية الاستخدام (API Documentation)',
        txTitle: 'سجل المعاملات',
        txSubtitle: 'هذه القائمة تعرض معاملات هذا الحساب فقط.',
        th_ref:'المرجع', th_type:'النوع', th_status:'الحالة', th_network:'شبكة التحويل',
        th_fiat:'Fiat', th_crypto:'Crypto', th_link:'رابط الدفع', th_date:'التاريخ',
        lbl_fiat_amount:'قيمة الدفع', lbl_fiat_currency:'عملة الدفع',
        lbl_crypto_currency_mp:'عملة الشراء', lbl_network_mp:'شبكة التحويل',
        lbl_country:'الدولة', lbl_subdivision:'الولاية/الإمارة', lbl_ext_mp:'رقم مرجعي (اختياري)',
        btn_moonpay_submit:'إنشاء رابط MoonPay',
        lbl_crypto_amount:'قيمة الدفع', lbl_crypto_currency_d:'العملة',
        lbl_ext_d:'رقم مرجعي (اختياري)',
        btn_direct_submit:'إنشاء رابط دفع مباشر',
        refresh:'تحديث', logout:'تسجيل خروج',
        stateReady:'جاهز', stateConnected:'متصل', stateUpdating:'جارٍ التحديث…', stateError:'خطأ',
        noOrders:'لا توجد معاملات حتى الآن.',
        linkOpen:'فتح الرابط', linkNA:'غير متاح',
        resultCreated:'تم إنشاء رابط الدفع',
        resultRef:'المرجع: ', resultAmount:'المبلغ: ', resultOpen:'فتح رابط الدفع',
        langBtn:'EN',
      },
      en: {
        heroTitle: 'Secure Payment Gateway',
        heroSubtitle: 'Create Crypto or MoonPay payment links and track all your transactions securely without sharing sensitive data.',
        heroFoot: 'Secure & Protected Payment Gateway',
        portalSubtitle: 'Create payment links and track all your transactions easily and securely.',
        t1h:'Client Privacy', t1s:'Each account sees only its own transactions and links.',
        t2h:'Global Payments', t2s:'Cards, bank transfer, SEPA, and direct crypto.',
        t3h:'Ledger Wallet', t3s:'Payments routed to a dedicated treasury address.',
        t4h:'Operational Confirmations', t4s:'Track status from webhooks and admin.',
        mpTitle:'MoonPay Commerce Link',
        mpSubtitle:'Create a MoonPay Commerce payment link settled to the company wallet.',
        directTitle:'Direct Crypto Payment',
        directSubtitle:'Direct payment link to the company Ledger wallet. Choose Ethereum or TRON.',
        tronWarning:'⚠️ Send USDT TRC-20 only on the TRON network — do NOT send ETH or ERC-20',
        btnCopyEth:'Copy ETH Address', btnCopyTron:'Copy TRON Address',
        apiKeyTitle:'🔑 API Integration Key',
        apiKeySubtitle:'Use this key to connect your system to the ALSHUMOOKH platform via API.',
        apiKeyDesc:'If you use your own API system to integrate with our platform, you can reveal or regenerate your API key here. Use this key in the request header: X-API-Key',
        lbl_api_key:'API Key', lbl_client_id:'Client ID',
        btnCopyApiKeyLabel:'Copy', btnCopyClientIdLabel:'Copy',
        btnRevealLabel:'Reveal Key', btnRotateLabel:'Regenerate Key',
        apiKeyWarningText:'The key will be shown only once — save it in a secure location.',
        apiDocsToggle:'📖 How to Use (API Documentation)',
        txTitle: 'Transaction History',
        txSubtitle: 'This list shows transactions for this account only.',
        th_ref:'Reference', th_type:'Type', th_status:'Status', th_network:'Network',
        th_fiat:'Fiat', th_crypto:'Crypto', th_link:'Payment Link', th_date:'Date',
        lbl_fiat_amount:'Payment Amount', lbl_fiat_currency:'Payment Currency',
        lbl_crypto_currency_mp:'Purchase Currency', lbl_network_mp:'Transfer Network',
        lbl_country:'Country', lbl_subdivision:'State / Emirate', lbl_ext_mp:'Reference Number (optional)',
        btn_moonpay_submit:'Create MoonPay Link',
        lbl_crypto_amount:'Payment Amount', lbl_crypto_currency_d:'Currency',
        lbl_ext_d:'Reference Number (optional)',
        btn_direct_submit:'Create Direct Payment Link',
        refresh:'Refresh', logout:'Logout',
        stateReady:'Ready', stateConnected:'Connected', stateUpdating:'Updating…', stateError:'Error',
        noOrders:'No transactions yet.',
        linkOpen:'Open Link', linkNA:'Not available',
        resultCreated:'Payment link created',
        resultRef:'Reference: ', resultAmount:'Amount: ', resultOpen:'Open Payment Link',
        langBtn:'عربي',
      }
    };

    let clientLang = localStorage.getItem('als_lang') || 'ar';

    function applyClientLang(lang) {
      const s = CL[lang];
      const isRtl = lang === 'ar';
      document.documentElement.lang = lang;
      document.documentElement.dir = isRtl ? 'rtl' : 'ltr';

      // Simple textContent swap by ID
      const ids = [
        'heroTitle','heroSubtitle','heroFoot','portalSubtitle',
        't1h','t1s','t2h','t2s','t3h','t3s','t4h','t4s',
        'mpTitle','mpSubtitle','directTitle','directSubtitle',
        'tronWarning','btnCopyEth','btnCopyTron',
        'apiKeyTitle','apiKeySubtitle','apiKeyDesc',
        'apiKeyWarningText','apiDocsToggle',
        'btnCopyApiKeyLabel','btnCopyClientIdLabel',
        'btnRevealLabel','btnRotateLabel',
        'txTitle','txSubtitle',
        'th_ref','th_type','th_status','th_network','th_fiat','th_crypto','th_link','th_date',
        'btn_moonpay_submit','btn_direct_submit',
      ];
      ids.forEach(function(id) {
        const el = document.getElementById(id);
        if (el && s[id] !== undefined) el.textContent = s[id];
      });

      // Labels (first text node child)
      ['lbl_fiat_amount','lbl_fiat_currency','lbl_crypto_currency_mp','lbl_network_mp',
       'lbl_country','lbl_subdivision','lbl_ext_mp','lbl_crypto_amount',
       'lbl_crypto_currency_d','lbl_ext_d','lbl_api_key','lbl_client_id'].forEach(function(id) {
        const el = document.getElementById(id);
        if (el && el.childNodes[0]) el.childNodes[0].textContent = s[id] ? s[id] + ' ' : el.childNodes[0].textContent;
      });

      const refreshBtn = document.getElementById('refreshButton');
      if (refreshBtn) refreshBtn.textContent = s.refresh;
      const logoutBtn = document.querySelector('#logoutButton');
      if (logoutBtn) logoutBtn.textContent = s.logout;
      const langBtn = document.getElementById('langToggleBtn');
      if (langBtn) langBtn.textContent = s.langBtn;

      // State badge text
      const stateEl = document.getElementById('apiState');
      if (stateEl) {
        const cur = stateEl.textContent.trim();
        if (cur === CL['ar'].stateReady || cur === CL['en'].stateReady) stateEl.textContent = s.stateReady;
        else if (cur === CL['ar'].stateConnected || cur === CL['en'].stateConnected) stateEl.textContent = s.stateConnected;
        else if (cur === CL['ar'].stateError || cur === CL['en'].stateError) stateEl.textContent = s.stateError;
      }
    }

    function toggleClientLang() {
      clientLang = clientLang === 'ar' ? 'en' : 'ar';
      localStorage.setItem('als_lang', clientLang);
      applyClientLang(clientLang);
    }

    // ── Session Timeout — auto logout after 30 min of inactivity ───────────
    const SESSION_TIMEOUT_MS = 30 * 60 * 1000; // 30 minutes
    let _sessionTimer = null;

    function _resetSessionTimer() {
      clearTimeout(_sessionTimer);
      _sessionTimer = setTimeout(function () {
        fetch('/client/logout', { method: 'POST' }).finally(function () {
          window.location.href = '/login?type=client&reason=timeout';
        });
      }, SESSION_TIMEOUT_MS);
    }

    ['click','keydown','scroll','touchstart'].forEach(function(evt) {
      document.addEventListener(evt, _resetSessionTimer, { passive: true });
    });

    // ── Core functions ──────────────────────────────────────────────────────
    function setState(key) {
      var s = CL[clientLang];
      var el = document.getElementById('apiState');
      if (el) el.textContent = s[key] || key;
    }

    async function jsonApi(path, options) {
      const response = await fetch(path, {
        method: options && options.method ? options.method : 'GET',
        credentials: 'include',
        headers: Object.assign({ 'Content-Type': 'application/json' }, (options && options.headers) || {}),
        body: options && options.body ? options.body : null
      });
      const text = await response.text();
      const data = text ? JSON.parse(text) : {};
      if (!response.ok) {
        var detail = data.detail;
        var msg;
        if (typeof detail === 'string') {
          msg = detail;
        } else if (detail && typeof detail === 'object') {
          msg = detail.message || detail.moonpay_response || detail.coinbase_response || JSON.stringify(detail);
        } else {
          msg = text || ('HTTP ' + response.status);
        }
        throw new Error(msg);
      }
      return data;
    }

    function formatDate(value) {
      if (!value) return '-';
      return new Date(value).toLocaleString(clientLang === 'ar' ? 'ar' : 'en-GB');
    }

    function linkHtml(url) {
      const s = CL[clientLang];
      if (!url) return '<span>' + s.linkNA + '</span>';
      return '<a href="' + url + '" target="_blank" rel="noopener">' + s.linkOpen + '</a>';
    }

    function showResult(element, order) {
      const s = CL[clientLang];
      element.innerHTML =
        '<strong>' + s.resultCreated + '</strong>' +
        '<p>' + s.resultRef + (order.external_id || order.id) + '</p>' +
        '<p>' + s.resultAmount + (order.crypto_amount || order.fiat_amount || '-') + ' ' + (order.crypto_currency || order.fiat_currency || '') + '</p>' +
        '<a href="' + order.payment_url + '" target="_blank" rel="noopener">' + s.resultOpen + '</a>';
      element.classList.remove('hidden');
    }

    function renderOrders(orders) {
      var ordersBody = document.getElementById('ordersBody');
      if (!ordersBody) return;
      var s = CL[clientLang];
      ordersBody.innerHTML = '';
      if (!orders || !orders.length) {
        ordersBody.innerHTML = '<tr><td colspan="8">' + s.noOrders + '</td></tr>';
        return;
      }
      for (var i = 0; i < orders.length; i++) {
        var order = orders[i];
        var row = document.createElement('tr');
        row.innerHTML =
          '<td>' + (order.external_id || order.id) + '</td>' +
          '<td>' + order.provider + '</td>' +
          '<td><span class="badge ' + order.status + '">' + order.status + '</span></td>' +
          '<td>' + order.network + '</td>' +
          '<td>' + (order.fiat_amount || '-') + ' ' + (order.fiat_currency || '') + '</td>' +
          '<td>' + (order.crypto_amount || '-') + ' ' + (order.crypto_currency || '') + '</td>' +
          '<td>' + linkHtml(order.payment_url) + '</td>' +
          '<td>' + formatDate(order.created_at) + '</td>';
        ordersBody.appendChild(row);
      }
    }

    async function refreshOrders() {
      const orders = await jsonApi('/client/orders');
      renderOrders(orders);
    }

    async function loadMe() {
      var me = await jsonApi('/client/me');
      var pt = document.getElementById('pageTitle');
      if (pt) pt.textContent = (clientLang === 'ar' ? 'مرحباً ' : 'Welcome ') + me.identifier;
      setState('stateConnected');
      await refreshOrders();
    }

    var _logoutBtn = document.getElementById('logoutButton');
    if (_logoutBtn) _logoutBtn.addEventListener('click', async function () {
      await jsonApi('/client/logout', { method: 'POST' }).catch(function () {});
      window.location.href = '/login?type=client';
    });

    var _refreshBtn = document.getElementById('refreshButton');
    if (_refreshBtn) _refreshBtn.addEventListener('click', async function () {
      try {
        setState('stateUpdating');
        await refreshOrders();
        setState('stateConnected');
      } catch (error) {
        setState('stateError');
      }
    });

    // ── Circle payment form ──────────────────────────────────────────────────
    var _circleForm = document.getElementById('circleForm');
    if (_circleForm) _circleForm.addEventListener('submit', async function (event) {
      event.preventDefault();
      var circleResult = document.getElementById('circleResult');
      var formData = new FormData(event.target);
      circleResult.classList.add('hidden');
      try {
        setState('stateUpdating');
        var order = await jsonApi('/client/circle-payment', {
          method: 'POST',
          body: JSON.stringify({
            fiat_amount: Number(formData.get('fiat_amount')),
            fiat_currency: 'USD',
            crypto_currency: 'USDC',
            network: formData.get('network'),
            external_id: formData.get('external_id') || null
          })
        });
        showResult(circleResult, order);
        await refreshOrders();
        setState('stateConnected');
      } catch (error) {
        circleResult.innerHTML = '<span style="color:var(--bad);">❌ ' + error.message + '</span>';
        circleResult.classList.remove('hidden');
        setState('stateError');
      }
    });

    // ── MoonPay payment form ─────────────────────────────────────────────────
    var _coinbaseForm = document.getElementById('coinbaseForm');
    if (_coinbaseForm) _coinbaseForm.addEventListener('submit', async function (event) {
      event.preventDefault();
      var coinbaseResult = document.getElementById('coinbaseResult');
      var formData = new FormData(event.target);
      coinbaseResult.classList.add('hidden');
      try {
        setState('stateUpdating');
        var order = await jsonApi('/client/moonpay-payment', {
          method: 'POST',
          body: JSON.stringify({
            fiat_amount: Number(formData.get('fiat_amount')),
            fiat_currency: formData.get('fiat_currency'),
            crypto_currency: formData.get('crypto_currency'),
            network: formData.get('network'),
            country: formData.get('country') || null,
            subdivision: formData.get('subdivision') || null,
            external_id: formData.get('external_id') || null
          })
        });
        showResult(coinbaseResult, order);
        await refreshOrders();
        setState('stateConnected');
      } catch (error) {
        coinbaseResult.innerHTML = '<span style="color:var(--bad);">❌ ' + error.message + '</span>';
        coinbaseResult.classList.remove('hidden');
        setState('stateError');
      }
    });

    // ── API Key Management ──────────────────────────────────────────────────
    var _revealedKey = null;
    var _revealedClientId = null;

    async function revealApiKey() {
      var btn = document.getElementById('btnRevealKey');
      if (btn) btn.disabled = true;
      try {
        const data = await jsonApi('/client/apikey');
        _revealedKey = data.api_key;
        _revealedClientId = data.client_id;
        document.getElementById('apiKeyDisplay').value = data.api_key;
        document.getElementById('clientIdDisplay').value = data.client_id;
        if (btn) btn.style.display = 'none';
        document.getElementById('apiKeyWarning').style.display = 'block';
      } catch(e) {
        console.error('[portal] revealApiKey error:', e);
        if (btn) btn.disabled = false;
        var warn = document.getElementById('apiKeyWarning');
        if (warn) { warn.style.display = 'block'; warn.textContent = '❌ ' + e.message; }
        else alert('خطأ في عرض المفتاح: ' + e.message);
      }
    }

    async function rotateApiKey() {
      if (!confirm(clientLang === 'ar'
        ? 'هل أنت متأكد؟ سيتم إلغاء المفتاح الحالي وإنشاء مفتاح جديد.'
        : 'Are you sure? The current key will be revoked and a new one generated.')) return;
      var btn = document.getElementById('btnRotateKey');
      if (btn) btn.disabled = true;
      try {
        const data = await jsonApi('/client/rotate-apikey', { method: 'POST' });
        _revealedKey = data.api_key;
        _revealedClientId = data.client_id;
        document.getElementById('apiKeyDisplay').value = data.api_key;
        document.getElementById('clientIdDisplay').value = data.client_id;
        document.getElementById('apiKeyWarning').style.display = 'block';
        document.getElementById('btnRevealKey').style.display = 'none';
        if (btn) btn.disabled = false;
      } catch(e) {
        console.error('[portal] rotateApiKey error:', e);
        if (btn) btn.disabled = false;
        var warn = document.getElementById('apiKeyWarning');
        if (warn) { warn.style.display = 'block'; warn.textContent = '❌ ' + e.message; }
        else alert('خطأ في تجديد المفتاح: ' + e.message);
      }
    }

    function copyApiKey() {
      const val = document.getElementById('apiKeyDisplay').value;
      if (val && !val.includes('•')) {
        navigator.clipboard.writeText(val).then(function() {
          const btn = document.getElementById('btnCopyApiKeyLabel');
          if (btn) { btn.textContent = clientLang === 'ar' ? '✓ تم' : '✓ Copied'; setTimeout(function(){ btn.textContent = CL[clientLang].btnCopyApiKeyLabel; }, 2000); }
        });
      }
    }

    function copyClientId() {
      const val = document.getElementById('clientIdDisplay').value;
      if (val && !val.includes('•')) {
        navigator.clipboard.writeText(val).then(function() {
          const btn = document.getElementById('btnCopyClientIdLabel');
          if (btn) { btn.textContent = clientLang === 'ar' ? '✓ تم' : '✓ Copied'; setTimeout(function(){ btn.textContent = CL[clientLang].btnCopyClientIdLabel; }, 2000); }
        });
      }
    }

    // ── Client Network Switcher ─────────────────────────────────────────────
    var _clientActiveNetwork = 'ethereum';
    function clientSwitchNetwork(net) {
      _clientActiveNetwork = net;
      var isEth = net === 'ethereum';
      document.getElementById('clientEthCard').style.display  = isEth ? 'block' : 'none';
      document.getElementById('clientTronCard').style.display = isEth ? 'none'  : 'block';
      document.getElementById('clientNetworkHidden').value = net;
      // Button styles
      var ethBtn  = document.getElementById('clientNetEth');
      var tronBtn = document.getElementById('clientNetTron');
      if (isEth) {
        ethBtn.style.background  = '#6366f1'; ethBtn.style.borderColor  = '#6366f1'; ethBtn.style.color = '#fff';
        tronBtn.style.background = '#f8fafc'; tronBtn.style.borderColor = '#d8e0ea'; tronBtn.style.color = '#374151';
      } else {
        tronBtn.style.background = '#10b981'; tronBtn.style.borderColor = '#10b981'; tronBtn.style.color = '#fff';
        ethBtn.style.background  = '#f8fafc'; ethBtn.style.borderColor  = '#d8e0ea'; ethBtn.style.color = '#374151';
      }
      // Currency options: TRON only supports USDT
      var sel = document.getElementById('clientCurrencySelect');
      if (!isEth) {
        sel.value = 'USDT';
        Array.from(sel.options).forEach(function(o){ o.disabled = o.value !== 'USDT'; });
      } else {
        Array.from(sel.options).forEach(function(o){ o.disabled = false; });
      }
    }

    var _directForm = document.getElementById('directForm');
    if (_directForm) _directForm.addEventListener('submit', async function (event) {
      event.preventDefault();
      var directResult = document.getElementById('directResult');
      var formData = new FormData(event.target);
      var netHidden = document.getElementById('clientNetworkHidden');
      var network = netHidden ? netHidden.value : 'ethereum';
      var isTron  = network === 'tron';
      var amount  = Number(formData.get('crypto_amount'));
      var currency = formData.get('crypto_currency') || 'USDT';
      var TRON_WALLET = 'TLARV2U9NzuK9QfzV3PQjwabQTGiEEqjTn';
      var ETH_WALLET  = '0xBD682cfD8382a90adfDd6745780D3D7959c4d939';
      directResult.classList.add('hidden');
      try {
        setState('stateUpdating');
        var order = await jsonApi('/client/direct-payment', {
          method: 'POST',
          body: JSON.stringify({
            crypto_amount: amount,
            crypto_currency: currency,
            network: network,
            external_id: formData.get('external_id') || null
          })
        });
        var wallet = order.treasury_wallet_address || (isTron ? TRON_WALLET : ETH_WALLET);
        var payUrl = order.payment_url || '';
        var netLabel = isTron ? 'TRON (TRC-20)' : 'Ethereum (ERC-20)';
        var netColor = isTron ? '#10b981' : '#6366f1';
        var html = '<div style="background:#f0fdf4;border:1.5px solid ' + netColor + ';border-radius:10px;padding:14px;">';
        html += '<strong style="color:' + netColor + ';">&#x2705; تم إنشاء رابط الدفع &mdash; ' + netLabel + '</strong><br><br>';
        html += '<b>المرجع:</b> <code>' + (order.external_id || order.id) + '</code><br>';
        html += '<b>المبلغ:</b> ' + amount + ' ' + currency + '<br>';
        html += '<b>الشبكة:</b> ' + netLabel + '<br>';
        html += '<b>العنوان:</b><br><code style="font-size:11px;word-break:break-all;">' + wallet + '</code><br>';
        if (isTron) html += '<p style="color:#f59e0b;font-size:11px;">&#x26A0;&#xFE0F; أرسل USDT TRC-20 فقط على شبكة TRON</p>';
        html += '<div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:10px;">';
        if (payUrl) html += '<a href="' + payUrl + '" target="_blank" rel="noopener" style="padding:7px 16px;background:' + netColor + ';color:#fff;border-radius:6px;text-decoration:none;font-size:13px;">&#x1F517; فتح رابط الدفع</a>';
        html += '<button type="button" id="_copyWalletBtn" style="background:#6b7280;border:none;color:#fff;border-radius:6px;padding:7px 14px;font-size:12px;cursor:pointer;">نسخ العنوان</button>';
        if (payUrl) html += '<button type="button" id="_copyLinkBtn" style="background:#1d4ed8;border:none;color:#fff;border-radius:6px;padding:7px 14px;font-size:12px;cursor:pointer;">نسخ الرابط</button>';
        html += '</div></div>';
        directResult.innerHTML = html;
        directResult.classList.remove('hidden');
        var wb = document.getElementById('_copyWalletBtn');
        if (wb) wb.onclick = function(){ navigator.clipboard.writeText(wallet); };
        var lb = document.getElementById('_copyLinkBtn');
        if (lb) lb.onclick = function(){ navigator.clipboard.writeText(payUrl); };
        await refreshOrders();
        setState('stateConnected');
      } catch (error) {
        directResult.textContent = error.message;
        directResult.classList.remove('hidden');
        setState('stateError');
      }
    });

    // ── Onramper — Card & Bank Transfer ─────────────────────────────────────
    var _onramperLastUrl = '';   // stores last generated URL for copy button
    var _onramperForm   = document.getElementById('onramperForm');
    var _onramperResult = document.getElementById('onramperResult');

    if (_onramperForm && _onramperResult) {
      _onramperForm.addEventListener('submit', async function (event) {
        event.preventDefault();
        _onramperResult.classList.add('hidden');
        setState('stateUpdating');

        var fd           = new FormData(_onramperForm);
        var fiatAmount   = Number(fd.get('fiat_amount'));
        var fiatCurrency = String(fd.get('fiat_currency') || 'USD').toUpperCase();
        var crypto       = String(fd.get('crypto') || 'USDC').toUpperCase();
        var network      = String(fd.get('network') || 'ethereum').toLowerCase();
        var externalId   = fd.get('external_id') || ('ONR-' + Date.now());

        try {
          var data = await jsonApi('/client/onramper-payment', {
            method: 'POST',
            body: JSON.stringify({
              fiat_amount: fiatAmount,
              fiat_currency: fiatCurrency,
              crypto: crypto,
              network: network,
              external_id: externalId
            })
          });

          var checkoutUrl = data.checkout_url || data.payment_url || '';
          _onramperLastUrl = checkoutUrl;
          _onramperResult.innerHTML =
            '<div>' +
            '<strong style="color:#00c26f;">&#x2705; تم إنشاء رابط الدفع</strong>' +
            '<p>المبلغ: <strong>' + fiatAmount + ' ' + fiatCurrency + '</strong> &#x2190; <strong>' + crypto + '</strong></p>' +
            '<p style="font-size:12px;color:var(--muted);">أرسل هذا الرابط للعميل — يدفع ببطاقة، تحويل بنكي، Apple Pay أو Google Pay.</p>' +
            (checkoutUrl ? '<a href="' + checkoutUrl + '" target="_blank" rel="noopener" style="display:inline-block;margin-top:8px;padding:8px 16px;background:linear-gradient(135deg,#00a85a,#00c26f);color:#fff;border-radius:7px;text-decoration:none;font-weight:700;">&#x1F517; فتح صفحة الدفع</a>' : '') +
            (checkoutUrl ? '<button type="button" id="_onrCopyBtn" style="margin-top:8px;margin-right:8px;padding:7px 14px;background:#00a85a;border:none;border-radius:7px;color:#fff;cursor:pointer;font-size:12px;font-weight:700;">نسخ الرابط</button>' : '') +
            '</div>';
          _onramperResult.classList.remove('hidden');
          var _onrCopy = document.getElementById('_onrCopyBtn');
          if (_onrCopy) _onrCopy.onclick = function(){ if(_onramperLastUrl) navigator.clipboard.writeText(_onramperLastUrl); };
          setState('stateConnected');
          refreshOrders().catch(function(){});
        } catch (error) {
          _onramperResult.innerHTML = '<span style="color:var(--bad);">❌ ' + error.message + '</span>';
          _onramperResult.classList.remove('hidden');
          setState('stateError');
        }
      });
    }

    // ── Init ────────────────────────────────────────────────────────────────
    try { applyClientLang(clientLang); } catch(e) { console.warn('applyClientLang error', e); }
    _resetSessionTimer();
    loadMe().catch(function (err) {
      console.error('[portal] loadMe failed:', err);
      // Show a brief diagnostic banner then redirect
      var banner = document.createElement('div');
      banner.style.cssText = 'position:fixed;top:0;left:0;right:0;z-index:9999;background:#b91c1c;color:#fff;padding:12px 20px;font-size:14px;text-align:center;';
      banner.textContent = 'جلسة منتهية أو غير صالحة — جارٍ التحويل للدخول... (' + (err && err.message ? err.message : 'session error') + ')';
      document.body.appendChild(banner);
      setTimeout(function () {
        window.location.href = '/login?type=client';
      }, 2500);
    });
  </script>
</body>
</html>"""

    html = html.replace("__LOGO_URL__", escape(_logo_url()))

    return HTMLResponse(html)


@router.get("/client", response_class=HTMLResponse, include_in_schema=False)
async def client_home(request: Request, db: AsyncSession = Depends(get_db)):
    try:
        await _current_account(request, db)
    except HTTPException:
        return RedirectResponse("/login?type=client", status_code=status.HTTP_303_SEE_OTHER)

    return client_page()


@router.get("/client/login", include_in_schema=False)
async def client_login_page():
    return RedirectResponse("/login?type=client", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/client/register")
async def client_register(request: Request, db: AsyncSession = Depends(get_db)):
    payload = await request.json()
    identifier = _identifier(payload.get("identifier"))
    password = str(payload.get("password") or "")

    if not _is_valid_identifier(identifier):
        raise HTTPException(
            status_code=400,
            detail="يرجى إدخال بريد إلكتروني صحيح أو رقم هاتف صحيح / Please enter a valid email address or phone number",
        )

    if len(password) < 6:
        raise HTTPException(
            status_code=400,
            detail="يجب أن تكون كلمة المرور 6 أحرف على الأقل / Password must be at least 6 characters",
        )

    existing = await db.execute(
        select(ClientAccount).where(ClientAccount.email_or_phone == identifier)
    )

    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=409,
            detail="هذا الحساب موجود مسبقاً، سجل الدخول مباشرة / This account already exists, please log in instead",
        )

    api_key = create_api_key()

    api_client = ApiClient(
        name=identifier,
        api_key_hash=hash_api_key(api_key),
        hmac_secret=create_hmac_secret(),
        allowed_ips=None,
    )
    db.add(api_client)
    await db.commit()
    await db.refresh(api_client)

    account = ClientAccount(
        api_client_id=api_client.id,
        email_or_phone=identifier,
        password_hash=hash_password(password),
    )
    db.add(account)
    await db.commit()
    await db.refresh(account)

    await log_event(
        db,
        "CLIENT_ACCOUNT_CREATED",
        {
            "identifier": identifier,
            "ip": _request_ip(request),
        },
        None,
        client_id=api_client.id,
    )

    response = JSONResponse({"identifier": account.email_or_phone})
    response.set_cookie(
        CLIENT_SESSION_COOKIE,
        create_client_session_token(str(account.id), str(api_client.id), request),
        max_age=CLIENT_SESSION_MAX_AGE,
        httponly=True,
        secure=_secure_cookie_context(),
        samesite="lax",
    )

    return response


@router.post("/client/login")
async def client_login(request: Request, db: AsyncSession = Depends(get_db)):
    ip = _request_ip(request) or "unknown"
    guard = login_guard(ip)

    if guard["is_locked"]:
        await log_event(db, "CLIENT_LOGIN_RATE_LIMITED", {"ip": ip, "lock_seconds": guard["lock_seconds"]}, None)
        await log_security_event(
            "SECURITY_CLIENT_LOGIN_LOCKED",
            {
                "classification": "blocked",
                "lock_seconds": guard["lock_seconds"],
                "captcha_ready": guard["captcha_ready"],
            },
            ip=ip,
            path="/client/login",
            method="POST",
            user_agent=str(request.headers.get("user-agent") or ""),
            status_code=429,
            request_id=getattr(request.state, "request_id", None),
        )
        raise HTTPException(
            status_code=429,
            headers={"X-Captcha-Recommended": "1" if guard["captcha_ready"] else "0"},
            detail=f"تم قفل تسجيل الدخول مؤقتاً. حاول بعد {guard['lock_seconds']} ثانية / Login is temporarily locked. Try again in {guard['lock_seconds']} seconds.",
        )

    if guard["is_backoff"]:
        raise HTTPException(
            status_code=429,
            headers={"X-Captcha-Recommended": "1" if guard["captcha_ready"] else "0"},
            detail=f"يرجى الانتظار {guard['backoff_seconds']} ثانية قبل المحاولة التالية / Please wait {guard['backoff_seconds']} seconds before trying again.",
        )

    payload = await request.json()
    identifier = _identifier(payload.get("identifier"))
    password = str(payload.get("password") or "")

    result = await db.execute(
        select(ClientAccount).where(
            ClientAccount.email_or_phone == identifier,
            ClientAccount.is_active.is_(True),
        )
    )
    account = result.scalar_one_or_none()

    if not account or not verify_password(password, account.password_hash):
        failure = register_failed_login(ip)
        await log_event(
            db,
            "CLIENT_LOGIN_FAILED",
            {
                "identifier": identifier,
                "ip": ip,
                "failed_attempts": failure["failed_attempts"],
                "backoff_seconds": failure["backoff_seconds"],
                "captcha_ready": failure["captcha_ready"],
            },
            None,
        )
        await log_security_event(
            "SECURITY_CLIENT_LOGIN_FAILED",
            {
                "classification": "suspicious",
                "identifier": identifier,
                "failed_attempts": failure["failed_attempts"],
                "backoff_seconds": failure["backoff_seconds"],
                "captcha_ready": failure["captcha_ready"],
            },
            ip=ip,
            path="/client/login",
            method="POST",
            user_agent=str(request.headers.get("user-agent") or ""),
            status_code=401,
            request_id=getattr(request.state, "request_id", None),
        )
        raise HTTPException(
            status_code=401,
            headers={"X-Captcha-Recommended": "1" if failure["captcha_ready"] else "0"},
            detail="بيانات الدخول غير صحيحة / Invalid login details",
        )

    clear_login_failures(ip)
    await log_event(
        db,
        "CLIENT_LOGIN_SUCCESS",
        {"identifier": identifier, "ip": ip},
        None,
        client_id=account.api_client_id,
    )

    response = JSONResponse({"identifier": account.email_or_phone})
    response.set_cookie(
        CLIENT_SESSION_COOKIE,
        create_client_session_token(str(account.id), str(account.api_client_id), request),
        max_age=CLIENT_SESSION_MAX_AGE,
        httponly=True,
        secure=_secure_cookie_context(),
        samesite="lax",
    )

    return response


@router.post("/client/logout")
async def client_logout():
    response = JSONResponse({"ok": True})
    response.delete_cookie(CLIENT_SESSION_COOKIE)
    return response


@router.get("/client/me")
async def client_me(request: Request, db: AsyncSession = Depends(get_db)):
    account = await _current_account(request, db)

    return {
        "identifier": account.email_or_phone,
        "account_id": str(account.id),
    }


@router.get("/client/orders")
async def client_orders(request: Request, db: AsyncSession = Depends(get_db)):
    account = await _current_account(request, db)

    result = await db.execute(
        select(PaymentOrder)
        .where(PaymentOrder.client_id == account.api_client_id)
        .order_by(PaymentOrder.created_at.desc())
        .limit(100)
    )

    return [_order_json(order) for order in result.scalars().all()]


@router.post("/client/direct-payment")
async def client_direct_payment(request: Request, db: AsyncSession = Depends(get_db)):
    account = await _current_account(request, db)
    payload = await request.json()

    network = _network(payload.get("network"))
    amount = _amount(payload.get("crypto_amount"))
    currency = str(payload.get("crypto_currency") or "USDC").upper()
    external_id = str(payload.get("external_id") or f"DIRECT-{currency}-{uuid.uuid4().hex[:10]}")
    destination_address = _ledger_address(network)

    order = PaymentOrder(
        client_id=account.api_client_id,
        idempotency_key=f"client-direct-{uuid.uuid4()}",
        external_id=external_id,
        provider=Provider.MANUAL,
        side=OrderSide.BUY,
        status=OrderStatus.CREATED,
        network=network,
        fiat_currency="USD",
        fiat_amount=None,
        crypto_currency=currency,
        crypto_amount=amount,
        user_wallet_address=destination_address,
    )

    if hasattr(order, "treasury_wallet_address"):
        order.treasury_wallet_address = destination_address

    db.add(order)
    await db.commit()
    await db.refresh(order)

    await log_event(
        db,
        "CLIENT_DIRECT_PAYMENT_CREATED",
        {
            "order_id": str(order.id),
            "external_id": external_id,
            "network": network.value,
            "crypto_currency": currency,
            "crypto_amount": str(amount),
        },
        order.id,
        client_id=account.api_client_id,
    )

    return _order_json(order)


@router.post("/client/circle-payment")
async def client_circle_payment(request: Request, db: AsyncSession = Depends(get_db)):
    account = await _current_account(request, db)
    payload = await request.json()

    network = _network(payload.get("network"))
    fiat_amount = _amount(payload.get("fiat_amount"))
    fiat_currency = str(payload.get("fiat_currency") or "USD").upper()
    crypto_currency = str(payload.get("crypto_currency") or "USDC").upper()
    external_id = str(payload.get("external_id") or f"CIR-{uuid.uuid4().hex[:10]}")
    destination_address = _ledger_address(network)

    provider = await get_provider(Provider.CIRCLE)

    provider_payload = {
        "walletAddress": destination_address,
        "cryptoCurrency": crypto_currency,
        "network": network.value,
        "fiatCurrency": fiat_currency,
        "fiatAmount": fiat_amount,
        "redirectURL": f"{_public_base_url()}/pay/success",
        "partnerUserRef": external_id,
        "clientIp": _request_ip(request),
    }
    provider_payload = {k: v for k, v in provider_payload.items() if v is not None}

    checkout_url, quote = await provider.create_widget_url(provider_payload)

    def _safe_json(obj):
        if obj is None:
            return None
        import json
        from decimal import Decimal as _Decimal
        def _default(o):
            if isinstance(o, _Decimal):
                return str(o)
            raise TypeError(f"Not serializable: {type(o)}")
        return json.loads(json.dumps(obj, default=_default))

    # Use Provider.MOONPAY in DB until 'circle' enum migration runs on PostgreSQL.
    # Circle orders are identified by external_id prefix "CIR-" and idempotency_key prefix "client-circle-".
    order = PaymentOrder(
        client_id=account.api_client_id,
        idempotency_key=f"client-circle-{uuid.uuid4()}",
        external_id=external_id,
        provider=Provider.MOONPAY,
        side=OrderSide.BUY,
        status=OrderStatus.CREATED,
        network=network,
        fiat_currency=fiat_currency,
        fiat_amount=fiat_amount,
        crypto_currency=crypto_currency,
        crypto_amount=None,
        user_wallet_address=destination_address,
        quote_json=_safe_json(quote),
        checkout_url=checkout_url,
    )

    if hasattr(order, "treasury_wallet_address"):
        order.treasury_wallet_address = destination_address

    if hasattr(order, "coinbase_session_url"):
        order.coinbase_session_url = checkout_url

    db.add(order)
    await db.commit()
    await db.refresh(order)

    await log_event(
        db,
        "CLIENT_CIRCLE_PAYMENT_CREATED",
        {
            "order_id": str(order.id),
            "external_id": external_id,
            "network": network.value,
            "fiat_currency": fiat_currency,
            "fiat_amount": str(fiat_amount),
            "crypto_currency": crypto_currency,
            "checkout_url": checkout_url,
        },
        order.id,
        client_id=account.api_client_id,
    )

    return _order_json(order)


@router.post("/client/onramper-payment")
async def client_onramper_payment(request: Request, db: AsyncSession = Depends(get_db)):
    """Create an Onramper widget link for the client (card, bank transfer, Apple/Google Pay)."""
    account = await _current_account(request, db)
    payload = await request.json()

    network = _network(payload.get("network"))
    fiat_amount = _amount(payload.get("fiat_amount"))
    fiat_currency = str(payload.get("fiat_currency") or "USD").upper()
    crypto = str(payload.get("crypto") or "USDC").upper()
    external_id = str(payload.get("external_id") or f"ONR-{uuid.uuid4().hex[:10]}")
    destination_address = _ledger_address(network)

    provider = OnramperProvider()
    provider_payload = {
        "walletAddress": destination_address,
        "network": network.value,
        "fiatCurrency": fiat_currency,
        "fiat_currency": fiat_currency,
        "fiatAmount": fiat_amount,
        "fiat_amount": fiat_amount,
        "crypto": crypto,
        "cryptoCurrency": crypto,
        "partnerUserRef": external_id,
        "external_id": external_id,
        "clientIp": _request_ip(request),
    }
    provider_payload = {k: v for k, v in provider_payload.items() if v is not None}

    checkout_url, quote = await provider.create_widget_url(provider_payload)

    # Use Provider.MOONPAY in DB — ONR- prefix identifies Onramper orders
    order = PaymentOrder(
        client_id=account.api_client_id,
        idempotency_key=f"client-onramper-{uuid.uuid4()}",
        external_id=external_id,
        provider=Provider.MOONPAY,
        side=OrderSide.BUY,
        status=OrderStatus.CREATED,
        network=network,
        fiat_currency=fiat_currency,
        fiat_amount=fiat_amount,
        crypto_currency=crypto,
        crypto_amount=None,
        user_wallet_address=destination_address,
        quote_json=quote,
        checkout_url=checkout_url,
    )

    if hasattr(order, "treasury_wallet_address"):
        order.treasury_wallet_address = destination_address

    db.add(order)
    await db.commit()
    await db.refresh(order)

    await log_event(
        db,
        "CLIENT_ONRAMPER_PAYMENT_CREATED",
        {
            "order_id": str(order.id),
            "external_id": external_id,
            "network": network.value,
            "fiat_currency": fiat_currency,
            "fiat_amount": str(fiat_amount),
            "crypto": crypto,
            "checkout_url": checkout_url,
        },
        order.id,
        client_id=account.api_client_id,
    )

    return _order_json(order)


@router.post("/client/moonpay-payment")
@router.post("/client/coinbase-payment", deprecated=True)
async def client_moonpay_payment(request: Request, db: AsyncSession = Depends(get_db)):
    account = await _current_account(request, db)
    payload = await request.json()

    network = _network(payload.get("network"))
    fiat_amount = _amount(payload.get("fiat_amount"))
    fiat_currency = str(payload.get("fiat_currency") or "USD").upper()
    crypto_currency = str(payload.get("crypto_currency") or "USDC").upper()
    external_id = str(payload.get("external_id") or f"MP-{uuid.uuid4().hex[:10]}")
    destination_address = _ledger_address(network)

    provider = await get_provider(Provider.MOONPAY)

    provider_payload = {
        "walletAddress": destination_address,
        "cryptoCurrency": crypto_currency,
        "network": network.value,
        "fiatCurrency": fiat_currency,
        "fiatAmount": fiat_amount,
        "country": payload.get("country"),
        "subdivision": payload.get("subdivision"),
        "redirectURL": f"{_public_base_url()}/pay/success",
        "partnerUserRef": external_id,
        "clientIp": _request_ip(request),
    }
    provider_payload = {
        key: value for key, value in provider_payload.items() if value is not None
    }

    checkout_url, quote = await provider.create_widget_url(provider_payload)

    # Ensure quote_json is JSON-serializable (convert Decimal/etc to str)
    def _safe_json(obj):
        if obj is None:
            return None
        import json
        from decimal import Decimal as _Decimal
        def _default(o):
            if isinstance(o, _Decimal):
                return str(o)
            raise TypeError(f"Not serializable: {type(o)}")
        return json.loads(json.dumps(obj, default=_default))

    order = PaymentOrder(
        client_id=account.api_client_id,
        idempotency_key=f"client-moonpay-{uuid.uuid4()}",
        external_id=external_id,
        provider=Provider.MOONPAY,
        side=OrderSide.BUY,
        status=OrderStatus.CREATED,
        network=network,
        fiat_currency=fiat_currency,
        fiat_amount=fiat_amount,
        crypto_currency=crypto_currency,
        crypto_amount=None,
        user_wallet_address=destination_address,
        quote_json=_safe_json(quote),
        checkout_url=checkout_url,
    )

    if hasattr(order, "treasury_wallet_address"):
        order.treasury_wallet_address = destination_address

    if hasattr(order, "coinbase_session_url"):
        order.coinbase_session_url = checkout_url

    db.add(order)
    await db.commit()
    await db.refresh(order)

    await log_event(
        db,
        "CLIENT_MOONPAY_PAYMENT_CREATED",
        {
            "order_id": str(order.id),
            "external_id": external_id,
            "network": network.value,
            "fiat_currency": fiat_currency,
            "fiat_amount": str(fiat_amount),
            "crypto_currency": crypto_currency,
            "checkout_url": checkout_url,
        },
        order.id,
        client_id=account.api_client_id,
    )

    return _order_json(order)


# ── Client API Key endpoints ──────────────────────────────────────────────────
# Scope: client_only — payload upload & system linking only.
# Cannot access any admin endpoint.

@router.get("/client/apikey")
async def client_get_apikey(request: Request, db: AsyncSession = Depends(get_db)):
    """Reveal a fresh API key for the client (payload upload & system linking only)."""
    account = await _current_account(request, db)

    result = await db.execute(
        select(ApiClient).where(cast(ApiClient.id, String) == str(account.api_client_id))
    )
    api_client = result.scalar_one_or_none()
    if not api_client:
        raise HTTPException(status_code=404, detail="API client not found")

    new_key = create_api_key()
    api_client.api_key_hash = hash_api_key(new_key)
    await db.commit()

    await log_event(
        db, "CLIENT_APIKEY_REVEALED",
        {"ip": _request_ip(request)}, None, client_id=account.api_client_id,
    )

    return {
        "api_key": new_key,
        "client_id": str(account.api_client_id),
        "scope": "client_only",
        "allowed_endpoints": [
            "POST /api/v1/payloads/ingest",
            "GET /api/v1/payloads/{id}",
            "POST /client/direct-payment",
        ],
        "header": "X-API-Key",
        "note": "Client-level key only. Admin endpoints are NOT accessible with this key.",
    }


@router.post("/client/rotate-apikey")
async def client_rotate_apikey(request: Request, db: AsyncSession = Depends(get_db)):
    """Revoke current key and issue a new client-scope key."""
    account = await _current_account(request, db)

    result = await db.execute(
        select(ApiClient).where(cast(ApiClient.id, String) == str(account.api_client_id))
    )
    api_client = result.scalar_one_or_none()
    if not api_client:
        raise HTTPException(status_code=404, detail="API client not found")

    new_key = create_api_key()
    api_client.api_key_hash = hash_api_key(new_key)
    await db.commit()

    await log_event(
        db, "CLIENT_APIKEY_ROTATED",
        {"ip": _request_ip(request)}, None, client_id=account.api_client_id,
    )

    return {
        "api_key": new_key,
        "client_id": str(account.api_client_id),
        "scope": "client_only",
        "note": "Previous key revoked. New key for payload upload & system linking only.",
        "header": "X-API-Key",
    }
