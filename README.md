# Alshumookh Full Payment System v1

A production-ready, multi-provider payment gateway supporting both **fiat** (Stripe) and **crypto** (Alchemy/Web3) payments with a unified API, admin dashboard, and real-time webhook processing.

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                   FastAPI Backend                    │
│                                                     │
│  ┌──────────┐  ┌──────────┐  ┌────────────────┐   │
│  │  Auth    │  │ Payments │  │    Treasury    │   │
│  │  (JWT)   │  │  Router  │  │  (Wallet Mgmt) │   │
│  └──────────┘  └──────────┘  └────────────────┘   │
│                                                     │
│  ┌──────────────────────────────────────────────┐   │
│  │              Provider Services               │   │
│  │   ┌──────────────┐   ┌────────────────────┐  │   │
│  │   │ Alchemy (Web3)│   │  Stripe (Fiat)    │  │   │
│  │   │  - ETH/ERC20  │   │  - Cards/Wallets  │  │   │
│  │   │  - Webhooks   │   │  - Webhooks        │  │   │
│  │   └──────────────┘   └────────────────────┘  │   │
│  └──────────────────────────────────────────────┘   │
│                                                     │
│  ┌───────────┐  ┌──────────┐  ┌───────────────┐   │
│  │ Celery    │  │  Redis   │  │  PostgreSQL   │   │
│  │ Workers   │  │  Cache   │  │    Database   │   │
│  └───────────┘  └──────────┘  └───────────────┘   │
└─────────────────────────────────────────────────────┘
```

## Features

- ✅ **Crypto Payments** via Alchemy (ETH, USDT, USDC, DAI, MATIC)
- ✅ **Fiat Payments** via Stripe (Cards, Apple/Google Pay)
- ✅ **Wallet Management** with HD wallet derivation
- ✅ **Treasury System** for fund management and sweeping
- ✅ **Matching Engine** to correlate on-chain txns with orders
- ✅ **Webhook Processing** (Alchemy Address Activity + Stripe)
- ✅ **Admin Dashboard** with real-time stats
- ✅ **JWT Authentication** with refresh tokens
- ✅ **Rate Limiting** via SlowAPI
- ✅ **Audit Logging** for all transactions
- ✅ **Email/SMS Notifications** (SendGrid + Twilio)
- ✅ **Reconciliation Service** for daily settlement
- ✅ **Prometheus Metrics** endpoint
- ✅ **Celery Background Workers**

---

## Quick Start

### 1. Clone & Setup

```bash
git clone <repo>
cd alshumookh-full-system-v1
cp .env.example .env
# Edit .env with your credentials
```

### 2. Install Dependencies

```bash
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Start Services

```bash
# Start PostgreSQL & Redis (Docker)
docker-compose up -d postgres redis

# Run DB migrations
alembic upgrade head

# Start API server
uvicorn app.app.main:app --reload --port 8000

# Start Celery worker (separate terminal)
celery -A worker.celery_app worker --loglevel=info
```

### 4. Access

| Service | URL |
|---------|-----|
| API Docs (Swagger) | http://localhost:8000/docs |
| API Docs (ReDoc) | http://localhost:8000/redoc |
| Admin Dashboard | http://localhost:8000/static/dashboard.html |
| Create Payment | http://localhost:8000/static/create-payment.html |
| Metrics | http://localhost:8000/metrics |

---

## API Reference

### Authentication

```http
POST /api/v1/auth/register
POST /api/v1/auth/login
POST /api/v1/auth/refresh
POST /api/v1/auth/logout
```

### Payments

```http
POST /api/v1/payments/          # Create payment (fiat or crypto)
GET  /api/v1/payments/{id}      # Get payment status
GET  /api/v1/payments/          # List payments
POST /api/v1/payments/{id}/cancel
```

### Crypto

```http
POST /api/v1/crypto/address     # Generate deposit address
GET  /api/v1/crypto/rates       # Get current rates
GET  /api/v1/crypto/balance/{address}
```

### Fiat

```http
POST /api/v1/fiat/intent        # Create Stripe PaymentIntent
POST /api/v1/fiat/confirm/{id}  # Confirm payment
```

### Treasury

```http
GET  /api/v1/treasury/balance
POST /api/v1/treasury/sweep     # Sweep funds to treasury
GET  /api/v1/treasury/transactions
```

### Webhooks

```http
POST /webhooks/alchemy          # Alchemy address activity
POST /webhooks/stripe           # Stripe events
```

### Admin

```http
GET  /api/v1/admin/stats
GET  /api/v1/admin/users
GET  /api/v1/admin/payments
POST /api/v1/admin/users/{id}/suspend
```

---

## Environment Variables

See `.env.example` for full configuration reference.

### Required for Production

| Variable | Description |
|----------|-------------|
| `DATABASE_URL` | PostgreSQL async connection string |
| `SECRET_KEY` | App secret (min 32 chars) |
| `ALCHEMY_API_KEY` | From [alchemy.com](https://alchemy.com) |
| `STRIPE_SECRET_KEY` | From Stripe Dashboard |
| `TREASURY_WALLET_ADDRESS` | Hot wallet for sweeps |

---

## Deployment (Render)

```bash
# Push to GitHub, then connect repo in Render Dashboard
# render.yaml is pre-configured for:
#   - Web service (FastAPI)
#   - Worker service (Celery)
#   - Redis instance
#   - PostgreSQL database
```

---

## Security Notes

- All private keys are encrypted at rest using AES-256
- Webhook signatures validated on every request
- Rate limiting on all public endpoints
- SQL injection prevention via SQLAlchemy ORM
- CORS restricted to configured origins

---

## License

Proprietary — Alshumookh © 2024
