# ALSHUMOOKH Enterprise Settlement API

Production domain:

```text
https://api.alshumookh-pay.com
```

This document describes the production-ready API-to-API settlement receiver that
can be used while formal certifications such as ISO 27001, SOC 2, PCI-DSS, PSD2,
or eIDAS are being completed.

## 1. Settlement Payload Ingestion

```http
POST /api/v1/payloads/ingest
Content-Type: application/json
Idempotency-Key: <unique-request-key>
X-API-Key: <client-api-key>
X-Timestamp: <unix-seconds>
X-Signature: sha256=<hmac-signature>
```

Alternative OAuth2 authentication:

```http
Authorization: Bearer <access-token>
```

The endpoint accepts structured, nested, partially structured, and custom JSON.
The full raw wire payload, parsed payload, headers, client IP, user agent,
idempotency key, auth method, and verification result are stored for audit and
reconciliation.

## 2. Public Technical Schema

```http
GET /api/v1/payloads/schema
```

This endpoint exposes the expected field names, supported aliases, required
headers, and an example payload for counterparties. It does not expose secrets.

## 3. OAuth2 Client Credentials

```http
POST /api/v1/oauth/token
Content-Type: application/x-www-form-urlencoded

grant_type=client_credentials
client_id=<oauth-client-id>
client_secret=<oauth-client-secret>
scope=settlement:ingest
```

Response:

```json
{
  "access_token": "...",
  "token_type": "Bearer",
  "expires_in": 900,
  "scope": "settlement:ingest"
}
```

## 4. HMAC Request Signature

Signature base string:

```text
X-Timestamp + "." + exact raw wire body
```

Algorithm:

```text
HMAC-SHA256 using the client hmac_secret
```

Header:

```http
X-Signature: sha256=<hex-digest>
```

## 5. JWS Detached Signature

For counterparties requiring asymmetric signatures, provide a public key when
creating the API client and enable `jws_required`.

Header:

```http
X-JWS-Signature: <compact-jws>
```

Expected JWS claims:

```json
{
  "payload_hash": "sha256-of-plaintext-json-body",
  "iat": 1770000000,
  "exp": 1770000900
}
```

Supported algorithms:

```text
RS256, PS256, ES256, ES384
```

## 6. JWE Encrypted Payloads

If `jwe_required` is enabled, the request body must be a compact JSON envelope:

```json
{
  "alg": "RSA-OAEP-256",
  "enc": "A256GCM",
  "encrypted_key": "...",
  "iv": "...",
  "ciphertext": "...",
  "tag": "...",
  "aad": "..."
}
```

The receiver decrypts the envelope using `SETTLEMENT_JWE_PRIVATE_KEY_PEM`.
HMAC is calculated over the encrypted wire body. JWS is calculated over the
decrypted plaintext body hash.

## 7. mTLS-Ready Mode

When deployed behind Cloudflare, Nginx, Caddy, or a VPS gateway, the gateway can
validate the client certificate and forward the certificate SHA-256 fingerprint:

```http
X-Client-Cert-Fingerprint: <sha256-fingerprint>
```

If `mtls_required` is enabled for the API client, ingestion is rejected unless
the fingerprint matches the configured counterparty certificate fingerprint.

## 8. Required Fields for Automatic Verification

```json
{
  "transaction_reference": "W2W-TEST-0001",
  "tx_hash": "0x...",
  "sender_wallet": "0xSenderWallet",
  "receiver_wallet": "0xReceiverMasterWallet",
  "amount": "100.00",
  "asset": "USDC",
  "network": "ethereum",
  "token_contract": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48"
}
```

Supported networks:

```text
ethereum
base
tron-placeholder
```

## 9. Verification and Reconciliation

When `tx_hash` is present, the system verifies via Alchemy/RPC:

- transaction exists
- receipt success
- ERC-20 transfer logs
- sender wallet match, when provided
- receiver wallet match against approved master wallet
- token contract match
- amount received
- block number
- confirmation count
- explorer URL

## 10. Admin Endpoints

```http
GET  /api/v1/admin/payloads
GET  /api/v1/admin/payloads/{payload_id}
POST /api/v1/admin/payloads/{payload_id}/verify
POST /api/v1/admin/payloads/{payload_id}/mark-manual-review
```

Admin endpoints require admin session or:

```http
X-Admin-API-Key: <admin-api-key>
```

## 11. Alchemy Webhook

```http
POST /api/v1/webhooks/alchemy
```

The webhook verifies the Alchemy signature and attempts to match incoming
transfers to pending settlement payloads.

## 12. Operational Status

This deployment is technically ready for controlled API-to-API settlement
testing with small amounts. Formal compliance certifications remain a separate
legal/audit process and should be completed independently.
