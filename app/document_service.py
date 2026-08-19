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
    quote = order.quote_json or {}
    gas_estimate = quote.get("gas_fee_estimate") if isinstance(quote, dict) else None
    is_gas_invoice = isinstance(quote, dict) and quote.get("type") == "M1_GAS_FEE_INVOICE"
    prefer_tron_wallet = document_type in {"invoice", "pending"}
    wallet_address = _wallet_address(order, prefer_tron=prefer_tron_wallet)
    document_network = "tron" if prefer_tron_wallet else order.network.value
    job_details = quote.get("tokenization_job") if isinstance(quote, dict) else None
    if not isinstance(job_details, dict):
        job_details = {}

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

    if is_gas_invoice:
        method_cards = f"""
          <div class="method">
            <strong>USDT TRC20 Gas Fee</strong>
            <span>This invoice collects the approved gas fee amount in USDT TRC20 on the TRON network.</span>
          </div>

          <div class="method">
            <strong>Linked M1 Transaction</strong>
            <span>The fee is tied to M1 job {escape(str(quote.get("tokenization_job_id") or "-"))} and the related fiat-to-crypto settlement record.</span>
          </div>

          <div class="method">
            <strong>TRON Treasury Wallet</strong>
            <span>Send only USDT TRC20 to the listed TRON treasury wallet. Do not send ETH or ERC-20 funds for this fee.</span>
          </div>
        """
    elif is_stripe:
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

    if is_gas_invoice:
        linked_rows = [
            ("Linked M1 Job ID", quote.get("tokenization_job_id") or "-"),
            ("Sender Reference", job_details.get("sender_reference") or "-"),
            ("Sender Name", job_details.get("sender_name") or "-"),
            ("Sender IBAN", job_details.get("sender_iban") or "-"),
            ("EUR Transaction Amount", _money(job_details.get("eur_amount"), "EUR")),
            ("FX Rate EUR/USD", job_details.get("fx_rate_eur_usd") or "-"),
            ("USD Converted Amount", _money(job_details.get("usd_amount"), "USD")),
            ("USDT Settlement Amount", _money(job_details.get("usdt_amount"), "USDT")),
            ("Original Settlement Network", job_details.get("network") or "-"),
            ("Original Destination Wallet", job_details.get("destination_wallet") or "-"),
            ("Outbound Transfer ID", job_details.get("outbound_transfer_id") or "-"),
            ("M1 Job Status", job_details.get("status") or "-"),
        ]
        rows.extend(linked_rows)

    if order.failure_reason:
        rows.append(("Failure Reason", order.failure_reason))

    amount_due = _money(order.crypto_amount, order.crypto_currency)
    gas_panel = ""
    if is_gas_invoice and isinstance(gas_estimate, dict):
        gas_rows = [
            ("Gas Fee Amount", amount_due),
            ("Settlement Asset", "USDT TRC20"),
            ("Network", "TRON"),
            ("Treasury Wallet", wallet_address),
            ("Source", "Manual Admin Override" if gas_estimate.get("manual_override") else gas_estimate.get("source") or "Estimated"),
            ("Tokenization Job ID", quote.get("tokenization_job_id") or "-"),
        ]
        gas_rows_html = "".join(
            f"<tr><th>{escape(str(label))}</th><td>{escape(str(value or '-'))}</td></tr>"
            for label, value in gas_rows
        )
        gas_panel = f"""
          <section class="gas-panel">
            <div>
              <div class="eyebrow">M1 Tokenization Gas Fee</div>
              <h2>Gas Fee Authorization</h2>
              <p>This invoice was generated for the approved M1 gas fee. The payable amount is denominated in USDT TRC20 and collected on TRON.</p>
            </div>
            <table class="gas-table">{gas_rows_html}</table>
          </section>
        """

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
      --brand:#1a3a6b;
      --brand2:#2656a8;
      --gold:#b8860b;
      --gold2:#d4a017;
      --soft:#f7f9fc;
      --dark:#0f1f3d;
      --green:#0a7a4a;
      --red:#c0392b;
    }}

    * {{
      box-sizing: border-box;
    }}

    body {{
      margin: 0;
      padding: 32px;
      color: var(--ink);
      font-family: 'Times New Roman', Georgia, serif;
      background: #e8ecf0;
    }}

    /* Top gold accent bar */
    .gold-bar {{
      height: 7px;
      background: linear-gradient(90deg, var(--brand) 0%, var(--gold2) 50%, var(--brand) 100%);
      border-radius: 3px 3px 0 0;
    }}

    .sheet {{
      max-width: 970px;
      margin: 0 auto;
      padding: 0;
      background: white;
      border: 1px solid #c8d0dc;
      box-shadow: 0 20px 60px rgba(15, 23, 42, 0.14), inset 0 0 0 4px rgba(26,58,107,0.04);
    }}

    .sheet-inner {{
      padding: 36px 40px 32px;
    }}

    /* Banking certification band */
    .cert-band {{
      background: linear-gradient(135deg, var(--brand) 0%, var(--brand2) 100%);
      color: white;
      padding: 8px 40px;
      font-size: 10px;
      letter-spacing: .12em;
      text-transform: uppercase;
      display: flex;
      justify-content: space-between;
      align-items: center;
    }}

    .head {{
      display: flex;
      justify-content: space-between;
      gap: 24px;
      border-bottom: 2px solid var(--brand);
      padding-bottom: 22px;
      margin-bottom: 6px;
    }}

    .brand-block {{
      display: flex;
      align-items: center;
      gap: 18px;
    }}

    .logo-wrap {{
      border: 2px solid var(--gold);
      border-radius: 6px;
      padding: 6px;
      background: #0f1f3d;
    }}

    .logo {{
      width: 100px;
      height: 75px;
      object-fit: contain;
      display: block;
    }}

    .logo-fallback {{
      width: 70px;
      height: 70px;
      display: none;
      align-items: center;
      justify-content: center;
      border-radius: 6px;
      background: var(--brand);
      color: white;
      font-weight: 900;
      font-size: 18px;
      font-family: Arial, sans-serif;
      letter-spacing:.04em;
    }}

    .brand {{
      color: var(--brand);
      font-size: 11.5px;
      font-weight: 900;
      text-transform: uppercase;
      letter-spacing: .07em;
      font-family: Arial, sans-serif;
    }}

    .brand-tagline {{
      font-size: 10px;
      color: var(--muted);
      font-family: Arial, sans-serif;
      margin-top: 2px;
    }}

    h1 {{
      margin: 8px 0 2px;
      font-size: 30px;
      color: var(--dark);
      font-family: 'Times New Roman', Georgia, serif;
      font-weight: 700;
    }}

    h2 {{
      margin: 20px 0 8px;
      font-size: 17px;
      color: var(--brand);
      font-family: Arial, sans-serif;
      border-left: 3px solid var(--gold);
      padding-left: 10px;
    }}

    p {{
      color: var(--muted);
      line-height: 1.6;
      font-size: 13px;
    }}

    .doc-number {{
      text-align: right;
      min-width: 200px;
      border-left: 1px solid var(--line);
      padding-left: 20px;
    }}

    .doc-number .num {{
      font-family: 'Courier New', monospace;
      font-size: 13px;
      font-weight: 900;
      color: var(--brand);
      background: #f0f4ff;
      padding: 4px 10px;
      border-radius: 4px;
      display: inline-block;
      margin-bottom: 10px;
      border: 1px solid #c5d3ee;
    }}

    .doc-number .issued {{
      font-size: 11px;
      color: var(--muted);
      display: block;
      margin-bottom: 8px;
      font-family: Arial, sans-serif;
    }}

    .summary {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) 200px;
      gap: 24px;
      align-items: start;
      margin-top: 20px;
    }}

    .amount-due {{
      margin-top: 22px;
      display: grid;
      grid-template-columns: minmax(0, 1fr) 260px;
      border: 2px solid var(--brand);
      border-radius: 8px;
      overflow: hidden;
    }}

    .amount-due .left {{
      padding: 16px 20px;
      background: #f8faff;
    }}

    .amount-due .right {{
      padding: 16px 20px;
      background: var(--brand);
      color: #fff;
      text-align: right;
    }}

    .amount-due .label {{
      font-size: 10px;
      font-weight: 900;
      text-transform: uppercase;
      letter-spacing: .1em;
      font-family: Arial, sans-serif;
    }}

    .amount-due .left .label {{
      color: var(--muted);
    }}

    .amount-due .right .label {{
      color: rgba(255,255,255,0.7);
    }}

    .amount-due .total {{
      margin-top: 8px;
      font-size: 26px;
      font-weight: 900;
      color: var(--gold2);
      font-family: 'Times New Roman', Georgia, serif;
    }}

    .qr-box {{
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 12px;
      text-align: center;
      background: var(--soft);
    }}

    .qr-box img {{
      width: 170px;
      height: 170px;
      background: white;
      padding: 6px;
      border: 1px solid var(--line);
      border-radius: 4px;
    }}

    .qr-box strong {{
      display: block;
      margin-top: 8px;
      font-size: 11px;
      font-family: Arial, sans-serif;
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: .06em;
    }}

    .methods {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 10px;
      margin-top: 12px;
    }}

    .method {{
      border: 1px solid var(--line);
      border-radius: 6px;
      border-top: 3px solid var(--brand);
      padding: 11px;
      background: #fbfcff;
    }}

    .method strong {{
      display: block;
      margin-bottom: 5px;
      font-size: 12px;
      color: var(--brand);
      font-family: Arial, sans-serif;
    }}

    .method span {{
      color: var(--muted);
      font-size: 12px;
      line-height: 1.45;
    }}

    .payment-link {{
      display: inline-block;
      margin-top: 14px;
      padding: 10px 18px;
      border-radius: 5px;
      background: var(--brand);
      color: #fff;
      font-weight: 800;
      text-decoration: none;
      font-family: Arial, sans-serif;
      font-size: 13px;
    }}

    .gas-panel {{
      margin-top: 22px;
      padding: 18px 20px;
      border: 1px solid #d9c38a;
      border-left: 4px solid var(--gold);
      border-radius: 6px;
      background: linear-gradient(135deg, #fffdf5, #ffffff);
    }}

    .eyebrow {{
      color: var(--gold);
      font-size: 10px;
      font-weight: 900;
      letter-spacing: .1em;
      text-transform: uppercase;
      font-family: Arial, sans-serif;
    }}

    .gas-panel h2 {{
      margin-top: 4px;
    }}

    .gas-table {{
      margin-top: 10px;
      background: white;
      border: 1px solid var(--line);
      border-radius: 6px;
      overflow: hidden;
    }}

    table {{
      width: 100%;
      border-collapse: collapse;
      margin-top: 16px;
      font-size: 13px;
    }}

    th,
    td {{
      padding: 10px 12px;
      border-bottom: 1px solid var(--line);
      text-align: left;
      vertical-align: top;
    }}

    th {{
      width: 240px;
      color: var(--muted);
      font-weight: 700;
      font-family: Arial, sans-serif;
      font-size: 12px;
      background: #f8faff;
    }}

    td {{
      word-break: break-word;
    }}

    tr:last-child th, tr:last-child td {{
      border-bottom: none;
    }}

    .status {{
      display: inline-block;
      padding: 5px 14px;
      border-radius: 4px;
      font-weight: 900;
      font-family: Arial, sans-serif;
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: .06em;
    }}

    .status-pending {{ background: #fff3cd; color: #7a5800; border: 1px solid #f0cc70; }}
    .status-completed {{ background: #d4edda; color: #1a5c32; border: 1px solid #90d4a5; }}
    .status-failed {{ background: #f8d7da; color: #7a1a20; border: 1px solid #f5a0a7; }}
    .status-default {{ background: #e0e8f8; color: #1a3a6b; border: 1px solid #b0c4e0; }}

    .seal-row {{
      margin-top: 22px;
      display: flex;
      justify-content: space-between;
      align-items: flex-end;
      gap: 20px;
      padding-top: 16px;
      border-top: 2px solid var(--brand);
    }}

    .legal-seal {{ display: inline-block; }}

    .auth-block {{
      flex: 1;
    }}

    .auth-block .auth-line {{
      border-bottom: 1px solid var(--ink);
      width: 200px;
      margin-top: 28px;
      margin-bottom: 4px;
    }}

    .auth-block .auth-label {{
      font-size: 10px;
      color: var(--muted);
      font-family: Arial, sans-serif;
    }}

    .footer {{
      margin-top: 22px;
      padding: 14px 16px;
      border: 1px solid var(--line);
      border-top: 3px solid var(--brand);
      background: #f8faff;
      font-family: Arial, sans-serif;
      border-radius: 0 0 4px 4px;
    }}

    .footer p {{
      margin: 0;
      font-size: 11px;
      color: var(--muted);
      line-height: 1.55;
    }}

    .footer .disclaimer {{
      font-size: 10px;
      color: #999;
      margin-top: 8px;
    }}

    .actions {{
      max-width: 970px;
      margin: 14px auto 0;
      text-align: right;
      display: flex;
      gap: 8px;
      justify-content: flex-end;
    }}

    button {{
      min-height: 38px;
      padding: 7px 16px;
      border: 1px solid var(--brand);
      border-radius: 5px;
      background: var(--brand);
      color: white;
      font-weight: 700;
      cursor: pointer;
      font-family: Arial, sans-serif;
      font-size: 13px;
    }}

    button.secondary {{
      background: white;
      color: var(--brand);
    }}

    @media (max-width: 760px) {{
      body {{
        padding: 12px;
      }}

      .head,
      .summary,
      .amount-due,
      .methods,
      .seal-row {{
        display: grid;
        grid-template-columns: 1fr;
      }}

      .doc-number {{
        text-align: left;
        border-left: none;
        padding-left: 0;
        border-top: 1px solid var(--line);
        padding-top: 12px;
      }}
    }}

    @media print {{
      /* Zero margin suppresses browser date/URL headers and footers */
      @page {{
        size: A4 portrait;
        margin: 0;
      }}

      * {{
        -webkit-print-color-adjust: exact !important;
        print-color-adjust: exact !important;
      }}

      body {{
        background: white !important;
        padding: 0 !important;
        margin: 0 !important;
      }}

      .sheet {{
        max-width: 100% !important;
        width: 100% !important;
        border: none !important;
        box-shadow: none !important;
        margin: 0 !important;
      }}

      .sheet-inner {{
        padding: 16px 26px 18px !important;
      }}

      /* Prevent cert-band from wrapping across two lines */
      .cert-band {{
        padding: 5px 26px !important;
        font-size: 8px !important;
        letter-spacing: .07em !important;
        white-space: nowrap !important;
        overflow: hidden !important;
      }}

      .gold-bar {{
        height: 5px !important;
      }}

      .actions {{
        display: none !important;
      }}

      h1 {{
        font-size: 24px !important;
        margin: 6px 0 2px !important;
      }}

      h2 {{
        font-size: 13px !important;
        margin: 10px 0 5px !important;
      }}

      p {{
        font-size: 11px !important;
        line-height: 1.5 !important;
      }}

      .head {{
        padding-bottom: 12px !important;
        margin-bottom: 3px !important;
        gap: 14px !important;
      }}

      .brand {{
        font-size: 10px !important;
      }}

      .brand-tagline {{
        font-size: 9px !important;
      }}

      .logo {{
        width: 80px !important;
        height: 60px !important;
      }}

      .doc-number .num {{
        font-size: 11px !important;
        padding: 3px 8px !important;
      }}

      .doc-number .issued {{
        font-size: 9.5px !important;
      }}

      .summary {{
        margin-top: 10px !important;
        gap: 16px !important;
      }}

      .methods {{
        gap: 7px !important;
        margin-top: 7px !important;
      }}

      .method {{
        padding: 8px 10px !important;
      }}

      .method strong {{
        font-size: 10.5px !important;
        margin-bottom: 3px !important;
      }}

      .method span {{
        font-size: 10px !important;
        line-height: 1.4 !important;
      }}

      .qr-box {{
        padding: 8px !important;
      }}

      .qr-box img {{
        width: 120px !important;
        height: 120px !important;
      }}

      .qr-box strong {{
        font-size: 9px !important;
        margin-top: 5px !important;
      }}

      .amount-due {{
        margin-top: 12px !important;
      }}

      .amount-due .left,
      .amount-due .right {{
        padding: 11px 16px !important;
      }}

      .amount-due .total {{
        font-size: 22px !important;
        margin-top: 5px !important;
      }}

      .amount-due .label {{
        font-size: 9px !important;
      }}

      .gas-panel {{
        margin-top: 12px !important;
        padding: 12px 16px !important;
      }}

      .gas-panel p {{
        font-size: 10.5px !important;
      }}

      table {{
        font-size: 11px !important;
        margin-top: 8px !important;
      }}

      th {{
        width: 175px !important;
        padding: 6px 10px !important;
        font-size: 10px !important;
      }}

      td {{
        padding: 6px 10px !important;
        font-size: 11px !important;
        word-break: break-all !important;
      }}

      .seal-row {{
        margin-top: 14px !important;
        padding-top: 10px !important;
        gap: 14px !important;
      }}

      .auth-block .auth-line {{
        width: 160px !important;
        margin-top: 20px !important;
      }}

      .auth-block .auth-label {{
        font-size: 9px !important;
      }}

      .legal-seal { display: inline-block !important; }

      .footer {{
        margin-top: 12px !important;
        padding: 9px 12px !important;
      }}

      .footer p {{
        font-size: 9.5px !important;
        line-height: 1.5 !important;
      }}

      .footer .disclaimer {{
        font-size: 8.5px !important;
        margin-top: 5px !important;
      }}
    }}
  </style>
</head>

<body>
  <section class="sheet">
    <div class="gold-bar"></div>

    <div class="cert-band">
      <span>ALSHUMOOKH GLOBAL BANKING FINANCE &amp; CREDIT — OFFICIAL DOCUMENT</span>
      <span>REG: AE-DMCC-2024 | BIC: ALSGBFC0 | TLS 1.3 SECURED</span>
    </div>

    <div class="sheet-inner">
      <div class="head">
        <div class="brand-block">
          <div class="logo-wrap">
            <img
              class="logo"
              src="{escape(logo_url)}"
              alt="AL SHUMOOKH GROUP Logo"
              onerror="this.style.display='none';this.nextElementSibling.style.display='flex';"
            >
            <div class="logo-fallback">SG</div>
          </div>

          <div>
            <div class="brand">ALSHUMOOKH GLOBAL BANKING FINANCE &amp; CREDIT</div>
            <div class="brand-tagline">Dubai — UAE · Financial Technology &amp; Digital Asset Services</div>
            <h1>{escape(title)}</h1>
            <p style="margin:4px 0 0;">{escape(subtitle)}</p>
          </div>
        </div>

        <div class="doc-number">
          <span class="issued">Document No.</span>
          <div class="num">{escape(number)}</div>
          <span class="issued">Issued: {escape(issued_at)}</span>
          <span class="status {"status-completed" if status == "Completed" else "status-pending" if status == "Pending" else "status-failed" if status == "Failed" else "status-default"}">{escape(status)}</span>
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

      <section class="amount-due">
        <div class="left">
          <div class="label">Document Purpose</div>
          <strong style="display:block;margin-top:6px;font-size:15px;">{escape(title)}</strong>
          <p style="margin-top:6px;font-size:12px;">{escape(note)}</p>
        </div>
        <div class="right">
          <div class="label">Amount Due</div>
          <div class="total">{escape(amount_due)}</div>
          <div style="font-size:11px;margin-top:8px;opacity:.75;">As of {escape(issued_at)}</div>
        </div>
      </section>

      {gas_panel}

      <h2>Transaction Details</h2>
      <table>{rows_html}</table>

      <div class="seal-row">
        <div class="auth-block">
          <div style="font-size:12px;color:var(--muted);font-family:Arial,sans-serif;">Authorized by</div>
          <div class="auth-line"></div>
          <div class="auth-label">ALSHUMOOKH GLOBAL BANKING FINANCE &amp; CREDIT</div>
          <div class="auth-label" style="margin-top:2px;">Compliance &amp; Settlement Division</div>
        </div>
        <svg width="90" height="90" viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg"><defs><path id="atDS" d="M 17,50 A 33,33 0 0,1 83,50"/><path id="abDS" d="M 83,50 A 33,33 0 0,1 17,50"/></defs><polygon points="50.0,3.0 56.6,8.5 64.5,5.3 69.1,12.6 77.6,12.0 79.7,20.3 88.0,22.4 87.4,30.9 94.7,35.5 91.5,43.4 97.0,50.0 91.5,56.6 94.7,64.5 87.4,69.1 88.0,77.6 79.7,79.7 77.6,88.0 69.1,87.4 64.5,94.7 56.6,91.5 50.0,97.0 43.4,91.5 35.5,94.7 30.9,87.4 22.4,88.0 20.3,79.7 12.0,77.6 12.6,69.1 5.3,64.5 8.5,56.6 3.0,50.0 8.5,43.4 5.3,35.5 12.6,30.9 12.0,22.4 20.3,20.3 22.4,12.0 30.9,12.6 35.5,5.3 43.4,8.5" fill="#0D1B3E"/><circle cx="50" cy="50" r="42" fill="#fdf8ef" stroke="#C9A84C" stroke-width="0.4"/><circle cx="50.0" cy="12.0" r="1.4" fill="#C9A84C"/><circle cx="59.8" cy="13.3" r="0.7" fill="#C9A84C"/><circle cx="69.0" cy="17.1" r="1.4" fill="#C9A84C"/><circle cx="76.9" cy="23.1" r="0.7" fill="#C9A84C"/><circle cx="82.9" cy="31.0" r="1.4" fill="#C9A84C"/><circle cx="86.7" cy="40.2" r="0.7" fill="#C9A84C"/><circle cx="88.0" cy="50.0" r="1.4" fill="#C9A84C"/><circle cx="86.7" cy="59.8" r="0.7" fill="#C9A84C"/><circle cx="82.9" cy="69.0" r="1.4" fill="#C9A84C"/><circle cx="76.9" cy="76.9" r="0.7" fill="#C9A84C"/><circle cx="69.0" cy="82.9" r="1.4" fill="#C9A84C"/><circle cx="59.8" cy="86.7" r="0.7" fill="#C9A84C"/><circle cx="50.0" cy="88.0" r="1.4" fill="#C9A84C"/><circle cx="40.2" cy="86.7" r="0.7" fill="#C9A84C"/><circle cx="31.0" cy="82.9" r="1.4" fill="#C9A84C"/><circle cx="23.1" cy="76.9" r="0.7" fill="#C9A84C"/><circle cx="17.1" cy="69.0" r="1.4" fill="#C9A84C"/><circle cx="13.3" cy="59.8" r="0.7" fill="#C9A84C"/><circle cx="12.0" cy="50.0" r="1.4" fill="#C9A84C"/><circle cx="13.3" cy="40.2" r="0.7" fill="#C9A84C"/><circle cx="17.1" cy="31.0" r="1.4" fill="#C9A84C"/><circle cx="23.1" cy="23.1" r="0.7" fill="#C9A84C"/><circle cx="31.0" cy="17.1" r="1.4" fill="#C9A84C"/><circle cx="40.2" cy="13.3" r="0.7" fill="#C9A84C"/><circle cx="50" cy="50" r="35" fill="none" stroke="#b8860b" stroke-width="0.5"/><circle cx="50" cy="50" r="31" fill="#0D1B3E" stroke="#C9A84C" stroke-width="0.8"/><text font-size="5" font-weight="800" fill="#C9A84C" letter-spacing="0.8" font-family="Arial,sans-serif"><textPath href="#atDS" startOffset="10%">ALSHUMOOKH BANKING</textPath></text><text font-size="4.5" font-weight="700" fill="#C9A84C" letter-spacing="0.6" font-family="Arial,sans-serif"><textPath href="#abDS" startOffset="12%">UAE &#8226; OFFICIAL &#8226; EST.2020</textPath></text><text x="50" y="46" text-anchor="middle" font-size="4.5" font-weight="800" fill="#e2c97e" letter-spacing="1" font-family="Arial,sans-serif">ALSHUMOOKH</text><line x1="34" y1="49" x2="66" y2="49" stroke="#C9A84C" stroke-width="0.5"/><text x="50" y="57" text-anchor="middle" font-size="16" font-weight="900" fill="#e2c97e" font-family="Georgia,serif">AG</text><line x1="34" y1="60" x2="66" y2="60" stroke="#C9A84C" stroke-width="0.5"/><text x="50" y="67" text-anchor="middle" font-size="4.5" font-weight="700" fill="#C9A84C" letter-spacing="1.5" font-family="Arial,sans-serif">SEAL</text></svg>
      </div>

      <div class="footer">
        <p>{escape(note)}</p>
        <p class="disclaimer">
          This document is an official record issued by ALSHUMOOKH GLOBAL BANKING FINANCE &amp; CREDIT.
          It does not expose API keys, private keys, database credentials, or webhook secrets.
          For queries contact: compliance@alshumookh-pay.com | All rights reserved © ALSHUMOOKH GROUP 2026.
          Document is digitally traceable via the transaction ID above.
        </p>
      </div>
    </div>
  </section>

  <div class="actions">
    <button class="secondary" onclick="window.close()">Close</button>
    <button onclick="window.print()">&#128424; Print / Save PDF</button>
  </div>
</body>
</html>"""
