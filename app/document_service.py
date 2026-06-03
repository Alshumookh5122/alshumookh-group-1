from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from html import escape
from urllib.parse import quote

from app.config import get_settings
from app.models import OrderStatus, PaymentOrder

settings = get_settings()

ETHEREUM_LEDGER_WALLET = "0xBD682cfD8382a90adfDd6745780D3D7959c4d939"
TRON_LEDGER_WALLET = "TLARV2U9NzuK9QfzV3PQjwabQTGiEEqjTn"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _money(amount: Decimal | float | None, currency: str | None) -> str:
    if amount is None:
        return f"- {currency or ''}".strip()

    value = Decimal(str(amount))
    text = f"{value:,.8f}".rstrip("0").rstrip(".")
    return f"{text} {currency or ''}".strip()


def _doc_number(prefix: str, order: PaymentOrder) -> str:
    created = order.created_at or _now()
    date_part = created.strftime("%Y%m%d")
    short_id = str(order.id).split("-")[0].upper()
    return f"{prefix}-{date_part}-{short_id}"


def _status_label(status: OrderStatus) -> str:
    labels = {
        OrderStatus.CREATED: "Pending",
        OrderStatus.PENDING: "Pending",
        OrderStatus.PROCESSING: "Processing",
        OrderStatus.COMPLETED: "Completed",
        OrderStatus.FAILED: "Failed",
        OrderStatus.REFUNDED: "Refunded",
        OrderStatus.EXPIRED: "Expired",
    }

    return labels.get(status, status.value)


def _public_base_url() -> str:
    value = (
        getattr(settings, "public_base_url", None)
        or getattr(settings, "public_app_url", None)
        or "https://api.alshumookh-pay.com"
    )

    return str(value).rstrip("/")


def _logo_url() -> str:
    configured = getattr(settings, "company_logo_url", None)

    if configured:
        return str(configured)

    return f"{_public_base_url()}/static/company-logo.png"


def _configured_tron_wallet() -> str:
    return (
        getattr(settings, "master_wallet_tron", None)
        or getattr(settings, "ledger_tron_address", None)
        or getattr(settings, "tron_treasury_address", None)
        or getattr(settings, "circle_wallet_address", None)
        or TRON_LEDGER_WALLET
    )


def _wallet_address(order: PaymentOrder, *, prefer_tron: bool = False) -> str:
    if prefer_tron:
        return _configured_tron_wallet()

    return (
        getattr(order, "treasury_wallet_address", None)
        or getattr(order, "user_wallet_address", None)
        or ETHEREUM_LEDGER_WALLET
    )


def _payment_url(order: PaymentOrder) -> str:
    return (
        getattr(order, "checkout_url", None)
        or getattr(order, "coinbase_session_url", None)
        or f"{_public_base_url()}/pay/direct/{order.id}"
    )


def _is_stripe_order(order: PaymentOrder) -> bool:
    provider = getattr(order, "provider", "")
    value = getattr(provider, "value", provider)
    return str(value).lower() == "stripe"


def _qr_url(data: str, size: int = 180) -> str:
    return (
        "https://api.qrserver.com/v1/create-qr-code/"
        f"?size={size}x{size}&data={quote(data)}"
    )


def _wallet_qr_url(
    order: PaymentOrder,
    size: int = 180,
    *,
    wallet: str | None = None,
    network_label: str | None = None,
) -> str:
    wallet = wallet or _wallet_address(order)
    network = network_label or order.network.value

    data = "\n".join(
        [
            "ALSHUMOOKH GLOBAL BANKING FINANCE & CREDIT",
            f"Wallet: {wallet}",
            f"Network: {network.upper()}",
            f"Currency: {order.crypto_currency}",
            f"Amount: {_money(order.crypto_amount, order.crypto_currency)}",
            f"Reference: {getattr(order, 'payment_reference', None) or order.external_id or order.id}",
        ]
    )

    return _qr_url(data, size)


def _payment_qr_url(order: PaymentOrder, size: int = 180) -> str:
    return _qr_url(_payment_url(order), size)


