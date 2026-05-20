# ALSHUMOOKH API — v2 Settlement Upgrade

Institutional-style API-to-API settlement receiver built on top of the existing FastAPI system.  
Zero rebuild. Minimal cost. All open-source.

---

## What Was Added

| Area | Change |
|---|---|
| `POST /api/v1/payloads/ingest` | New external payload receiver endpoint |
| `GET /api/v1/admin/payloads` | Admin list of all received payloads |
| `GET /api/v1/admin/payloads/{id}` | Full payload detail |
| `POST /api/v1/admin/payloads/{id}/verify` | Trigger Alchemy on-chain verification |
| `POST /api/v1/admin/payloads/{id}/mark-manual-review` | Flag for manual review |
| `POST /api/v1/admin/payloads/{id}/review` | Apply operational review actions: approve, hold, reject, reconcile, note |
| `POST /api/v1/webhooks/alchemy` | Settlement Alchemy webhook (with signature verification) |
| `POST /api/v1/oauth/token` | OAuth2 Client Credentials token endpoint for counterparties |
| `GET /api/v1/payloads/schema` | Public technical payload schema for counterparties |
| `GET /receiver/docs` | Swagger-style technical API window similar to institutional receiver portals |
| `GET /receiver/openapi.json` | OpenAPI schema backing the receiver docs window |
| `GET /ready` | Lightweight readiness endpoint |
| `GET /api/v1/admin/system/readiness` | Internal enterprise readiness and operational evidence summary |
| `GET /api/v1/admin/clients/security-posture` | Security posture and hardening score for each counterparty |
| `PATCH /api/v1/admin/clients/{id}` | Update counterparty security requirements safely |
| `POST /api/v1/admin/clients/{id}/rotate-secrets` | Rotate API key, HMAC, and OAuth client secrets |
| `app/payload_service.py` | Field normalization engine + blockchain TX verifier |
| `app/payloads.py` | All payload routes |
| `app/models.py` | `ExternalPayload` table, `PayloadVerificationStatus` enum, `hmac_required` on `ApiClient` |
| `app/database.py` | Auto-migration for `external_payloads` table + `hmac_required` column |
| `app/config.py` | `MASTER_WALLET_*`, `ALCHEMY_ETHEREUM_RPC_URL` env vars |
| `app/webhooks.py` | Alchemy webhook now also matches `ExternalPayload` records |
| `app/main.py` | Security headers, trusted request IP handling, request tracing, audit middleware, restricted CORS |
| `app/static/dashboard.*` | Settlement Payloads table, detail modal, verify/review controls, readiness view, counterparty management |
| `Dockerfile` | Production-ready container |
| `.env.example` | Updated with all new variables |
| `ENTERPRISE_SETTLEMENT_API.md` | Formal counterparty-facing API procedure |

---

## New Environment Variables

Add these to your `.env` or Render/VPS environment:

```bash
# ── Alchemy RPC URLs (full URL preferred over API key alone) ──────────────
ALCHEMY_ETHEREUM_RPC_URL=https://eth-mainnet.g.alchemy.com/v2/YOUR_API_KEY
ALCHEMY_BASE_RPC_URL=https://base-mainnet.g.alchemy.com/v2/YOUR_API_KEY
ALCHEMY_WEBHOOK_SIGNING_KEY=your_alchemy_webhook_signing_key

# ── Master wallets — funds must arrive HERE to be verified ────────────────
MASTER_WALLET_ETHEREUM=0xYOUR_ETH_MASTER_WALLET
MASTER_WALLET_BASE=0xYOUR_BASE_MASTER_WALLET
MASTER_WALLET_TRON=TYOUR_TRON_MASTER_WALLET

# ── Enterprise settlement controls ───────────────────────────────────────
SETTLEMENT_OAUTH_ISSUER=alshumookh-settlement-api
SETTLEMENT_OAUTH_AUDIENCE=alshumookh-settlement
SETTLEMENT_OAUTH_TOKEN_TTL_SECONDS=900
SETTLEMENT_JWE_PRIVATE_KEY_PEM=
SETTLEMENT_JWE_PRIVATE_KEY_PASSPHRASE=
```

