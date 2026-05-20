# Settlement Ingest Test Examples

Replace placeholders before running.

## 1. OAuth2 token

```bash
curl -sS -X POST "https://api.alshumookh-pay.com/api/v1/oauth/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=client_credentials" \
  -d "client_id=YOUR_OAUTH_CLIENT_ID" \
  -d "client_secret=YOUR_OAUTH_CLIENT_SECRET" \
  -d "scope=settlement:ingest"
```

## 2. Ingest without tx_hash

Expected status: `AWAITING_TX_HASH`

```bash
curl -sS -X POST "https://api.alshumookh-pay.com/api/v1/payloads/ingest" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
  -H "Idempotency-Key: test-no-tx-001" \
  -H "Content-Type: application/json" \
  -d '{
    "transaction_reference": "W2W-TEST-NO-TX-001",
    "sender_wallet": "0xSenderWallet",
    "receiver_wallet": "0xReceiverMasterWallet",
    "amount": "100.00",
    "asset": "USDC",
    "network": "ethereum",
    "token_contract": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48"
  }'
```

## 3. Ingest with tx_hash

Expected status: `ALCHEMY_PENDING`, then admin verification can update to
`ALCHEMY_VERIFIED`, `ON_CHAIN_CONFIRMED`, `FAILED`, or `MANUAL_REVIEW`.

```bash
curl -sS -X POST "https://api.alshumookh-pay.com/api/v1/payloads/ingest" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
  -H "Idempotency-Key: test-with-tx-001" \
  -H "Content-Type: application/json" \
  -d '{
    "transaction_reference": "W2W-TEST-TX-001",
    "tx_hash": "0xREAL_TX_HASH",
    "sender_wallet": "0xSenderWallet",
    "receiver_wallet": "0xReceiverMasterWallet",
    "amount": "100.00",
    "asset": "USDC",
    "network": "ethereum",
    "token_contract": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48"
  }'
```

## 4. HMAC signature generation

```bash
BODY='{"transaction_reference":"W2W-HMAC-001","amount":"100.00","asset":"USDC","network":"ethereum"}'
TS=$(date +%s)
SIG=$(printf "%s.%s" "$TS" "$BODY" | openssl dgst -sha256 -hmac "YOUR_HMAC_SECRET" -hex | awk '{print $2}')

curl -sS -X POST "https://api.alshumookh-pay.com/api/v1/payloads/ingest" \
  -H "X-API-Key: YOUR_CLIENT_API_KEY" \
  -H "Idempotency-Key: test-hmac-001" \
  -H "X-Timestamp: $TS" \
  -H "X-Signature: sha256=$SIG" \
  -H "Content-Type: application/json" \
  -d "$BODY"
```

## 5. Schema

```bash
curl -sS "https://api.alshumookh-pay.com/api/v1/payloads/schema"
```
