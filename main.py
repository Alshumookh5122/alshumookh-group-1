"""
Alshumookh Payment System — FastAPI Application Entry Point
"""

import time
import structlog
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from prometheus_fastapi_instrumentator import Instrumentator

from app.app.config import settings
from app.app.database import init_db, close_db

# Routers
from app.app.auth import router as auth_router
from app.app.payments import router as payments_router
from app.app.fiat import router as fiat_router
from app.app.crypto import router as crypto_router
from app.app.treasury import router as treasury_router
from app.app.webhooks import router as webhooks_router
from app.app.admin import router as admin_router

logger = structlog.get_logger()


# ── Rate Limiter ─────────────────────────────────────────────────────────────
limiter = Limiter(key_func=get_remote_address)


# ── Lifespan ──────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("app.starting", version=settings.APP_VERSION, env=settings.ENVIRONMENT)
    await init_db()

    # Sentry
    if settings.SENTRY_DSN:
        import sentry_sdk
        sentry_sdk.init(dsn=settings.SENTRY_DSN, traces_sample_rate=0.1)
        logger.info("sentry.initialized")

    yield

    # Shutdown
    logger.info("app.shutting_down")
    await close_db()


# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="""
## Alshumookh Payment System API

Unified payment gateway supporting **fiat** (Stripe) and **crypto** (Alchemy/Web3).

### Features
- 💳 Fiat payments via Stripe (Cards, Apple Pay, Google Pay)
- ₿ Crypto payments (ETH, USDT, USDC, DAI, MATIC) via Alchemy
- 🔐 JWT authentication with refresh tokens
- 🔔 Real-time webhook processing
- 🏦 Treasury management with auto-sweep
- 📊 Admin dashboard and reporting
    """,
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# ── Middleware ────────────────────────────────────────────────────────────────
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(GZipMiddleware, minimum_size=1000)


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    start = time.time()
    response = await call_next(request)
    duration = time.time() - start
    logger.info(
        "http.request",
        method=request.method,
        path=request.url.path,
        status=response.status_code,
        duration_ms=round(duration * 1000, 2),
    )
    return response


# ── Prometheus Metrics ────────────────────────────────────────────────────────
Instrumentator().instrument(app).expose(app)


# ── Static Files ──────────────────────────────────────────────────────────────
app.mount("/static", StaticFiles(directory="app/app/static"), name="static")


# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(auth_router)
app.include_router(payments_router)
app.include_router(fiat_router)
app.include_router(crypto_router)
app.include_router(treasury_router)
app.include_router(webhooks_router)
app.include_router(admin_router)


# ── Health Check ──────────────────────────────────────────────────────────────
@app.get("/health", tags=["System"])
async def health_check():
    """System health check — used by Render and load balancers."""
    from app.app.database import engine
    from datetime import datetime
    import redis.asyncio as aioredis

    db_status = "ok"
    redis_status = "ok"

    try:
        async with engine.connect() as conn:
            await conn.execute(__import__("sqlalchemy").text("SELECT 1"))
    except Exception:
        db_status = "error"

    try:
        r = aioredis.from_url(settings.REDIS_URL)
        await r.ping()
        await r.aclose()
    except Exception:
        redis_status = "error"

    overall = "ok" if db_status == "ok" and redis_status == "ok" else "degraded"

    return {
        "status": overall,
        "version": settings.APP_VERSION,
        "environment": settings.ENVIRONMENT,
        "database": db_status,
        "redis": redis_status,
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.get("/", tags=["System"])
async def root():
    return {
        "name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "docs": "/docs",
        "health": "/health",
    }