---

## Settlement Payload Status Flow

```
RECEIVED → PARSED → AWAITING_TX_HASH
                  ↘ ALCHEMY_PENDING → ALCHEMY_VERIFIED → ON_CHAIN_CONFIRMED → RECONCILED
                                    → FAILED
                                    → MANUAL_REVIEW
```

---

## Security Model

Every call to `POST /api/v1/payloads/ingest` requires either API key auth or OAuth2 bearer auth:

| Header | Required | Notes |
|---|---|---|
| `X-API-Key` | Required unless OAuth2 is used | Issued per counterparty client |
| `Authorization: Bearer ...` | Required if `oauth_required=true` | Token from `POST /api/v1/oauth/token` |
| `Idempotency-Key` | **YES** | UUID or unique string; duplicate keys return the original response |
| `X-Timestamp` | Recommended | Unix epoch (seconds). Rejected if >5 minutes old |
| `X-Signature` | Required if `hmac_required=true` | HMAC-SHA256 over timestamp + exact wire body |
| `X-JWS-Signature` | Required if `jws_required=true` | Detached JWS with `payload_hash=sha256(plaintext_body)` |
| `X-Client-Cert-Fingerprint` | Required if `mtls_required=true` | Forwarded by Cloudflare/Nginx/VPS after client certificate validation |

**HMAC Signature Format:**
```
base_string = timestamp + "." + raw_body_bytes
signature   = HMAC-SHA256(hmac_secret, base_string).hexdigest()
Header: X-Signature: sha256=<hex_digest>
```

If `hmac_required=false` for a client, requests are accepted with API key + Idempotency-Key only, and `security_level` is set to `api_key_only`.

OAuth2, JWS, JWE, and mTLS-ready controls are enabled per API client. Existing clients remain backward-compatible until those flags are turned on.

---

## Operational Governance Added

The platform now supports internal operational control over inbound settlement payloads:

- Review priorities: `LOW`, `NORMAL`, `HIGH`, `CRITICAL`
- Review decisions:
  - `APPROVED`
  - `ON_HOLD`
  - `REJECTED`
  - `RECONCILED`
  - `NOTED`
  - `MANUAL_REVIEW`
- Review metadata:
  - reviewer identity
  - review timestamp
  - review note
  - hold reason

Admin endpoint:

```bash
POST /api/v1/admin/payloads/{payload_id}/review
```

Example:

```json
{
  "action": "HOLD",
  "priority": "HIGH",
  "hold_reason": "Sender amount mismatch requires manual confirmation",
  "note": "Awaiting signed reconciliation note from counterparty"
}
```

This workflow lets the team operate the settlement queue in a more institutional way instead of relying only on raw verification status.

---

## Readiness / Operations Visibility

The admin dashboard now exposes:

- enterprise readiness warnings
- counterparty security posture
- compatibility vs institutional-ready sender counts
- settlement payload counts by operational state
- list of counterparties needing hardening
- review and reconciliation controls on each payload

This gives the operations team real visibility into:

- who is still onboarded with weak security
- which payloads are blocked in manual review
- which payloads failed and need follow-up
- which payloads are fully reconciled

---

## Test Cases

### Test 1 — Readable payload, no tx_hash → AWAITING_TX_HASH
```bash
curl -X POST https://your-api/api/v1/payloads/ingest \
  -H "X-API-Key: asgbfc_YOUR_KEY" \
  -H "Idempotency-Key: test-001-$(date +%s)" \
  -H "Content-Type: application/json" \
  -d '{
    "transaction_reference": "TXN-2025-001",
    "sender_wallet": "0xABCDEF1234567890",
    "receiver_wallet": "0xYOUR_MASTER_WALLET",
    "amount": "5000",
    "asset": "USDC",
    "network": "ethereum"
  }'
```
**Expected:**
```json
{
  "status": "payload_received",
  "payload_id": "...",
  "transaction_reference": "TXN-2025-001",
  "parsed": true,
  "verification_status": "AWAITING_TX_HASH"
}
```

