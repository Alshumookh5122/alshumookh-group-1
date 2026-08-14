"""
ALSHUMOOKH AI Bot Service
=========================
Claude-powered assistant that can execute any admin action in the dashboard.

Architecture:
  - Tool registry: maps capability names → async functions that call internal admin APIs
  - Dynamic: adding new admin routes → just register new tools
  - File extraction: PDF/DOCX/JSON/CSV content fed as bot context
  - Execution modes: MANUAL (confirm first) | AUTO (execute directly)
"""
from __future__ import annotations

import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Anthropic client (lazy init – only fails at runtime if key missing)
# ─────────────────────────────────────────────────────────────────────────────

def _anthropic_client():
    try:
        import anthropic  # noqa: PLC0415
        from app.config import settings  # noqa: PLC0415
        key = settings.anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        if not key:
            raise ValueError("ANTHROPIC_API_KEY not set in environment or .env")
        return anthropic.AsyncAnthropic(api_key=key)
    except ImportError:
        raise RuntimeError("anthropic package not installed. Run: pip install anthropic")


# ─────────────────────────────────────────────────────────────────────────────
# Internal HTTP helper — calls our own admin API
# ─────────────────────────────────────────────────────────────────────────────

async def _admin(method: str, path: str, body: dict | None = None, params: dict | None = None) -> dict:
    """Call an internal admin endpoint using the admin API key."""
    from app.config import settings  # noqa: PLC0415
    base = f"http://127.0.0.1:{settings.app_port}"
    headers = {"X-Admin-API-Key": settings.admin_api_key, "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=30) as client:
        url = f"{base}{settings.api_prefix}{path}"
        resp = await getattr(client, method.lower())(url, headers=headers, json=body, params=params)
        try:
            return resp.json()
        except Exception:
            return {"status": resp.status_code, "text": resp.text[:500]}


# ─────────────────────────────────────────────────────────────────────────────
# TOOL REGISTRY — one entry per capability
# Format: { "name": str, "description": str, "input_schema": dict, "fn": async callable }
# ─────────────────────────────────────────────────────────────────────────────

TOOLS: list[dict] = []


def register_tool(name: str, description: str, schema: dict):
    """Decorator to register a function as a bot tool."""
    def decorator(fn):
        TOOLS.append({"name": name, "description": description, "input_schema": schema, "fn": fn})
        return fn
    return decorator


# ══════════════════════════════════════════════════════════════════════════════
# 1. SYSTEM STATUS
# ══════════════════════════════════════════════════════════════════════════════

@register_tool("get_system_summary", "Get overall system summary: orders, payloads, transfers, M1 jobs, revenue stats", {
    "type": "object", "properties": {}, "required": []
})
async def get_system_summary(**_):
    return await _admin("GET", "/admin/summary")


@register_tool("get_system_readiness", "Check system readiness and configuration warnings", {
    "type": "object", "properties": {}, "required": []
})
async def get_system_readiness(**_):
    return await _admin("GET", "/admin/system/readiness")


@register_tool("get_live_monitoring", "Get live monitoring data: active transfers, pending payloads, recent events", {
    "type": "object", "properties": {}, "required": []
})
async def get_live_monitoring(**_):
    return await _admin("GET", "/admin/monitoring/live")


# ══════════════════════════════════════════════════════════════════════════════
# 2. ORDERS
# ══════════════════════════════════════════════════════════════════════════════

@register_tool("list_orders", "List payment orders with optional status filter", {
    "type": "object",
    "properties": {
        "status": {"type": "string", "description": "Filter by status: PENDING, COMPLETED, FAILED, CANCELLED. Leave empty for all."},
        "limit": {"type": "integer", "description": "Max number of orders to return", "default": 50}
    },
    "required": []
})
async def list_orders(status: str | None = None, limit: int = 50, **_):
    params = {"limit": limit}
    if status:
        params["status"] = status.upper()
    return await _admin("GET", "/admin/orders", params=params)


@register_tool("get_order_details", "Get full details of a specific payment order by ID", {
    "type": "object",
    "properties": {"order_id": {"type": "string", "description": "The order UUID"}},
    "required": ["order_id"]
})
async def get_order_details(order_id: str, **_):
    return await _admin("GET", f"/admin/orders/{order_id}/details")


@register_tool("update_order_status", "Change the status of a payment order", {
    "type": "object",
    "properties": {
        "order_id": {"type": "string"},
        "status": {"type": "string", "description": "New status: PENDING, PROCESSING, COMPLETED, FAILED, CANCELLED"},
        "notes": {"type": "string", "description": "Optional reason for status change"}
    },
    "required": ["order_id", "status"]
})
async def update_order_status(order_id: str, status: str, notes: str = "", **_):
    return await _admin("POST", f"/admin/orders/{order_id}/status", {"status": status.upper(), "notes": notes})


@register_tool("delete_order", "Delete a payment order permanently", {
    "type": "object",
    "properties": {"order_id": {"type": "string"}},
    "required": ["order_id"]
})
async def delete_order(order_id: str, **_):
    return await _admin("DELETE", f"/admin/orders/{order_id}")


@register_tool("tokenize_order", "Start M1 tokenization for an order (EUR→SIG)", {
    "type": "object",
    "properties": {
        "order_id": {"type": "string"},
        "asset": {"type": "string", "description": "Target asset: SIG or USDT", "default": "SIG"},
        "network": {"type": "string", "description": "Network: ethereum, tron, base", "default": "ethereum"}
    },
    "required": ["order_id"]
})
async def tokenize_order(order_id: str, asset: str = "SIG", network: str = "ethereum", **_):
    return await _admin("POST", f"/admin/orders/{order_id}/tokenize", {"asset": asset, "network": network})


# ══════════════════════════════════════════════════════════════════════════════
# 3. SETTLEMENT PAYLOADS
# ══════════════════════════════════════════════════════════════════════════════

@register_tool("list_payloads", "List settlement payloads with optional status filter", {
    "type": "object",
    "properties": {
        "status": {"type": "string", "description": "RECEIVED, PARSED, ALCHEMY_VERIFIED, RECONCILED, FAILED, MANUAL_REVIEW"},
        "limit": {"type": "integer", "default": 50}
    },
    "required": []
})
async def list_payloads(status: str | None = None, limit: int = 50, **_):
    params = {"limit": limit}
    if status:
        params["status"] = status.upper()
    return await _admin("GET", "/admin/payloads", params=params)


@register_tool("verify_payload_onchain", "Verify a settlement payload on the blockchain via Alchemy", {
    "type": "object",
    "properties": {"payload_id": {"type": "string"}},
    "required": ["payload_id"]
})
async def verify_payload_onchain(payload_id: str, **_):
    return await _admin("POST", f"/admin/payloads/{payload_id}/verify")


@register_tool("review_payload", "Approve or reject a settlement payload", {
    "type": "object",
    "properties": {
        "payload_id": {"type": "string"},
        "action": {"type": "string", "description": "approve or reject"},
        "note": {"type": "string", "description": "Operational note or rejection reason"}
    },
    "required": ["payload_id", "action"]
})
async def review_payload(payload_id: str, action: str, note: str = "", **_):
    return await _admin("POST", f"/admin/payloads/{payload_id}/review", {"action": action.lower(), "note": note})


@register_tool("mark_payload_manual_review", "Flag a payload for manual review with a reason", {
    "type": "object",
    "properties": {
        "payload_id": {"type": "string"},
        "reason": {"type": "string"}
    },
    "required": ["payload_id"]
})
async def mark_payload_manual_review(payload_id: str, reason: str = "", **_):
    return await _admin("POST", f"/admin/payloads/{payload_id}/manual-review", {"reason": reason})


@register_tool("send_response_to_sender", "Send a JSON response back to the sender's endpoint", {
    "type": "object",
    "properties": {
        "payload_id": {"type": "string"},
        "response_body": {"type": "object", "description": "JSON body to send"},
        "target_url": {"type": "string", "description": "Sender endpoint URL (optional if pre-configured)"}
    },
    "required": ["payload_id", "response_body"]
})
async def send_response_to_sender(payload_id: str, response_body: dict, target_url: str = "", **_):
    body: dict = {"response_body": response_body}
    if target_url:
        body["target_url"] = target_url
    return await _admin("POST", f"/admin/payloads/{payload_id}/push-response", body)


# ══════════════════════════════════════════════════════════════════════════════
# 4. OUTBOUND TRANSFERS
# ══════════════════════════════════════════════════════════════════════════════

@register_tool("list_transfers", "List outbound crypto transfers", {
    "type": "object",
    "properties": {
        "status": {"type": "string", "description": "PENDING, APPROVED, BROADCASTING, CONFIRMED, COMPLETED, FAILED"},
        "network": {"type": "string", "description": "ethereum, tron, base"},
        "limit": {"type": "integer", "default": 50}
    },
    "required": []
})
async def list_transfers(status: str | None = None, network: str | None = None, limit: int = 50, **_):
    params: dict = {"limit": limit}
    if status:
        params["status"] = status.upper()
    if network:
        params["network"] = network.lower()
    return await _admin("GET", "/admin/outbound-transfers", params=params)


@register_tool("create_transfer", "Create a new outbound crypto transfer", {
    "type": "object",
    "properties": {
        "to_address": {"type": "string", "description": "Recipient blockchain address"},
        "amount": {"type": "number", "description": "Amount to send"},
        "asset": {"type": "string", "description": "SIG or USDT", "default": "SIG"},
        "network": {"type": "string", "description": "ethereum, tron, base", "default": "ethereum"},
        "notes": {"type": "string"}
    },
    "required": ["to_address", "amount"]
})
async def create_transfer(to_address: str, amount: float, asset: str = "SIG", network: str = "ethereum", notes: str = "", **_):
    return await _admin("POST", "/admin/outbound-transfers", {
        "to_address": to_address, "amount": str(amount),
        "asset": asset.upper(), "network": network.lower(), "notes": notes
    })


@register_tool("approve_transfer", "Approve a pending outbound transfer", {
    "type": "object",
    "properties": {"transfer_id": {"type": "string"}},
    "required": ["transfer_id"]
})
async def approve_transfer(transfer_id: str, **_):
    return await _admin("POST", f"/admin/outbound-transfers/{transfer_id}/approve")


@register_tool("broadcast_transfer", "Broadcast an approved transfer to the blockchain", {
    "type": "object",
    "properties": {"transfer_id": {"type": "string"}},
    "required": ["transfer_id"]
})
async def broadcast_transfer(transfer_id: str, **_):
    return await _admin("POST", f"/admin/outbound-transfers/{transfer_id}/broadcast")


@register_tool("cancel_transfer", "Cancel a pending transfer before broadcast", {
    "type": "object",
    "properties": {
        "transfer_id": {"type": "string"},
        "reason": {"type": "string"}
    },
    "required": ["transfer_id"]
})
async def cancel_transfer(transfer_id: str, reason: str = "", **_):
    return await _admin("POST", f"/admin/outbound-transfers/{transfer_id}/cancel", {"reason": reason})


# ══════════════════════════════════════════════════════════════════════════════
# 5. M1 TOKENIZATION
# ══════════════════════════════════════════════════════════════════════════════

@register_tool("list_tokenization_jobs", "List M1 tokenization jobs", {
    "type": "object",
    "properties": {
        "status": {"type": "string", "description": "QUEUED, FX_FETCHED, CONVERTING, SENDING, COMPLETED, FAILED"},
        "limit": {"type": "integer", "default": 50}
    },
    "required": []
})
async def list_tokenization_jobs(status: str | None = None, limit: int = 50, **_):
    params: dict = {"limit": limit}
    if status:
        params["status"] = status.upper()
    return await _admin("GET", "/admin/tokenization-jobs", params=params)


@register_tool("create_tokenization_job", "Create a new EUR→SIG tokenization job", {
    "type": "object",
    "properties": {
        "eur_amount": {"type": "number", "description": "Amount in EUR"},
        "reference": {"type": "string", "description": "Optional reference"},
        "sender_name": {"type": "string"},
        "iban": {"type": "string"},
        "network": {"type": "string", "default": "ethereum"},
        "asset": {"type": "string", "default": "SIG"}
    },
    "required": ["eur_amount"]
})
async def create_tokenization_job(eur_amount: float, reference: str = "", sender_name: str = "", iban: str = "", network: str = "ethereum", asset: str = "SIG", **_):
    return await _admin("POST", "/admin/tokenization-jobs", {
        "eur_amount": str(eur_amount), "reference": reference,
        "sender_name": sender_name, "iban": iban,
        "network": network, "asset": asset.upper()
    })


@register_tool("process_tokenization_job", "Execute/process a tokenization job", {
    "type": "object",
    "properties": {"job_id": {"type": "string"}},
    "required": ["job_id"]
})
async def process_tokenization_job(job_id: str, **_):
    return await _admin("POST", f"/admin/tokenization-jobs/{job_id}/process")


@register_tool("get_live_fx_rate", "Get the live EUR/USD exchange rate", {
    "type": "object", "properties": {}, "required": []
})
async def get_live_fx_rate(**_):
    return await _admin("GET", "/admin/tokenization-jobs/fx-rate/live")


# ══════════════════════════════════════════════════════════════════════════════
# 6. CLIENTS / COUNTERPARTIES
# ══════════════════════════════════════════════════════════════════════════════

@register_tool("list_clients", "List all API clients / counterparties", {
    "type": "object", "properties": {}, "required": []
})
async def list_clients(**_):
    return await _admin("GET", "/admin/clients")


@register_tool("create_client", "Create a new API client / counterparty", {
    "type": "object",
    "properties": {
        "name": {"type": "string", "description": "Client display name"},
        "allowed_ips": {"type": "string", "description": "Comma-separated IPs (optional)"},
        "require_hmac": {"type": "boolean", "default": False}
    },
    "required": ["name"]
})
async def create_client(name: str, allowed_ips: str = "", require_hmac: bool = False, **_):
    ips = [ip.strip() for ip in allowed_ips.split(",") if ip.strip()] if allowed_ips else []
    return await _admin("POST", "/admin/clients", {"name": name, "allowed_ips": ips, "require_hmac_signature": require_hmac})


@register_tool("toggle_client", "Enable or disable a client account", {
    "type": "object",
    "properties": {
        "client_id": {"type": "string"},
        "is_active": {"type": "boolean", "description": "true to enable, false to disable"}
    },
    "required": ["client_id", "is_active"]
})
async def toggle_client(client_id: str, is_active: bool, **_):
    return await _admin("PATCH", f"/admin/clients/{client_id}", {"is_active": is_active})


@register_tool("whitelist_ip", "Add an IP address to a client's whitelist", {
    "type": "object",
    "properties": {
        "client_id": {"type": "string"},
        "ip_address": {"type": "string"}
    },
    "required": ["client_id", "ip_address"]
})
async def whitelist_ip(client_id: str, ip_address: str, **_):
    return await _admin("POST", f"/admin/clients/{client_id}/whitelist-ip", {"ip_address": ip_address})


@register_tool("rotate_client_secrets", "Rotate the API key and HMAC secret for a client", {
    "type": "object",
    "properties": {"client_id": {"type": "string"}},
    "required": ["client_id"]
})
async def rotate_client_secrets(client_id: str, **_):
    return await _admin("POST", f"/admin/clients/{client_id}/rotate-secrets")


# ══════════════════════════════════════════════════════════════════════════════
# 7. CIRCLE WIRE
# ══════════════════════════════════════════════════════════════════════════════

@register_tool("get_circle_balance", "Get current Circle USDC wallet balance", {
    "type": "object", "properties": {}, "required": []
})
async def get_circle_balance(**_):
    return await _admin("GET", "/admin/circle/balance")


@register_tool("get_circle_wire_instructions", "Get Circle wire transfer instructions for sending funds", {
    "type": "object", "properties": {}, "required": []
})
async def get_circle_wire_instructions(**_):
    return await _admin("GET", "/admin/circle/wire-instructions")


@register_tool("list_circle_wire_deposits", "List Circle wire deposits", {
    "type": "object",
    "properties": {
        "status": {"type": "string", "description": "PENDING, RECEIVED, SETTLED, CANCELLED"},
        "limit": {"type": "integer", "default": 50}
    },
    "required": []
})
async def list_circle_wire_deposits(status: str | None = None, limit: int = 50, **_):
    params: dict = {"limit": limit}
    if status:
        params["status"] = status.upper()
    return await _admin("GET", "/admin/circle/wire-deposits", params=params)


@register_tool("create_circle_wire_deposit", "Register a new expected Circle wire deposit and generate SWIFT reference", {
    "type": "object",
    "properties": {
        "amount_eur": {"type": "number"},
        "sender_name": {"type": "string"},
        "sender_bank": {"type": "string"},
        "sender_iban": {"type": "string"},
        "sender_bic": {"type": "string"},
        "settlement_network": {"type": "string", "default": "ethereum"},
        "notes": {"type": "string"}
    },
    "required": ["amount_eur", "sender_name"]
})
async def create_circle_wire_deposit(amount_eur: float, sender_name: str, sender_bank: str = "", sender_iban: str = "", sender_bic: str = "", settlement_network: str = "ethereum", notes: str = "", **_):
    return await _admin("POST", "/admin/circle/wire-deposits", {
        "amount_eur": str(amount_eur), "sender_name": sender_name,
        "sender_bank": sender_bank, "sender_iban": sender_iban,
        "sender_bic": sender_bic, "settlement_network": settlement_network, "notes": notes
    })


@register_tool("settle_circle_deposit", "Settle a received Circle wire deposit", {
    "type": "object",
    "properties": {"deposit_id": {"type": "string"}},
    "required": ["deposit_id"]
})
async def settle_circle_deposit(deposit_id: str, **_):
    return await _admin("POST", f"/admin/circle/wire-deposits/{deposit_id}/settle")


@register_tool("bulk_settle_circle_deposits", "Bulk settle multiple Circle wire deposits at once", {
    "type": "object",
    "properties": {
        "deposit_ids": {"type": "array", "items": {"type": "string"}, "description": "List of deposit IDs to settle"}
    },
    "required": ["deposit_ids"]
})
async def bulk_settle_circle_deposits(deposit_ids: list[str], **_):
    return await _admin("POST", "/admin/circle/wire-deposits/bulk-settle", {"deposit_ids": deposit_ids})


@register_tool("get_circle_fx_rate", "Get current EUR/USDC exchange rate from Circle", {
    "type": "object", "properties": {}, "required": []
})
async def get_circle_fx_rate(**_):
    return await _admin("GET", "/admin/circle/fx-rate")


# ══════════════════════════════════════════════════════════════════════════════
# 8. OTC QUOTES
# ══════════════════════════════════════════════════════════════════════════════

@register_tool("get_live_otc_rate", "Get the current live OTC EUR/USDT rate from Binance/CoinGecko", {
    "type": "object", "properties": {}, "required": []
})
async def get_live_otc_rate(**_):
    return await _admin("GET", "/admin/otc/rate")


@register_tool("create_otc_quote", "Create an OTC quote for EUR→USDT conversion", {
    "type": "object",
    "properties": {
        "eur_amount": {"type": "number"},
        "client_id": {"type": "string", "description": "Optional client ID"}
    },
    "required": ["eur_amount"]
})
async def create_otc_quote(eur_amount: float, client_id: str = "", **_):
    body: dict = {"eur_amount": str(eur_amount)}
    if client_id:
        body["client_id"] = client_id
    return await _admin("POST", "/admin/otc/quotes", body)


@register_tool("list_otc_quotes", "List OTC quotes", {
    "type": "object",
    "properties": {
        "status": {"type": "string", "description": "PENDING, LOCKED, EXECUTED, CANCELLED"}
    },
    "required": []
})
async def list_otc_quotes(status: str | None = None, **_):
    params = {}
    if status:
        params["status"] = status.upper()
    return await _admin("GET", "/admin/otc/quotes", params=params)


@register_tool("execute_otc_quote", "Execute (finalize) an OTC quote", {
    "type": "object",
    "properties": {"quote_id": {"type": "string"}},
    "required": ["quote_id"]
})
async def execute_otc_quote(quote_id: str, **_):
    return await _admin("POST", f"/admin/otc/quotes/{quote_id}/execute")


# ══════════════════════════════════════════════════════════════════════════════
# 9. FIAT DEPOSITS
# ══════════════════════════════════════════════════════════════════════════════

@register_tool("register_fiat_deposit", "Register a new fiat (SWIFT/SEPA) deposit", {
    "type": "object",
    "properties": {
        "amount_eur": {"type": "number"},
        "sender_name": {"type": "string"},
        "sender_bank": {"type": "string"},
        "iban": {"type": "string"},
        "payment_method": {"type": "string", "description": "SWIFT, SEPA, LOCAL, PSP", "default": "SWIFT"},
        "bank_reference": {"type": "string"}
    },
    "required": ["amount_eur", "sender_name"]
})
async def register_fiat_deposit(amount_eur: float, sender_name: str, sender_bank: str = "", iban: str = "", payment_method: str = "SWIFT", bank_reference: str = "", **_):
    return await _admin("POST", "/admin/fiat/deposits", {
        "amount_eur": str(amount_eur), "sender_name": sender_name,
        "sender_bank": sender_bank, "iban": iban,
        "payment_method": payment_method.upper(), "bank_reference": bank_reference
    })


@register_tool("confirm_fiat_deposit", "Confirm that a fiat deposit has been received", {
    "type": "object",
    "properties": {"deposit_id": {"type": "string"}},
    "required": ["deposit_id"]
})
async def confirm_fiat_deposit(deposit_id: str, **_):
    return await _admin("POST", f"/admin/fiat/deposits/{deposit_id}/confirm")


@register_tool("list_fiat_deposits", "List all fiat deposits", {
    "type": "object",
    "properties": {
        "status": {"type": "string", "description": "PENDING, RECEIVED, MATCHED, FAILED, REFUNDED"}
    },
    "required": []
})
async def list_fiat_deposits(status: str | None = None, **_):
    params = {}
    if status:
        params["status"] = status.upper()
    return await _admin("GET", "/admin/fiat/deposits", params=params)


# ══════════════════════════════════════════════════════════════════════════════
# 10. TRANSFER REQUESTS
# ══════════════════════════════════════════════════════════════════════════════

@register_tool("create_transfer_request", "Create a full transfer request (EUR→crypto workflow)", {
    "type": "object",
    "properties": {
        "eur_amount": {"type": "number"},
        "recipient_wallet": {"type": "string"},
        "network": {"type": "string", "description": "TRC20 or ERC20", "default": "TRC20"},
        "sender_name": {"type": "string"},
        "notes": {"type": "string"}
    },
    "required": ["eur_amount", "recipient_wallet"]
})
async def create_transfer_request(eur_amount: float, recipient_wallet: str, network: str = "TRC20", sender_name: str = "", notes: str = "", **_):
    return await _admin("POST", "/admin/transfer-requests", {
        "eur_amount": str(eur_amount), "recipient_wallet": recipient_wallet,
        "network": network.upper(), "sender_name": sender_name, "notes": notes
    })


@register_tool("list_transfer_requests", "List all transfer requests", {
    "type": "object",
    "properties": {
        "status": {"type": "string", "description": "PENDING, QUOTE_ATTACHED, EXECUTING, COMPLETED, FAILED"}
    },
    "required": []
})
async def list_transfer_requests(status: str | None = None, **_):
    params = {}
    if status:
        params["status"] = status.upper()
    return await _admin("GET", "/admin/transfer-requests", params=params)


# ══════════════════════════════════════════════════════════════════════════════
# 11. SECURITY
# ══════════════════════════════════════════════════════════════════════════════

@register_tool("list_security_events", "List recent security events and alerts", {
    "type": "object",
    "properties": {"limit": {"type": "integer", "default": 50}},
    "required": []
})
async def list_security_events(limit: int = 50, **_):
    return await _admin("GET", "/admin/security-events", params={"limit": limit})


@register_tool("investigate_ip", "Investigate an IP address: history, country, risk score", {
    "type": "object",
    "properties": {"ip_address": {"type": "string"}},
    "required": ["ip_address"]
})
async def investigate_ip(ip_address: str, **_):
    return await _admin("GET", f"/admin/ip-investigation/{ip_address}")


@register_tool("unlock_ip", "Remove a ban / unlock an IP address", {
    "type": "object",
    "properties": {"ip_address": {"type": "string"}},
    "required": ["ip_address"]
})
async def unlock_ip(ip_address: str, **_):
    return await _admin("POST", f"/admin/ip-unlock/{ip_address}")


# ══════════════════════════════════════════════════════════════════════════════
# 12. WALLET OTP
# ══════════════════════════════════════════════════════════════════════════════

@register_tool("request_wallet_otp", "Generate an OTP for wallet address verification", {
    "type": "object",
    "properties": {
        "wallet_address": {"type": "string"},
        "client_id": {"type": "string", "description": "Optional client ID"}
    },
    "required": ["wallet_address"]
})
async def request_wallet_otp(wallet_address: str, client_id: str = "", **_):
    body: dict = {"wallet_address": wallet_address}
    if client_id:
        body["client_id"] = client_id
    return await _admin("POST", "/admin/wallet-otp/request", body)


@register_tool("verify_wallet_otp", "Verify an OTP against a wallet address", {
    "type": "object",
    "properties": {
        "wallet_address": {"type": "string"},
        "otp_code": {"type": "string"}
    },
    "required": ["wallet_address", "otp_code"]
})
async def verify_wallet_otp(wallet_address: str, otp_code: str, **_):
    return await _admin("POST", "/admin/wallet-otp/verify", {"wallet_address": wallet_address, "otp_code": otp_code})


@register_tool("list_wallet_otps", "List all pending wallet OTP verifications", {
    "type": "object", "properties": {}, "required": []
})
async def list_wallet_otps(**_):
    return await _admin("GET", "/admin/wallet-otp")


# ══════════════════════════════════════════════════════════════════════════════
# 13. NOWPAYMENTS
# ══════════════════════════════════════════════════════════════════════════════

@register_tool("nowpayments_create_payment", "Create a NOWPayments crypto payment invoice", {
    "type": "object",
    "properties": {
        "amount": {"type": "number"},
        "price_currency": {"type": "string", "default": "usd"},
        "pay_currency": {"type": "string", "default": "usdttrc20"},
        "order_id": {"type": "string"},
        "description": {"type": "string"}
    },
    "required": ["amount"]
})
async def nowpayments_create_payment(amount: float, price_currency: str = "usd", pay_currency: str = "usdttrc20", order_id: str = "", description: str = "", **_):
    return await _admin("POST", "/admin/nowpayments/create-payment", {
        "amount": amount, "price_currency": price_currency,
        "pay_currency": pay_currency, "order_id": order_id, "description": description
    })


@register_tool("nowpayments_list_payments", "List all NOWPayments payment history", {
    "type": "object",
    "properties": {"limit": {"type": "integer", "default": 20}},
    "required": []
})
async def nowpayments_list_payments(limit: int = 20, **_):
    return await _admin("GET", "/admin/nowpayments/payments", params={"limit": limit})


# ══════════════════════════════════════════════════════════════════════════════
# 14. AUDIT LOGS
# ══════════════════════════════════════════════════════════════════════════════

@register_tool("get_audit_logs", "Retrieve system audit logs", {
    "type": "object",
    "properties": {
        "limit": {"type": "integer", "default": 50},
        "event_type": {"type": "string", "description": "Filter by event type (optional)"}
    },
    "required": []
})
async def get_audit_logs(limit: int = 50, event_type: str | None = None, **_):
    params: dict = {"limit": limit}
    if event_type:
        params["event_type"] = event_type
    return await _admin("GET", "/admin/audit-logs", params=params)


# ══════════════════════════════════════════════════════════════════════════════
# TOP-UP ENGINE
# ══════════════════════════════════════════════════════════════════════════════

@register_tool("list_topup_wallets", "List all top-up wallets", {
    "type": "object", "properties": {}, "required": []
})
async def list_topup_wallets(**_):
    return await _admin("GET", "/admin/topup/wallets")


@register_tool("create_topup_wallet", "Create a new top-up wallet", {
    "type": "object",
    "properties": {
        "wallet_name": {"type": "string"},
        "currency": {"type": "string", "default": "USDT"},
        "network": {"type": "string", "default": "ethereum"},
        "blockchain_address": {"type": "string"}
    },
    "required": ["wallet_name"]
})
async def create_topup_wallet(wallet_name: str, currency: str = "USDT", network: str = "ethereum", blockchain_address: str = "", **_):
    return await _admin("POST", "/admin/topup/wallets", {
        "wallet_name": wallet_name, "currency": currency,
        "network": network, "blockchain_address": blockchain_address
    })


# ══════════════════════════════════════════════════════════════════════════════
# FILE EXTRACTION HELPER
# ══════════════════════════════════════════════════════════════════════════════

async def extract_file_content(filename: str, file_bytes: bytes) -> str:
    """Extract text content from uploaded files (PDF, JSON, CSV, DOCX, TXT)."""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    if ext == "json":
        try:
            data = json.loads(file_bytes.decode("utf-8", errors="replace"))
            return f"[JSON FILE: {filename}]\n{json.dumps(data, indent=2, ensure_ascii=False)[:4000]}"
        except Exception:
            return f"[JSON FILE — parse error]\n{file_bytes.decode('utf-8', errors='replace')[:2000]}"

    if ext == "csv":
        text = file_bytes.decode("utf-8", errors="replace")
        return f"[CSV FILE: {filename}]\n{text[:3000]}"

    if ext == "txt":
        return f"[TEXT FILE: {filename}]\n{file_bytes.decode('utf-8', errors='replace')[:3000]}"

    if ext == "pdf":
        try:
            import io  # noqa: PLC0415
            from pypdf import PdfReader  # noqa: PLC0415
            reader = PdfReader(io.BytesIO(file_bytes))
            pages_text = "\n".join(p.extract_text() or "" for p in reader.pages[:10])
            return f"[PDF FILE: {filename}]\n{pages_text[:4000]}"
        except Exception as exc:
            return f"[PDF FILE: {filename} — could not extract text: {exc}]"

    if ext in {"docx", "doc"}:
        try:
            import io  # noqa: PLC0415
            from docx import Document  # noqa: PLC0415
            doc = Document(io.BytesIO(file_bytes))
            text = "\n".join(p.text for p in doc.paragraphs)
            return f"[WORD FILE: {filename}]\n{text[:4000]}"
        except Exception as exc:
            return f"[WORD FILE: {filename} — could not extract text: {exc}]"

    # Fallback: try raw UTF-8
    return f"[FILE: {filename}]\n{file_bytes.decode('utf-8', errors='replace')[:2000]}"


# ══════════════════════════════════════════════════════════════════════════════
# TOOLS SCHEMA for Claude API
# ══════════════════════════════════════════════════════════════════════════════

def get_claude_tools() -> list[dict]:
    return [
        {"name": t["name"], "description": t["description"], "input_schema": t["input_schema"]}
        for t in TOOLS
    ]


def _tool_fn(name: str):
    for t in TOOLS:
        if t["name"] == name:
            return t["fn"]
    return None


# ══════════════════════════════════════════════════════════════════════════════
# MAIN CHAT FUNCTION
# ══════════════════════════════════════════════════════════════════════════════

SYSTEM_PROMPT = """You are ASIG-BOT, the intelligent operations assistant for ALSHUMOOKH GLOBAL BANKING FINANCE & CREDIT.

You have direct access to the entire admin dashboard API through tools. You can:
- Execute any admin operation (create, update, approve, reject, settle, broadcast, etc.)
- Query live data (balances, orders, payloads, transfers, monitoring)
- Run automated workflows (multi-step sequences)
- Extract and act on data from uploaded files

IMPORTANT RULES:
1. Always be precise and professional
2. For DESTRUCTIVE operations (delete, cancel, broadcast), briefly state what you are about to do before calling the tool
3. When you call a tool, present the result clearly and concisely
4. If a user's message is in Arabic, respond in Arabic; if English, respond in English
5. You can chain multiple tool calls to complete complex workflows
6. When you get data back, summarize it intelligently — don't just dump raw JSON
7. If file content is provided in the conversation, use that data to pre-fill tool parameters

You are connected to a live production system. Act with precision."""


async def chat(
    messages: list[dict],
    mode: str = "manual",
    file_context: str | None = None,
) -> dict:
    """
    Send messages to Claude and execute tool calls.
    Returns: { "reply": str, "tool_calls": list[dict], "mode": str }
    """
    client = _anthropic_client()
    claude_tools = get_claude_tools()

    # Inject file context as system addendum
    system = SYSTEM_PROMPT
    if file_context:
        system += f"\n\nUPLOADED FILE CONTEXT (use this data when executing commands):\n{file_context}"

    all_tool_calls: list[dict] = []
    final_text = ""

    # Agentic loop: Claude can call multiple tools in sequence
    working_messages = list(messages)
    max_iterations = 10

    from app.config import settings as _s  # noqa: PLC0415
    _model = _s.bot_model
    _max_tokens = _s.bot_max_tokens

    for _ in range(max_iterations):
        response = await client.messages.create(
            model=_model,
            max_tokens=_max_tokens,
            system=system,
            tools=claude_tools,
            messages=working_messages,
        )

        # Collect text
        text_parts = [b.text for b in response.content if hasattr(b, "text")]
        if text_parts:
            final_text = "\n".join(text_parts)

        # If no tool use → done
        if response.stop_reason != "tool_use":
            break

        # Execute tool calls
        tool_use_blocks = [b for b in response.content if b.type == "tool_use"]
        tool_results = []

        for block in tool_use_blocks:
            fn = _tool_fn(block.name)
            if fn is None:
                result = {"error": f"Unknown tool: {block.name}"}
            else:
                try:
                    result = await fn(**(block.input or {}))
                except Exception as exc:
                    result = {"error": str(exc)}

            all_tool_calls.append({"tool": block.name, "input": block.input, "result": result})
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": json.dumps(result, default=str)[:8000],
            })

        # Continue loop with tool results
        working_messages = working_messages + [
            {"role": "assistant", "content": response.content},
            {"role": "user", "content": tool_results},
        ]

    return {"reply": final_text, "tool_calls": all_tool_calls, "mode": mode}
