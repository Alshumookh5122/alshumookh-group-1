# ALSHUMOOKH GLOBAL BANKING FINANCE & CREDIT — API + MoonPay Commerce Webhook

Backend system for ALSHUMOOKH GLOBAL BANKING FINANCE & CREDIT to create MoonPay Commerce payment links, receive provider events, match them with internal payment orders, and track the order lifecycle for non-custodial crypto payments.

> Important: never commit real private keys or API secrets to GitHub. Use Render/hosting environment variables.

---

## What is included

- FastAPI backend
- PostgreSQL database
- Redis + Celery worker
- MoonPay Commerce link creation
- MoonPay webhook receiver: `/webhooks/moonpay`
- Alchemy webhook receiver: `/webhooks/alchemy`
- Order lifecycle tracking
- Audit logs
- Treasury balance checks for Ethereum/TRON
- Provider direct-delivery flow to avoid duplicate internal payouts
- Render deployment file
- `.env.example`

---

## Main flow

```text
1. Create an API client in /api/v1/admin/clients
2. Configure your Ledger wallet address in `LEDGER_BASE_ADDRESS`
3. Create a MoonPay order in /api/v1/payments/moonpay/orders with X-API-Key
4. Customer completes payment in MoonPay Commerce
5. MoonPay sends webhook to /webhooks/moonpay
6. Backend verifies MoonPay webhook signature
7. Backend matches webhook to internal order
8. If onramp.transaction.success:
   - mark order COMPLETED
   - save MoonPay payload in audit_logs
   - skip internal payout because MoonPay delivers directly to the destination wallet
```

---

## API clients and HMAC webhooks

Create a client with the admin key:

```bash
curl -X POST http://localhost:8000/api/v1/admin/clients \
  -H "X-Admin-API-Key: change_me_admin_key" \
  -H "Content-Type: application/json" \
  -d '{"name":"Demo Client","allowed_ips":["127.0.0.1"]}'
```

The response returns the raw `api_key` and `hmac_secret` once. Store them safely.

Protected client endpoints require:

```text
X-API-Key: <client_api_key>
```

Generic provider webhooks can be sent to:

```text
POST /webhooks/provider
X-API-Key: <client_api_key>
X-Signature: sha256=<hex_hmac_sha256_of_raw_body>
```

MoonPay, Coinbase legacy, and Alchemy webhooks keep their provider-specific verification.

---

## Executive setup

### 1. MoonPay Commerce

Create MoonPay Commerce API credentials, then set:

```env
MOONPAY_API_KEY=your_public_api_key
MOONPAY_API_SECRET=your_secret_api_key_or_bearer_token
MOONPAY_DEPOSIT_ID=your_deposit_id
MOONPAY_WEBHOOK_SECRET=your_webhook_secret
```

Create a MoonPay Commerce webhook endpoint pointing to:

```text
https://YOUR-DOMAIN.com/webhooks/moonpay
```

### 2. Ledger destination

Use the receive address from your Ledger wallet for the network you want to receive on:

```env
LEDGER_BASE_ADDRESS=0xYOUR_LEDGER_BASE_ADDRESS
LEDGER_ETHEREUM_ADDRESS=0xYOUR_LEDGER_ETHEREUM_ADDRESS
```

For the lowest fees, Base + USDC is the recommended default.

### 3. Create a client API key

Start the API, then run:

```bash
curl -X POST http://localhost:8000/api/v1/admin/clients \
  -H "X-Admin-API-Key: change_me_admin_key" \
  -H "Content-Type: application/json" \
  -d '{"name":"Main Dashboard"}'
```

Save the returned `api_key`. It is shown once.

### 4. Create a real MoonPay payment link

```bash
curl -X POST http://localhost:8000/api/v1/transactions \
  -H "X-API-Key: YOUR_CLIENT_API_KEY" \
  -H "Idempotency-Key: invoice-1001" \
  -H "Content-Type: application/json" \
  -d '{
    "external_id": "invoice-1001",
    "network": "base",
    "fiat_currency": "USD",
    "crypto_currency": "USDC",
    "fiat_amount": 100,
    "country": "US"
  }'
```