### Test 2 — Payload with tx_hash → ALCHEMY_PENDING then verify
```bash
curl -X POST https://your-api/api/v1/payloads/ingest \
  -H "X-API-Key: asgbfc_YOUR_KEY" \
  -H "Idempotency-Key: test-002-$(date +%s)" \
  -H "Content-Type: application/json" \
  -d '{
    "tx_hash": "0xREAL_TX_HASH_HERE",
    "network": "ethereum",
    "amount": "100",
    "asset": "USDC"
  }'
```
Then trigger verification:
```bash
curl -X POST https://your-api/api/v1/admin/payloads/{payload_id}/verify \
  -H "X-Admin-API-Key: YOUR_ADMIN_KEY"
```

### Test 3 — Invalid API key → 401
```bash
curl -X POST https://your-api/api/v1/payloads/ingest \
  -H "X-API-Key: invalid_key" \
  -H "Idempotency-Key: test-003" \
  -d '{}'
```
**Expected:** `401 {"error": "invalid_api_key"}`

### Test 4 — Duplicate Idempotency-Key → 200 with idempotent flag
Send the same Idempotency-Key twice. Second response includes `"idempotent": true`.

### Test 5 — Invalid HMAC (client with hmac_required=true) → 401
Send wrong `X-Signature`. **Expected:** `401 {"error": "invalid_hmac"}`

### Test 6 — Admin Verify button
Open Dashboard → Settlement Payloads → click any row → click "Verify with Alchemy".  
Calls `POST /api/v1/admin/payloads/{id}/verify` and updates status live.

---

## Alchemy Webhook Setup

1. In your Alchemy dashboard, add a new **Address Activity** webhook.
2. Set the URL to: `https://your-api.com/api/v1/webhooks/alchemy`
3. Add your master wallet addresses as monitored addresses.
4. Copy the **Signing Key** and set `ALCHEMY_WEBHOOK_SIGNING_KEY=...` in your `.env`.

The webhook will automatically match incoming transfers to pending `ExternalPayload` records by tx_hash, receiver wallet, amount, and asset.

---

## Deployment (Low-Cost Options)

### Option A — Keep Render (current)
No changes needed. Deploy the updated code as-is. The `Dockerfile` is available for future migration.

### Option B — Oracle Cloud Free Tier (0 cost)
```bash
# On the VPS
git clone <your-repo> /app
cd /app
cp .env.example .env
# Edit .env with your values
docker build -t alshumookh .
docker run -d --restart=always \
  --env-file .env \
  -p 8000:8000 \
  --name alshumookh \
  alshumookh
```

### Option C — Hetzner CX11 (~€4/month)
Same Docker commands as above. Recommended: add Caddy or Nginx as reverse proxy for HTTPS.

### Cloudflare DNS / Proxy
1. Add `CNAME` record: `api.alshumookh-pay.com -> your Render service hostname`
2. Enable Cloudflare proxy (orange cloud)
3. Set SSL/TLS to **Full (strict)**
4. Force HTTPS in Cloudflare rules

---

## MoonPay Fix

The `defaultOnrampAmount must be a number` error was caused by sending `200,000,000` or a non-numeric string.  
**Fix:** Always use `float(amount)` when building MoonPay payloads, and test with `100` or `5000`.

---

## Files Modified / Created

```
app/models.py          — ExternalPayload model, PayloadVerificationStatus enum
app/config.py          — MASTER_WALLET_*, ALCHEMY_ETHEREUM_RPC_URL
app/database.py        — external_payloads migration + hmac_required column
app/payload_service.py — NEW: normalization engine + blockchain verifier
app/payloads.py        — NEW: ingest + admin payload routes
app/webhooks.py        — Enhanced Alchemy webhook + settlement_webhooks_router
app/main.py            — Security headers, new routers
app/static/dashboard.html — Settlement Payloads tab + modal
app/static/dashboard.js   — Payload table, modal, verify/review logic
.env.example           — Updated with new vars
Dockerfile             — NEW: production container
UPGRADE_README.md      — This file
```