def document_summary(order: PaymentOrder) -> dict:
    is_complete = order.status == OrderStatus.COMPLETED

    return {
        "transaction_id": str(order.id),
        "external_id": order.external_id,
        "status": order.status.value,
        "network": order.network.value,
        "fiat_amount": str(order.fiat_amount) if order.fiat_amount is not None else None,
        "fiat_currency": order.fiat_currency,
        "crypto_amount": str(order.crypto_amount) if order.crypto_amount is not None else None,
        "crypto_currency": order.crypto_currency,
        "wallet": _wallet_address(order),
        "created_at": order.created_at,
        "invoice_number": _doc_number("INV", order),
        "receive_receipt_number": _doc_number("RCV", order) if is_complete else None,
        "send_receipt_number": _doc_number("SND", order) if is_complete else None,
        "invoice_url": f"/api/v1/admin/orders/{order.id}/documents/invoice",
        "pending_url": f"/api/v1/admin/orders/{order.id}/documents/pending",
        "receive_receipt_url": (
            f"/api/v1/admin/orders/{order.id}/documents/receive-receipt"
            if is_complete
            else None
        ),
        "send_receipt_url": (
            f"/api/v1/admin/orders/{order.id}/documents/send-receipt"
            if is_complete
            else None
        ),
    }


