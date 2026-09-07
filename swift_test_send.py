#!/usr/bin/env python3
"""
ALSHUMOOKH — SWIFT Terminal Test Send
──────────────────────────────────────
Sends a test wire from the ALSHUMOOKH SWIFT terminal
to buronkz01 / Global Server Funds (GSFDUS33) via the partner-dispatch endpoint.

Usage:
    python3 swift_test_send.py --key 'YOUR_KEY'
    python3 swift_test_send.py --key 'YOUR_KEY' --amount 5000
    python3 swift_test_send.py --key 'YOUR_KEY' --live
"""
import argparse
import json
import os
import sys
import uuid
import gzip
import zlib
from datetime import datetime, timezone

try:
    import urllib.request
    import urllib.error
except ImportError:
    pass

# ══════════════════════════════════════════════════════════════════════════════
#  CONFIGURATION
# ══════════════════════════════════════════════════════════════════════════════

BASE_URL   = os.getenv("ALSHUMOOKH_API_URL",   "https://api.alshumookh-pay.com")
API_PREFIX = "/api/v1"

# ── Sender (Deutsche Bank) ───────────────────────────────────────────────────
SENDER_BANK    = "DEUTSCHE BANK AG"
SENDER_SWIFT   = "DEUTDEDB101"
SENDER_ACCOUNT = "DE1910070124000326B3500"
SENDER_NAME    = "ADASDA DEUTSCHLAND GMBH"

# ── Receiver (buronkz01 / Global Server Funds) ───────────────────────────────
RECEIVER_BANK    = "Global Server Funds"
RECEIVER_SWIFT   = "GSFDUS33"
RECEIVER_ACCOUNT = "GS22GSFD00003646229939"
RECEIVER_NAME    = "buronkz01"

# ══════════════════════════════════════════════════════════════════════════════

CYAN   = "\033[96m"
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
BOLD   = "\033[1m"
RESET  = "\033[0m"


def banner():
    print("""
%s%s╔══════════════════════════════════════════════════════════════╗
║        ALSHUMOOKH — SWIFT TERMINAL TEST SEND                 ║
║        Target : Global Server Funds / GSFDUS33               ║
╚══════════════════════════════════════════════════════════════╝%s
""" % (BOLD, CYAN, RESET))


def build_payload(amount, api_key):
    ref = "ALSH-TEST-%s-%s" % (
        datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S'),
        uuid.uuid4().hex[:6].upper()
    )
    return {
        "partner":            "goodwill",
        "api_key":            api_key,

        "sender_bank":        SENDER_BANK,
        "sender_swift":       SENDER_SWIFT,
        "sender_account":     SENDER_ACCOUNT,
        "sender_name":        SENDER_NAME,

        "receiver_bank":      RECEIVER_BANK,
        "receiver_swift":     RECEIVER_SWIFT,
        "receiver_account":   RECEIVER_ACCOUNT,
        "receiver_name":      RECEIVER_NAME,

        "amount":             amount,
        "currency":           "EUR",
        "purpose_code":       "INTC",
        "charge_bearer":      "SHA",
        "priority":           "NORMAL",
        "transfer_reference": ref,

        "extra_headers": {
            "X-SWIFT-MsgType":   "MT103",
            "X-SWIFT-Sender":    SENDER_SWIFT,
            "X-SWIFT-Receiver":  RECEIVER_SWIFT,
            "X-SWIFT-ValueDate": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "X-SWIFT-Currency":  "EUR",
            "X-SWIFT-Amount":    str(amount),
        },

        "note": "[TEST] EUR SWIFT terminal test — %s" % datetime.now(timezone.utc).isoformat(),
    }


def decode_response(raw_bytes, content_encoding=""):
    """Decompress and decode response bytes."""
    try:
        enc = (content_encoding or "").lower()
        if "gzip" in enc:
            raw_bytes = gzip.decompress(raw_bytes)
        elif "deflate" in enc:
            try:
                raw_bytes = zlib.decompress(raw_bytes)
            except Exception:
                raw_bytes = zlib.decompress(raw_bytes, -zlib.MAX_WBITS)
    except Exception:
        pass
    return raw_bytes.decode("utf-8", errors="replace")