Open `checkout_url` from the response. MoonPay Commerce sends supported crypto payments directly to your Ledger address.

The response shape is:

```json
{
  "transaction_id": "...",
  "external_id": "invoice-1001",
  "status": "CREATED",
  "provider": "moonpay",
  "checkout_url": "https://moonpay.hel.io/deposit/..."
}
```

### 5. API-to-API status checks

Check by internal transaction id:

```bash
curl http://localhost:8000/api/v1/transactions/TRANSACTION_ID \
  -H "X-API-Key: YOUR_CLIENT_API_KEY"
```

Check by your external id:

```bash
curl http://localhost:8000/api/v1/transactions/external/invoice-1001 \
  -H "X-API-Key: YOUR_CLIENT_API_KEY"
```

### 6. Open the dashboard

```text
http://localhost:8000/dashboard
```

Enter:

```text
Admin API Key = ADMIN_API_KEY from .env
Client API Key = api_key returned from /api/v1/admin/clients
```

---

## Folder structure

```text
app/
  main.py                 FastAPI app
  config.py               Environment settings
  database.py             SQLAlchemy connection
  models.py               DB models
  schemas.py              Pydantic schemas
  payments.py             Order + Coinbase Onramp endpoints
  webhooks.py             Coinbase/Alchemy webhooks
  transfer_service.py     Legacy treasury payout guardrails
  wallet_service.py       Ethereum/TRON clients
  provider_service.py     Coinbase provider integration
  treasury.py             Treasury endpoints
  admin.py                Admin endpoints
  audit_service.py        Audit logs
worker.py                 Celery worker app
scripts/run_api.sh        Local API runner without Docker
scripts/run_worker.sh     Local worker runner without Docker
scripts/check_env.py      Environment readiness check
render.yaml               Render deployment example
.env.example              Required environment variables
```

---

## Local execution — Mac / Linux

### 1. Install tools

Install:
- Python 3.11+
- Git
- PostgreSQL 16+ or a managed PostgreSQL database
- Redis 7+ or a managed Redis database
- VS Code or Rider

### 2. Unzip and enter folder

```bash
cd alshumookh-full-system-v2-production-ready
```

### 3. Create environment file

```bash
cp .env.example .env
```

Open `.env` and fill your credentials.

For first testing, keep:

```env
AUTO_PAYOUT_ENABLED=false
```

This means webhooks update orders and save logs, but no real crypto is sent.

### 4. Install and run without Docker

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

Make sure PostgreSQL and Redis are running, then update `.env`:

```env
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/alshumookh
SYNC_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/alshumookh
REDIS_URL=redis://localhost:6379/0
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/0
```

Check required values:

```bash
source .venv/bin/activate
python scripts/check_env.py
```

Start the API:

```bash
source .venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Or use the helper:

```bash
./scripts/run_api.sh
```

Start the worker in another terminal:

```bash
source .venv/bin/activate
celery -A worker.celery_app worker -l info
```

Or use the helper:

```bash
./scripts/run_worker.sh
```

API will run here:

```text
http://localhost:8000
```

Docs: `http://localhost:8000/docs`
Dashboard: `http://localhost:8000/dashboard`
Health: `http://localhost:8000/health`

---

## Required environment variables

### Application

```env
APP_NAME=ALSHUMOOKH GLOBAL BANKING FINANCE & CREDIT
APP_ENV=development
APP_DEBUG=true
APP_HOST=0.0.0.0
APP_PORT=8000
API_PREFIX=/api/v1
ADMIN_API_KEY=change_me_admin_key
```

### Database and Redis

```env
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/alshumookh
SYNC_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/alshumookh
REDIS_URL=redis://localhost:6379/0
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/0
```

### Coinbase CDP Onramp

```env
COINBASE_API_HOST=api.cdp.coinbase.com
COINBASE_API_KEY_ID=replace_me
COINBASE_API_KEY_SECRET=replace_me
COINBASE_WEBHOOK_SECRET=replace_me_from_webhook_subscription
COINBASE_DEFAULT_PAYMENT_CURRENCY=USD
COINBASE_DEFAULT_PURCHASE_CURRENCY=USDC
COINBASE_DEFAULT_NETWORK=base
```

### Ethereum / Alchemy