def render_order_document(order: PaymentOrder, document_type: str) -> str:
    if document_type == "invoice":
        title = "Invoice"
        number = _doc_number("INV", order)
        subtitle = "Official payment invoice for Stripe, MoonPay Commerce, or direct crypto transaction"
        note = "This invoice remains pending until Stripe, MoonPay, blockchain confirmation, or admin confirmation completes the transaction."

    elif document_type == "pending":
        title = "Pending Notice"
        number = _doc_number("PND", order)
        subtitle = "Pending payment and settlement notice"
        note = "The transaction is waiting for payment, blockchain confirmation, or MoonPay webhook confirmation."

    elif document_type == "receive-receipt":
        title = "Receive Receipt"
        number = _doc_number("RCV", order)
        subtitle = "Receipt for payment received by ALSHUMOOKH GLOBAL BANKING FINANCE & CREDIT"
        note = "This receipt confirms the system marked the transaction as completed."

    elif document_type == "send-receipt":
        title = "Send Receipt"
        number = _doc_number("SND", order)
        subtitle = "Receipt for crypto delivery to the configured Ledger wallet"
        note = "MoonPay Commerce or direct crypto payment delivers crypto to the Ledger destination address."

    elif document_type == "statement":
        title = "Bank Transaction Statement"
        number = _doc_number("STM", order)
        subtitle = "Official transaction statement issued by ALSHUMOOKH GLOBAL BANKING FINANCE & CREDIT"
        note = "This statement summarizes the selected transaction, status, references, wallet movement, provider data, and audit-ready settlement details."

    else:
        raise ValueError("Unsupported document type")

    status = _status_label(order.status)
    issued_at = _now().strftime("%Y-%m-%d %H:%M UTC")
    created_at = order.created_at.strftime("%Y-%m-%d %H:%M UTC") if order.created_at else "-"
    prefer_tron_wallet = document_type in {"invoice", "pending"}
    wallet_address = _wallet_address(order, prefer_tron=prefer_tron_wallet)
    document_network = "tron" if prefer_tron_wallet else order.network.value

    payment_url = _payment_url(order)
    is_stripe = _is_stripe_order(order)
    qr_url = (
        _payment_qr_url(order)
        if is_stripe and getattr(order, "checkout_url", None)
        else _wallet_qr_url(order, wallet=wallet_address, network_label=document_network)
    )
    logo_url = _logo_url()
    payment_url_label = "Stripe Payment Link" if is_stripe else "Payment URL"
    qr_label = "Stripe Payment QR" if is_stripe else "Wallet Payment QR"

    if is_stripe:
        method_cards = f"""
          <div class="method">
            <strong>Stripe Card Payment</strong>
            <span>Open the secure Stripe-hosted payment page to pay by supported card or wallet methods enabled in Stripe.</span>
          </div>

          <div class="method">
            <strong>Stripe Payment Link</strong>
            <span>The official payment link is listed in this invoice and embedded in the QR code.</span>
          </div>

          <div class="method">
            <strong>Official Invoice Record</strong>
            <span>This invoice is tied to internal order {escape(str(order.id))} and Stripe reference {escape(getattr(order, "provider_order_id", None) or "-")}.</span>
          </div>
        """
    else:
        method_cards = f"""
          <div class="method">
            <strong>Card Payment</strong>
            <span>Open the MoonPay payment link. Payment options depend on MoonPay and payer eligibility.</span>
          </div>

          <div class="method">
            <strong>Bank Transfer</strong>
            <span>MoonPay may offer supported card, wallet, or local payment options inside checkout where available.</span>
          </div>

          <div class="method">
            <strong>Direct Crypto</strong>
            <span>Scan the QR code or send only {escape(order.crypto_currency)} on {escape(document_network)} to the Ledger destination wallet.</span>
          </div>
        """

    rows = [
        ("Document Number", number),
        ("Transaction ID", str(order.id)),
        ("External ID", order.external_id or "-"),
        ("Provider", order.provider.value),
        ("Status", status),
        ("Fiat Amount", _money(order.fiat_amount, order.fiat_currency)),
        ("Crypto Amount", _money(order.crypto_amount, order.crypto_currency)),
        ("Network", document_network),
        ("Ledger Destination Wallet", wallet_address),
        (payment_url_label, payment_url),
        ("Provider Order ID", getattr(order, "provider_order_id", None) or "-"),
        ("Transaction Hash", getattr(order, "tx_hash", None) or "-"),
        ("Idempotency Key", getattr(order, "idempotency_key", None) or "-"),
        ("Payer Email", getattr(order, "payer_email", None) or "-"),
        ("Customer Wallet", getattr(order, "customer_wallet_address", None) or "-"),
        ("Created At", created_at),
        ("Issued At", issued_at),
    ]

    if order.failure_reason:
        rows.append(("Failure Reason", order.failure_reason))

    rows_html = "".join(
        f"<tr><th>{escape(label)}</th><td>{escape(str(value))}</td></tr>"
        for label, value in rows
    )

    payment_button = ""
    if is_stripe and payment_url:
        payment_button = (
            f'<a class="payment-link" href="{escape(payment_url)}" target="_blank" '
            'rel="noopener">Open Stripe Payment Page</a>'
        )

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)} {escape(number)}</title>

  <style>
    :root {{
      --ink:#111827;
      --muted:#667085;
      --line:#d9e1ea;
      --brand:#1f5fd0;
      --gold:#c79a45;
      --soft:#f7f9fc;
      --dark:#111820;
    }}

    * {{
      box-sizing: border-box;
    }}

    body {{
      margin: 0;
      padding: 36px;
      color: var(--ink);
      font-family: Arial, sans-serif;
      background: #f2f5f8;
    }}

    .sheet {{
      max-width: 960px;
      margin: 0 auto;
      padding: 36px;
      background: white;
      border: 1px solid var(--line);
      box-shadow: 0 18px 50px rgba(15, 23, 42, 0.08);
    }}

    .head {{
      display: flex;
      justify-content: space-between;
      gap: 24px;
      border-bottom: 2px solid var(--line);
      padding-bottom: 22px;
    }}

    .brand-block {{
      display: flex;
      align-items: center;
      gap: 16px;
    }}

    .logo {{
      width: 110px;
      height: 82px;
      object-fit: contain;
      border: 1px solid #ead8ad;
      border-radius: 8px;
      padding: 7px;
      background: #080808;
    }}

    .logo-fallback {{
      width: 74px;
      height: 74px;
      display: none;
      align-items: center;
      justify-content: center;
      border-radius: 8px;
      background: var(--gold);
      color: var(--dark);
      font-weight: 900;
      font-size: 20px;
    }}

    .brand {{
      color: var(--gold);
      font-size: 13px;
      font-weight: 900;
      text-transform: uppercase;
    }}

    h1 {{
      margin: 8px 0 0;
      font-size: 34px;
      letter-spacing: 0;
    }}

    h2 {{
      margin: 24px 0 8px;
      font-size: 20px;
    }}

    p {{
      color: var(--muted);
      line-height: 1.6;
    }}

    .doc-number {{
      text-align: right;
      min-width: 170px;
    }}

    .doc-number strong {{
      display: block;
      margin-bottom: 10px;
    }}

    .summary {{
      display: grid;
      grid-template-columns: 1fr 220px;
      gap: 24px;
      align-items: start;
      margin-top: 22px;
    }}

    .qr-box {{
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px;
      text-align: center;
      background: var(--soft);
    }}

    .qr-box img {{
      width: 180px;
      height: 180px;
      background: white;
      padding: 8px;
      border-radius: 6px;
    }}

    .qr-box strong {{
      display: block;
      margin-top: 10px;
      font-size: 13px;
    }}

    .methods {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 12px;
      margin-top: 14px;
    }}

    .method {{
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 13px;
      background: #fbfcff;
    }}

    .method strong {{
      display: block;
      margin-bottom: 6px;
    }}

    .method span {{
      color: var(--muted);
      font-size: 13px;
      line-height: 1.45;
    }}

    .payment-link {{
      display: inline-block;
      margin-top: 16px;
      padding: 12px 16px;
      border-radius: 6px;
      background: var(--brand);
      color: #fff;
      font-weight: 800;
      text-decoration: none;
    }}

    table {{
      width: 100%;
      border-collapse: collapse;
      margin-top: 22px;
    }}

    th,
    td {{
      padding: 13px 10px;
      border-bottom: 1px solid var(--line);
      text-align: left;
      vertical-align: top;
    }}

    th {{
      width: 260px;
      color: var(--muted);
      font-weight: 700;
    }}

    td {{
      word-break: break-word;
    }}

    .status {{
      display: inline-block;
      padding: 8px 12px;
      border-radius: 6px;
      background: #fff6df;
      color: #8a5c00;
      font-weight: 900;
    }}

    .footer {{
      margin-top: 30px;
      padding-top: 18px;
      border-top: 1px solid var(--line);
      color: var(--muted);
      font-size: 13px;
    }}

    .actions {{
      max-width: 960px;
      margin: 18px auto 0;
      text-align: right;
    }}

    button {{
      min-height: 40px;
      padding: 8px 14px;
      border: 1px solid var(--brand);
      border-radius: 6px;
      background: var(--brand);
      color: white;
      font-weight: 700;
      cursor: pointer;
    }}

    @media (max-width: 760px) {{
      body {{
        padding: 18px;
      }}

      .head,
      .summary,
      .methods {{
        display: grid;
        grid-template-columns: 1fr;
      }}

      .doc-number {{
        text-align: left;
      }}
    }}

    @media print {{
      body {{
        background: white;
        padding: 0;
      }}

      .sheet {{
        border: 0;
        box-shadow: none;
      }}

      .actions {{
        display: none;
      }}
    }}
  </style>
