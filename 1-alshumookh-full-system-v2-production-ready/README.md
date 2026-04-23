# AL SHUMOOKH Full System v2 — API + Transak Webhook + Auto USDT Payout

Backend system for receiving Transak order events, matching them with internal payment orders, updating order status, and optionally triggering USDT payouts on Ethereum or TRON.

> Important: never commit real private keys or API secrets to GitHub. Use Render/hosting environment variables.

---

## What is included

- FastAPI backend
- PostgreSQL database
- Redis + Celery worker
- Transak widget URL creation
- Transak webhook receiver: `/webhooks/transak`
- Alchemy webhook receiver: `/webhooks/alchemy`
- Order lifecycle tracking
- Audit logs
- USDT payout service for:
  - Ethereum ERC20 USDT
  - TRON TRC20 USDT
- Idempotency protection to avoid duplicate payout after repeated webhook delivery
- Dockerfile + docker-compose
- Render deployment file
- `.env.example`

---

## Main flow

```text
1. Create internal order in /api/v1/payments/orders
2. Create Transak widget URL in /api/v1/payments/transak/widget-url
3. Customer completes payment in Transak
4. Transak sends webhook to /webhooks/transak
5. Backend verifies/decode signed payload
6. Backend matches webhook to internal order
7. If ORDER_COMPLETED:
   - mark order COMPLETED
   - check duplicate payout protection
   - if AUTO_PAYOUT_ENABLED=true, send USDT payout
   - save payout tx hash in audit_logs
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
  payments.py             Order + Transak widget endpoints
  webhooks.py             Transak/Alchemy webhooks
  transfer_service.py     Auto USDT payout logic
  wallet_service.py       Ethereum/TRON clients
  provider_service.py     Transak provider integration
  treasury.py             Treasury endpoints
  admin.py                Admin endpoints
  audit_service.py        Audit logs
worker.py                 Celery worker app
Dockerfile                Container build
 docker-compose.yml       Local Postgres/Redis/API/Worker
render.yaml               Render deployment example
.env.example              Required environment variables
```

---

## Local execution — Mac / Linux

### 1. Install tools

Install:
- Python 3.11+
- Git
- Docker Desktop
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

### 4. Run with Docker

```bash
docker compose up --build
```

API will run here:

```text
http://localhost:8000
```

API docs:

```text
http://localhost:8000/docs
```

Health check:

```text
http://localhost:8000/health
```

---

## Local execution without Docker

### 1. Create virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### 2. Start Postgres and Redis

```bash
docker run --name alsh-postgres \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_DB=alshumookh \
  -p 5432:5432 \
  -d postgres:16


docker run --name alsh-redis \
  -p 6379:6379 \
  -d redis:7
```

### 3. Start API

```bash
uvicorn app.main:app --reload --port 8000
```

### 4. Start Celery worker in another terminal

```bash
source .venv/bin/activate
celery -A worker.celery_app worker -l info
```

---

## Required environment variables

### Application

```env
APP_NAME=ALSHUMOOKH Full System v2
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

### Transak

```env
TRANSAK_BASE_URL=https://api.transak.com
TRANSAK_STAGING_BASE_URL=https://api-stg.transak.com
TRANSAK_API_KEY=replace_me
TRANSAK_API_SECRET=replace_me
TRANSAK_WEBHOOK_SECRET=replace_me_if_applicable
TRANSAK_ENV=staging
TRANSAK_DEFAULT_FIAT=AED
TRANSAK_DEFAULT_CRYPTO=USDT
TRANSAK_DEFAULT_NETWORK=ethereum
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
http://localhost:8000/webhooks/transak
http://localhost:8000/webhooks/alchemy
```

Production example:

```text
https://YOUR-DOMAIN.com/webhooks/transak
https://YOUR-DOMAIN.com/webhooks/alchemy
```

---

## GitHub upload steps

```bash
git init
git add .
git commit -m "Initial AL SHUMOOKH payment system"
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
TRANSAK_ENV=staging
AUTO_PAYOUT_ENABLED=false
```

Test:
- create order
- create widget URL
- complete Transak staging transaction
- confirm webhook arrives
- confirm order status becomes COMPLETED
- confirm `CRYPTO_PAYOUT_SKIPPED` is saved

### Phase 2 — Small payout test

Use a small amount only.

```env
AUTO_PAYOUT_ENABLED=true
```

Make sure treasury wallet has:
- USDT balance
- ETH for gas if Ethereum
- TRX energy/bandwidth/fees if TRON

### Phase 3 — Production

```env
TRANSAK_ENV=production
APP_ENV=production
APP_DEBUG=false
AUTO_PAYOUT_ENABLED=true
```

Add manual approval or daily limits before high-value payouts.

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
  -H "Content-Type: application/json" \
  -d '{
    "external_id": "test-order-001",
    "provider": "transak",
    "side": "BUY",
    "network": "ethereum",
    "fiat_currency": "AED",
    "crypto_currency": "USDT",
    "fiat_amount": 100,
    "crypto_amount": 25,
    "user_wallet_address": "0x0000000000000000000000000000000000000000"
  }'
```

Open docs:

```text
http://localhost:8000/docs
```