```env
ALCHEMY_API_KEY=replace_me
ALCHEMY_NETWORK=eth-mainnet
ALCHEMY_WEBHOOK_SIGNING_KEY=replace_me
ETH_TREASURY_ADDRESS=0x0000000000000000000000000000000000000000
ETH_TREASURY_PRIVATE_KEY=
USDT_ETH_CONTRACT=0xdAC17F958D2ee523a2206206994597C13D831ec7
```

### TRON

```env
TRON_API_URL=https://api.trongrid.io
TRON_API_KEY=replace_me
TRON_TREASURY_ADDRESS=TRON_TREASURY_ADDRESS_HERE
TRON_TREASURY_PRIVATE_KEY=
USDT_TRON_CONTRACT=TXLAQ63Xg1NAzckPwKHvzw7CSEmLMEqcdj
```

### Auto payout switch

```env
AUTO_PAYOUT_ENABLED=false
```

Change to `true` only after testing.

---

## Webhook URLs

Local:

```text
http://localhost:8000/webhooks/coinbase
http://localhost:8000/webhooks/alchemy
```

Production example:

```text
https://YOUR-DOMAIN.com/webhooks/coinbase
https://YOUR-DOMAIN.com/webhooks/alchemy
```

---

## GitHub upload steps

```bash
git init
git add .
git commit -m "Initial ALSHUMOOKH GLOBAL BANKING FINANCE CREDIT system"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO.git
git push -u origin main
```

Do not push `.env`.

---

## Render deployment steps

1. Push the repo to GitHub.
2. Open Render.
3. Create new Web Service from your GitHub repo.
4. Build command:

```bash
pip install -r requirements.txt
```

5. Start command:

```bash
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

6. Add environment variables from `.env.example` in Render dashboard.
7. Add managed PostgreSQL.
8. Add Redis.
9. Update:

```env
DATABASE_URL=postgresql+asyncpg://...
SYNC_DATABASE_URL=postgresql+psycopg://...
REDIS_URL=redis://...
CELERY_BROKER_URL=redis://...
CELERY_RESULT_BACKEND=redis://...
```

10. Create a separate Render Worker:

```bash
celery -A worker.celery_app worker -l info
```

---

## Safe go-live process

### Phase 1 — Webhook only

```env
AUTO_PAYOUT_ENABLED=false
```

Test:
- create order
- create widget URL
- complete Coinbase Onramp test transaction
- confirm webhook arrives
- confirm order status becomes COMPLETED
- confirm `CRYPTO_PAYOUT_SKIPPED` is saved

### Phase 2 — Coinbase production rehearsal

Use a small amount only and keep internal payout disabled. Coinbase Onramp delivers directly to the destination wallet.

```env
AUTO_PAYOUT_ENABLED=false
```

Confirm:
- Coinbase returns an Onramp URL
- webhook signature verification passes
- order status becomes COMPLETED
- no internal treasury payout is sent

### Phase 3 — Production

```env
APP_ENV=production
APP_DEBUG=false
AUTO_PAYOUT_ENABLED=false
```

Keep internal payouts disabled for Coinbase Onramp unless a separate treasury payout flow is intentionally added later.

---

## Important security rules

- Never put private keys in GitHub.
- Use separate staging and production wallets.
- Keep `AUTO_PAYOUT_ENABLED=false` until matching is fully verified.
- Use allowlisted wallet addresses for high-value transactions.
- Add manual approval for large payouts.
- Monitor audit logs.
- Keep enough native gas token in treasury wallets.

---

## Test commands

Health:

```bash
curl http://localhost:8000/health
```

Create order:

```bash
curl -X POST http://localhost:8000/api/v1/payments/orders \
  -H "X-API-Key: <client_api_key>" \
  -H "Content-Type: application/json" \
  -d '{
    "external_id": "test-order-001",
    "provider": "coinbase",
    "side": "BUY",
    "network": "base",
    "fiat_currency": "USD",
    "crypto_currency": "USDC",
    "fiat_amount": 100,
    "crypto_amount": 25,
    "user_wallet_address": "0x0000000000000000000000000000000000000000"
  }'
```

Open docs:

```text
http://localhost:8000/docs
```