</head>

<body>
  <section class="sheet">
    <div class="head">
      <div class="brand-block">
        <img
          class="logo"
          src="{escape(logo_url)}"
          alt="AL SHUMOOKH GROUP Logo"
          onerror="this.style.display='none';this.nextElementSibling.style.display='flex';"
        >
        <div class="logo-fallback">SG</div>

        <div>
          <div class="brand">ALSHUMOOKH GLOBAL BANKING FINANCE & CREDIT</div>
          <h1>{escape(title)}</h1>
          <p>{escape(subtitle)}</p>
        </div>
      </div>

      <div class="doc-number">
        <strong>{escape(number)}</strong>
        <span class="status">{escape(status)}</span>
      </div>
    </div>

    <div class="summary">
      <div>
        <h2>Payment Methods</h2>

        <div class="methods">
          {method_cards}
        </div>

        {payment_button}
      </div>

      <div class="qr-box">
        <img src="{escape(qr_url)}" alt="Wallet Payment QR Code">
        <strong>{escape(qr_label)}</strong>
      </div>
    </div>

    <h2>Transaction Details</h2>
    <table>{rows_html}</table>

    <div class="footer">
      {escape(note)}<br>
      This document does not expose API keys, private keys, database credentials, or webhook secrets.
    </div>
  </section>

  <div class="actions">
    <button onclick="window.print()">Print / Save PDF</button>
  </div>
</body>
</html>"""