def send_request(url, headers, payload):
    """Send POST request using urllib (no external dependencies)."""
    body = json.dumps(payload).encode("utf-8")
    req  = urllib.request.Request(url, data=body, method="POST")
    for k, v in headers.items():
        req.add_header(k, v)

    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            raw     = r.read()
            enc     = r.headers.get("Content-Encoding", "")
            text    = decode_response(raw, enc)
            return r.status, _parse_json(text)

    except urllib.error.HTTPError as e:
        raw  = e.read()
        enc  = e.headers.get("Content-Encoding", "")
        text = decode_response(raw, enc)
        return e.code, _parse_json(text)


def _parse_json(text):
    try:
        return json.loads(text)
    except Exception:
        return text


def print_result(status, body, payload):
    amount = payload["amount"]
    ref    = payload["transfer_reference"]

    print("%s%s%s" % (BOLD, "─" * 64, RESET))
    print("  Transfer Reference : %s%s%s" % (YELLOW, ref, RESET))
    print("  Amount             : %sEUR {:,.2f}%s".format(amount) % (BOLD, RESET))
    print("  Sender             : %s (%s)" % (SENDER_NAME, SENDER_SWIFT))
    print("  Receiver           : %s / %s (%s)" % (RECEIVER_NAME, RECEIVER_BANK, RECEIVER_SWIFT))
    print("  IBAN               : %s" % RECEIVER_ACCOUNT)
    print("  HTTP Status        : %s" % status)
    print("─" * 64)

    if isinstance(body, dict):
        delivery = body.get("delivery_status", "UNKNOWN")
        color    = GREEN if delivery in ("DELIVERED", "PENDING") else RED

        print("  Delivery Status    : %s%s%s%s" % (color, BOLD, delivery, RESET))

        if body.get("uetr"):
            print("  UETR               : %s" % body["uetr"])
        if body.get("trn"):
            print("  TRN                : %s" % body["trn"])
        if body.get("error"):
            print("  Error              : %s%s%s" % (RED, body["error"], RESET))
        if body.get("partner_response"):
            print("\n  Partner Response:")
            print(json.dumps(body["partner_response"], indent=4))
        elif body.get("partner_response_raw"):
            print("\n  Partner Response (raw):\n  %s" % body["partner_response_raw"])

        skip = {"partner_response", "partner_response_raw"}
        print("\n  Full Response:")
        print(json.dumps({k: v for k, v in body.items() if k not in skip}, indent=4))
    else:
        print("  Response: %s" % body)

    print("─" * 64 + "\n")


def main():
    parser = argparse.ArgumentParser(description="ALSHUMOOKH SWIFT Terminal Test")
    parser.add_argument("--amount", type=float, default=1000.0,
                        help="Amount in EUR (default: 1000)")
    parser.add_argument("--live",   action="store_true",
                        help="Use LIVE mode (default: SANDBOX)")
    parser.add_argument("--url",    default=BASE_URL,
                        help="API base URL override")
    parser.add_argument("--key",    default="SANDBOX",
                        help="Admin API key (wrap in single quotes if it has special chars)")
    args = parser.parse_args()

    banner()

    endpoint  = "%s%s/admin/partner-transfer" % (args.url.rstrip("/"), API_PREFIX)
    api_key   = "SANDBOX" if not args.live else args.key
    payload   = build_payload(args.amount, api_key)

    headers = {
        "Content-Type":    "application/json",
        "Accept":          "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate",
        "User-Agent":      (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/127.0.0.0 Safari/537.36"
        ),
        "Origin":          args.url.rstrip("/"),
        "Referer":         args.url.rstrip("/") + "/swift",
        "X-Admin-Api-Key": args.key,
        "X-Admin-Actor":   "swift-terminal-test",
        "Cache-Control":   "no-cache",
    }

    mode_label = "%sSANDBOX%s" % (YELLOW, RESET) if not args.live else "%sLIVE%s" % (RED, RESET)
    print("  Mode    : %s" % mode_label)
    print("  Endpoint: %s" % endpoint)
    print("  Key     : %s…%s" % (args.key[:4], args.key[-4:]) if len(args.key) > 8 else "  Key     : %s" % args.key)
    print("  Amount  : EUR {:,.2f}\n".format(args.amount))
    print("%sSending SWIFT test transfer...%s\n" % (CYAN, RESET))

    try:
        status, body = send_request(endpoint, headers, payload)
    except Exception as exc:
        print("%sConnection error: %s%s" % (RED, exc, RESET))
        sys.exit(1)

    print_result(status, body, payload)

    if isinstance(body, dict) and body.get("delivery_status") in ("DELIVERED", "PENDING"):
        sys.exit(0)
    elif status < 400:
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
