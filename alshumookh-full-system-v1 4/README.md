# Alshumookh Full Payment System v1

Production-ready, multi-provider payment gateway supporting **fiat** (Stripe) and **crypto** (Alchemy/Web3) with a unified API, admin dashboard, and real-time webhook processing.

---

## Project Structure

```
alshumookh-full-system-v1/
├── app/
│   ├── __init__.py
│   ├── main.py                    # FastAPI entry point
│   └── app/
│       ├── __init__.py
│       ├── config.py              # Settings (env vars)
│       ├── database.py            # Async SQLAlchemy setup
│       ├── models.py              # All DB models
│       ├── schemas.py             # Pydantic v2 schemas
│       ├── auth.py                # JWT auth router
│       ├── deps.py                # FastAPI dependencies
│       ├── utils.py               # Encryption, QR, helpers
│       ├── payments.py            # Payments router
│       ├── fiat.py                # Stripe fiat router
│       ├── crypto.py              # Crypto router
│       ├── treasury.py            # Treasury router + service
│       ├── admin.py               # Admin router
│       ├── webhooks.py            # Alchemy + Stripe webhooks
│       ├── alchemy_service.py     # Web3/Alchemy wrapper
│       ├── wallet_service.py      # HD wallet derivation
│       ├── provider_service.py    # Payment creation routing
│       ├── matching_service.py    # Tx ↔ payment matching
│       ├── audit_service.py       # Audit logging
│       ├── notification_service.py # Email/SMS
│       ├── reconciliation_service.py
│       ├── tasks/                 # Celery task modules
│       │   ├── __init__.py
│       │   ├── payment_tasks.py
│       │   ├── notification_tasks.py
│       │   ├── reconciliation_tasks.py
│       │   └── treasury_tasks.py
│       └── static/                # Dashboard + payment pages
│           ├── dashboard.html
│           ├── create-payment.html
│           └── payment-status.html
├── alembic/                       # DB migrations
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
├── worker.py                      # Celery worker entry point
├── alembic.ini
├── render.yaml                    # Render deployment config
├── requirements.txt
├── .env.example
├── .python-version
└── .gitignore
```

---

## Quick Start (Local)

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
source venv/bin/activate
pip install -r requirements.txt
```

### 3. Start Services

```bash
# Start PostgreSQL & Redis
docker run -d --name pg -e POSTGRES_DB=alshumookh -e POSTGRES_USER=user -e POSTGRES_PASSWORD=password -p 5432:5432 postgres:16
docker run -d --name redis -p 6379:6379 redis:7

# The app auto-creates tables on startup, but for production use Alembic:
# alembic upgrade head

# Start API server
uvicorn app.main:app --reload --port 8000

# Start Celery worker (separate terminal)
celery -A worker.celery_app worker --loglevel=info
```

### 4. Access

| Service             | URL                                            |
|---------------------|------------------------------------------------|
| API Docs (Swagger)  | http://localhost:8000/docs                     |
| Admin Dashboard     | http://localhost:8000/static/dashboard.html    |
| Create Payment      | http://localhost:8000/static/create-payment.html |
| Health Check        | http://localhost:8000/health                   |

Default admin login: `admin@alshumookh.com` / password from `ADMIN_PASSWORD` env var.

---

## Deploy to Render

### Option A: Using render.yaml (Recommended)

1. Push this repo to GitHub
2. Go to [Render Dashboard](https://dashboard.render.com) → **New** → **Blueprint**
3. Connect your GitHub repo
4. Render reads `render.yaml` and provisions:
   - Web service (FastAPI + Gunicorn)
   - Worker service (Celery)
   - Redis instance
   - PostgreSQL database
5. Set required env vars in Render dashboard:
   - `ADMIN_PASSWORD` — strong password for admin account
   - `ALCHEMY_API_KEY` — from [alchemy.com](https://alchemy.com)
   - `STRIPE_SECRET_KEY` — from Stripe Dashboard
   - `STRIPE_PUBLISHABLE_KEY` — from Stripe Dashboard
   - `STRIPE_WEBHOOK_SECRET` — from Stripe webhook settings
   - `TREASURY_WALLET_ADDRESS` — your ETH hot wallet

### Option B: Manual Setup

1. Create a PostgreSQL database on Render
2. Create a Redis instance on Render
3. Create a Web Service:
   - **Build**: `pip install -r requirements.txt`
   - **Start**: `gunicorn app.main:app --workers 2 --worker-class uvicorn.workers.UvicornWorker --bind 0.0.0.0:$PORT`
4. Create a Worker Service:
   - **Start**: `celery -A worker.celery_app worker --loglevel=info --concurrency=2`
5. Wire up env vars (DATABASE_URL, REDIS_URL, etc.)

### Important Notes for Render

- **DATABASE_URL**: Render provides `postgres://` format — the app auto-converts to `postgresql+asyncpg://`
- **Tables**: Auto-created on first startup via `init_db()`
- **Admin user**: Auto-seeded on startup using `ADMIN_EMAIL` + `ADMIN_PASSWORD`
- **Static files**: Served at `/static/` path
- **Health check**: `/health` endpoint monitors DB + Redis

---

## API Reference

### Authentication
```
POST /api/v1/auth/register    — Create account
POST /api/v1/auth/login       — Get JWT tokens
POST /api/v1/auth/refresh     — Refresh access token
```

### Payments
```
POST /api/v1/payments/         — Create payment (fiat or crypto)
GET  /api/v1/payments/         — List your payments
GET  /api/v1/payments/{id}     — Get payment details
POST /api/v1/payments/{id}/cancel
```

### Crypto
```
POST /api/v1/crypto/address    — Generate deposit address
GET  /api/v1/crypto/rates      — Token prices
GET  /api/v1/crypto/balance/{address}
```

### Fiat
```
POST /api/v1/fiat/intent       — Create Stripe PaymentIntent
POST /api/v1/fiat/confirm/{id}
```

### Treasury (Admin)
```
GET  /api/v1/treasury/balance
POST /api/v1/treasury/sweep
GET  /api/v1/treasury/transactions
```

### Webhooks
```
POST /webhooks/alchemy         — Alchemy address activity
POST /webhooks/stripe          — Stripe events
```

### Admin
```
GET  /api/v1/admin/stats
GET  /api/v1/admin/users
GET  /api/v1/admin/payments
POST /api/v1/admin/users/{id}/suspend
```

---

## Security

- Private keys encrypted at rest (AES-256 via Fernet)
- Webhook signatures validated (HMAC-SHA256)
- Rate limiting on all endpoints (SlowAPI)
- JWT with refresh token rotation
- CORS restricted to configured origins
- SQL injection prevention via SQLAlchemy ORM

---

## License

Proprietary — Alshumookh © 2024
