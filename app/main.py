from contextlib import asynccontextmanager
import asyncio
import hmac
import logging
import os
import time
import uuid
from collections import defaultdict
from datetime import datetime, timezone

from fastapi import FastAPI, Form, HTTPException, Request, status
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.openapi.utils import get_openapi
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from app.admin import router as admin_router
from app.stripe_routes import router as stripe_router
from app.audit_middleware import audit_request_middleware
from app.auth import (
    ADMIN_SESSION_COOKIE,
    ADMIN_SESSION_MAX_AGE,
    create_admin_session_token,
    is_admin_request_authenticated,
)
from app.client_portal import router as client_portal_router
from app.coinbase_routes import router as coinbase_router
from app.config import get_settings
from app.crypto import router as crypto_router
from app.audit_service import safe_details
from app.database import get_db, init_db
from app.fiat import router as fiat_router
from app.fnfcu import router as fnfcu_router
from app.m1_funds import router as m1_funds_router
from app.payloads import admin_payloads_router, ingest_router
from app.payments import router as payments_router
from app.oauth import router as oauth_router
from app.public_pages import router as public_router
from app.request_utils import get_client_ip
from app.security import (
    add_risk_score,
    ban_ip,
    ban_remaining_seconds,
    classify_path,
    classify_user_agent,
    clear_login_failures,
    clear_security_state,
    fingerprint_key,
    is_challenge_mode,
    is_ip_banned,
    log_security_event,
    login_guard,
    rate_limit_hit,
    register_failed_login,
)
from app.transactions import router as transactions_router
from app.treasury import router as treasury_router
from app.webhooks import router as webhooks_router, settlement_webhooks_router
from app.dashboard_pages import router as dashboard_pages_router
from app.client_pages import router as client_pages_router
from app.tasks.transfer_confirmations import transfer_confirmation_monitor_loop
from app.chat_routes import router as chat_router
from app.partner_dispatch import router as partner_dispatch_router

# مهم جداً: استيراد الموديلز حتى يتم تسجيل الجداول قبل create_all
import app.models  # noqa: F401

try:
    import sentry_sdk
except ImportError:  # pragma: no cover - optional dependency
    sentry_sdk = None

settings = get_settings()
logger = logging.getLogger(__name__)
APP_STARTED_AT = datetime.now(timezone.utc).isoformat()

sentry_dsn = (settings.sentry_dsn or "").strip()
CANONICAL_HOST = "api.alshumookh-pay.com"
LEGACY_HOSTS = {"alshumookh.finance", "www.alshumookh.finance"}

if sentry_sdk and sentry_dsn.startswith(("http://", "https://")):
    sentry_sdk.init(dsn=sentry_dsn)
elif sentry_dsn and not sentry_sdk:
    logger.warning("SENTRY_DSN is configured but sentry_sdk is not installed.")


# ── In-memory rate limiter for login attempts ────────────────────────────────
# Tracks failed login timestamps per IP. Works for single-worker deployments.
# For multi-worker, use Redis. WEB_CONCURRENCY=1 on Render — this is safe.
_login_attempts: dict[str, list[float]] = defaultdict(list)
RATE_LIMIT_MAX_ATTEMPTS = 5        # max failed attempts before lockout
RATE_LIMIT_WINDOW_SECONDS = 600    # 10-minute window
RATE_LIMIT_LOCKOUT_SECONDS = 600   # 10-minute lockout

# ── Lightweight public request guard ─────────────────────────────────────────
_public_hits: dict[str, list[float]] = defaultdict(list)
PUBLIC_RATE_LIMIT_WINDOW_SECONDS = 60
PUBLIC_RATE_LIMIT_MAX_REQUESTS = 120
PROBE_PATH_PREFIXES = (
    "/.git",
    "/.env",
    "/wp-login",
    "/phpmyadmin",
    "/cgi-bin",
    "/server-status",
    "/actuator",
    "/vendor",
    "/boaform",
    "/HNAP1",
)
PUBLIC_SAFE_PATHS = {
    "/",
    "/login",
    "/dashboard",
    "/dashboard/login",
    "/client",
    "/client/login",
    "/health",
    "/ready",
    "/support",
    "/favicon.ico",
    "/favicon.png",
    "/apple-touch-icon.png",
    "/apple-touch-icon-precomposed.png",
    "/robots.txt",
    "/security.txt",
    "/.well-known/security.txt",
}
API_CLIENT_SAFE_PATHS = {
    "/api/v1/oauth/token",
    "/api/v1/payloads/ingest",
    "/api/v1/payloads/schema",
    "/api/v1/webhooks/stripe",
    "/api/v1/webhooks/alchemy",
    "/api/v1/webhooks/circle",
    "/api/v1/webhooks/coinbase",
    "/api/v1/webhooks/moonpay",
    "/webhooks/alchemy",
    "/webhooks/coinbase",
    "/webhooks/moonpay",
    "/api/v1/transfer-request",
    "/api/v1/transfers",
}
API_CLIENT_SAFE_PREFIXES = (
    "/api/v1/transfer/",
)


def _get_client_ip(request: Request) -> str:
    return get_client_ip(request) or "unknown"


def _is_rate_limited(ip: str) -> bool:
    """Returns True if the IP has exceeded failed login attempts."""
    now = time.time()
    # Prune old attempts outside the window
    _login_attempts[ip] = [
        t for t in _login_attempts[ip]
        if now - t < RATE_LIMIT_WINDOW_SECONDS
    ]
    return len(_login_attempts[ip]) >= RATE_LIMIT_MAX_ATTEMPTS


def _record_failed_attempt(ip: str) -> int:
    """Records a failed attempt and returns remaining attempts before lockout."""
    _login_attempts[ip].append(time.time())
    return max(0, RATE_LIMIT_MAX_ATTEMPTS - len(_login_attempts[ip]))


def _clear_attempts(ip: str) -> None:
    """Clears failed attempts after successful login."""
    _login_attempts.pop(ip, None)


def _is_public_rate_limited(ip: str) -> bool:
    now = time.time()
    _public_hits[ip] = [
        t for t in _public_hits[ip]
        if now - t < PUBLIC_RATE_LIMIT_WINDOW_SECONDS
    ]
    return len(_public_hits[ip]) >= PUBLIC_RATE_LIMIT_MAX_REQUESTS


def _record_public_hit(ip: str) -> None:
    _public_hits[ip].append(time.time())


def _request_country(request: Request) -> str | None:
    value = request.headers.get("cf-ipcountry")
    if not value:
        return None
    cleaned = str(value).strip().upper()
    return cleaned if cleaned and cleaned != "XX" else None


def _is_api_client_safe_path(path: str) -> bool:
    return path in API_CLIENT_SAFE_PATHS or any(
        path.startswith(prefix) for prefix in API_CLIENT_SAFE_PREFIXES
    )


def _normalize_waf_path(path: str) -> str:
    normalized = str(path or "/")
    while "//" in normalized:
        normalized = normalized.replace("//", "/")
    return normalized


def _is_secure_cookie_context() -> bool:
    public_url = str(settings.public_base_url or settings.public_app_url or "").lower()
    return settings.app_env == "production" or public_url.startswith("https://")


def _is_health_authorized(request: Request) -> bool:
    client_ip = _get_client_ip(request)
    allowed_ips = set(settings.health_allowed_ips())
    if client_ip and client_ip in allowed_ips:
        return True

    expected_token = str(settings.healthcheck_token or "").strip()
    provided_token = str(request.headers.get("x-health-token") or "").strip()
    if expected_token and hmac.compare_digest(provided_token, expected_token):
        return True

    return False


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    warnings = settings.readiness_warnings()
    app.state.readiness_warnings = warnings
    if warnings:
        logger.warning("Enterprise readiness warnings: %s", warnings)
    else:
        logger.info("Enterprise readiness check passed with no warnings.")
    confirmation_monitor_task = None
    if settings.transfer_confirmation_monitor_enabled:
        confirmation_monitor_task = asyncio.create_task(transfer_confirmation_monitor_loop())
        app.state.transfer_confirmation_monitor_task = confirmation_monitor_task
    try:
        yield
    finally:
        if confirmation_monitor_task:
            confirmation_monitor_task.cancel()
            try:
                await confirmation_monitor_task
            except asyncio.CancelledError:
                logger.info("Outbound transfer confirmation monitor stopped.")


app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    debug=settings.app_debug,
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allowed_origins(),
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


# ── Security headers middleware ──────────────────────────────────────────────
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Safety wrapper — middleware must NEVER crash the request
        try:
            return await self._secure_dispatch(request, call_next)
        except Exception as exc:
            logger.exception("SecurityHeadersMiddleware unhandled error: %s", exc)
            try:
                return await call_next(request)
            except Exception:
                return JSONResponse(status_code=500, content={"detail": "Internal server error"})

    async def _secure_dispatch(self, request: Request, call_next):
        path = request.url.path or "/"
        waf_path = _normalize_waf_path(path)
        host = (request.headers.get("host") or "").split(":", 1)[0].lower()

        is_static_asset = path.startswith("/static/")
        is_public_chat = path.startswith("/api/v1/chat/start") or path.startswith("/api/v1/chat/reply") or path.startswith("/api/v1/chat/session/")
        is_public_safe = path in PUBLIC_SAFE_PATHS or is_static_asset or is_public_chat

        # ── Resolve client IP ────────────────────────────────────────────────
        try:
            request.state.proxy_ip = request.client.host if request.client else None
            request.state.trusted_proxy = request.state.proxy_ip in set(settings.trusted_proxy_ips())
            request.state.client_ip = get_client_ip(request)
            request.state.geo_country = _request_country(request)
        except Exception:
            request.state.proxy_ip = None
            request.state.trusted_proxy = False
            request.state.client_ip = None
            request.state.geo_country = None

        ip = _get_client_ip(request) or "unknown"
        user_agent = str(request.headers.get("user-agent") or "")
        request_id = getattr(request.state, "request_id", None)
        country = getattr(request.state, "geo_country", None)
        admin_key_header = str(request.headers.get("x-admin-api-key") or "")
        is_admin_api_path = (
            path.startswith(f"{settings.api_prefix}/admin")
            or path.startswith("/dashboard/api/")
        )
        is_dashboard_path = path.startswith("/dashboard/")
        has_valid_admin_key = bool(settings.admin_api_key) and hmac.compare_digest(
            admin_key_header,
            str(settings.admin_api_key),
        )
        is_authenticated_admin_request = (is_admin_api_path or is_dashboard_path) and (
            has_valid_admin_key or is_admin_request_authenticated(request)
        )
        is_waf_exempt = is_public_safe or is_authenticated_admin_request
        is_api_client_safe = _is_api_client_safe_path(path)
        is_access_block_exempt = is_waf_exempt or is_api_client_safe

        # ── Geo blocking (only if explicitly configured) ──────────────────────
        try:
            allowed_countries = set(settings.allowed_countries())
            blocked_countries = set(settings.blocked_countries())
            if country and ((allowed_countries and country not in allowed_countries) or (blocked_countries and country in blocked_countries)):
                await log_security_event(
                    "SECURITY_GEO_BLOCKED",
                    {"classification": "blocked", "country": country},
                    ip=ip, path=path, method=request.method,
                    user_agent=user_agent, status_code=403, request_id=request_id,
                )
                return JSONResponse(status_code=403, content={"detail": "Region access is restricted"})
        except Exception:
            pass

        # ── Internal health endpoint isolation ────────────────────────────────
        if path == "/internal/health":
            if not _is_health_authorized(request):
                return Response(status_code=404)

        # ── Quietly drop already-banned scanner traffic before it can create
        # noisy challenge/blocked events. API client and admin-safe paths are
        # still exempt through is_access_block_exempt.
        try:
            if is_ip_banned(ip) and not is_access_block_exempt:
                silent_probe_blocks = bool(getattr(settings, "security_silent_probe_blocks", True))
                if silent_probe_blocks:
                    return Response(status_code=204)
        except Exception:
            pass

        # ── WAF: suspicious user-agent (only block on non-public paths) ───────
        try:
            ua_classification, ua_score, block_ua = classify_user_agent(user_agent)
            if ua_score and not is_waf_exempt and not is_api_client_safe:
                score = add_risk_score(ip, ua_score, reason=ua_classification)
                await log_security_event(
                    "SECURITY_USER_AGENT_FLAGGED",
                    {"classification": ua_classification, "score": score, "country": country},
                    ip=ip, path=path, method=request.method,
                    user_agent=user_agent,
                    status_code=403 if block_ua else None,
                    request_id=request_id,
                )
            # Only block scanners on non-public paths to avoid false positives
            if block_ua and not is_waf_exempt and not is_api_client_safe:
                ban_ip(ip, 900)
                return JSONResponse(
                    status_code=403,
                    headers={"X-WAF-Action": "blocked"},
                    content={"detail": "Access denied"},
                )
        except Exception:
            pass

        # ── WAF: suspicious path probes ───────────────────────────────────────
        try:
            path_classification, path_score, _ = classify_path(waf_path)
            if path_classification or waf_path.startswith(PROBE_PATH_PREFIXES):
                score = add_risk_score(ip, path_score or 5, reason=path_classification or "probe", path=waf_path)
                silent_probe_blocks = bool(getattr(settings, "security_silent_probe_blocks", True))
                if not silent_probe_blocks:
                    await log_security_event(
                        "SECURITY_HONEYPOT_TRIGGERED" if path_classification == "honeypot" else "SECURITY_PATH_PROBE_BLOCKED",
                        {
                            "classification": path_classification or "probe",
                            "score": score,
                            "path": path,
                            "normalized_path": waf_path,
                            "country": country,
                        },
                        ip=ip, path=path, method=request.method,
                        user_agent=user_agent, status_code=404, request_id=request_id,
                    )
                    logger.warning("Blocked suspicious probe path %s from IP %s", path, ip)
                return Response(status_code=204 if silent_probe_blocks else 404)
        except Exception:
            pass

        # ── Canonical host redirect happens after WAF path checks so scanners
        # probing legacy domains are blocked instead of being forwarded.
        if host in LEGACY_HOSTS:
            target = request.url.replace(scheme="https", netloc=CANONICAL_HOST)
            return RedirectResponse(str(target), status_code=status.HTTP_308_PERMANENT_REDIRECT)

        # ── IP ban check (skip for public pages) ──────────────────────────────
        try:
            if is_ip_banned(ip) and not is_access_block_exempt:
                silent_probe_blocks = bool(getattr(settings, "security_silent_probe_blocks", True))
                if silent_probe_blocks:
                    return Response(status_code=204)
                await log_security_event(
                    "SECURITY_BANNED_IP_BLOCKED",
                    {"classification": "blocked", "seconds_remaining": ban_remaining_seconds(ip), "country": country},
                    ip=ip, path=path, method=request.method,
                    user_agent=user_agent, status_code=403, request_id=request_id,
                )
                return JSONResponse(
                    status_code=403,
                    headers={"X-WAF-Action": "blocked"},
                    content={"detail": "Access denied"},
                )

            if is_challenge_mode(ip) and not is_access_block_exempt:
                await log_security_event(
                    "SECURITY_CHALLENGE_MODE",
                    {"classification": "suspicious", "country": country},
                    ip=ip, path=path, method=request.method,
                    user_agent=user_agent, status_code=403, request_id=request_id,
                )
                return JSONResponse(
                    status_code=403,
                    headers={"X-WAF-Action": "challenge"},
                    content={"detail": "Request requires additional verification"},
                )
        except Exception:
            pass

        # ── Rate limiting (non-public paths only) ─────────────────────────────
        try:
            if not is_waf_exempt and rate_limit_hit(
                "global-ip", ip,
                limit=int(settings.global_rate_limit_max_requests or 300),
                window_seconds=int(settings.global_rate_limit_window_seconds or 60),
            ):
                await log_security_event(
                    "SECURITY_GLOBAL_RATE_LIMIT",
                    {"classification": "suspicious", "scope": "ip", "country": country},
                    ip=ip, path=path, method=request.method,
                    user_agent=user_agent, status_code=429, request_id=request_id,
                )
                return JSONResponse(status_code=429, content={"detail": "Rate limit exceeded"})

            if not is_waf_exempt and rate_limit_hit("burst-ip", ip, limit=60, window_seconds=5):
                return JSONResponse(status_code=429, content={"detail": "Burst limit exceeded"})

            api_key_fingerprint = fingerprint_key(
                request.headers.get("x-api-key")
                or request.headers.get("x-admin-api-key")
                or request.headers.get("authorization")
            )
            if api_key_fingerprint and not is_waf_exempt and rate_limit_hit("api-key", api_key_fingerprint, limit=200, window_seconds=60):
                return JSONResponse(status_code=429, content={"detail": "API usage limit exceeded"})
        except Exception:
            pass

        # ── Process request ───────────────────────────────────────────────────
        response = await call_next(request)

        # ── 404 scan scoring ──────────────────────────────────────────────────
        try:
            if request.method == "GET" and response.status_code == 404 and path not in {"/favicon.ico", "/robots.txt"}:
                add_risk_score(ip, 1, reason="404_scan", path=path)
        except Exception:
            pass

        # ── Security response headers ─────────────────────────────────────────
        try:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["X-Frame-Options"] = "DENY"
            response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; "
                "script-src 'self' 'unsafe-inline' 'unsafe-eval' "
                "https://cdnjs.cloudflare.com https://cdn.jsdelivr.net https://unpkg.com; "
                "style-src 'self' 'unsafe-inline'; "
                "img-src 'self' data: https:; "
                "font-src 'self' data:; "
                "connect-src 'self' https://api.coingecko.com https://api.qrserver.com "
                "https://*.infura.io https://*.alchemy.com "
                "https://ethereum.publicnode.com https://bsc.publicnode.com "
                "https://eth.drpc.org https://1rpc.io "
                "https://cloudflare-eth.com https://eth.llamarpc.com "
                "https://bsc-dataseed.binance.org https://bsc-dataseed1.binance.org "
                "https://data-seed-prebsc-1-s1.binance.org:8545; "
                "object-src 'none'; "
                "base-uri 'self'; "
                "frame-ancestors 'none';"
            )
            response.headers["X-Permitted-Cross-Domain-Policies"] = "none"
            response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
            if path in {"/", "/login", "/dashboard", "/dashboard/login", "/client", "/client/login", "/swift"}:
                response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive, nosnippet"
                response.headers["Cache-Control"] = "no-store"
            elif path.startswith("/static/") and path.endswith((".css", ".js", ".html")):
                response.headers["Cache-Control"] = "no-cache, must-revalidate"
            if "server" in response.headers:
                del response.headers["server"]
        except Exception:
            pass

        return response


app.add_middleware(SecurityHeadersMiddleware)


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


app.add_middleware(RequestContextMiddleware)
app.middleware("http")(audit_request_middleware)


app.mount("/static", StaticFiles(directory="app/static"), name="static")


# Core API
app.include_router(payments_router, prefix=settings.api_prefix)
app.include_router(coinbase_router, prefix=settings.api_prefix)
app.include_router(transactions_router, prefix=settings.api_prefix)
app.include_router(oauth_router, prefix=settings.api_prefix)

# Supporting API
app.include_router(fiat_router, prefix=settings.api_prefix)
app.include_router(crypto_router, prefix=settings.api_prefix)
app.include_router(treasury_router, prefix=settings.api_prefix)
app.include_router(admin_router, prefix=settings.api_prefix)
app.include_router(stripe_router, prefix=settings.api_prefix)
app.include_router(m1_funds_router, prefix=settings.api_prefix)

# ── Settlement pipeline (new) ────────────────────────────────────────────────
app.include_router(fnfcu_router, prefix=settings.api_prefix)
app.include_router(ingest_router, prefix=settings.api_prefix)
app.include_router(admin_payloads_router, prefix=settings.api_prefix)
app.include_router(settlement_webhooks_router, prefix=settings.api_prefix)
app.include_router(partner_dispatch_router, prefix=settings.api_prefix)

# Webhooks and public pages
app.include_router(webhooks_router)
app.include_router(public_router)
app.include_router(client_portal_router)

# Multi-page dashboard and client portal
app.include_router(dashboard_pages_router)
app.include_router(client_pages_router)

# Client-Admin Live Chat
app.include_router(chat_router)


@app.get("/support", include_in_schema=False)
async def client_chat_page():
    """Public client support chat page."""
    return FileResponse("app/static/chat_client.html")


def _receiver_openapi_schema() -> dict:
    routes = [
        route for route in app.routes
        if getattr(route, "include_in_schema", False)
        and str(getattr(route, "path", "")).startswith(settings.api_prefix)
        and not str(getattr(route, "path", "")).startswith(f"{settings.api_prefix}/admin")
    ]

    return get_openapi(
        title="ALSHUMOOKH Receiver API",
        version="2.0.0",
        description=(
            "Enterprise-style settlement receiver and operations API. "
            "Includes sender-facing settlement endpoints, webhook handling, treasury utilities, "
            "and protected administrative operations."
        ),
        routes=routes,
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    detail = exc.detail
    if isinstance(detail, dict):
        detail = safe_details(detail)
    if request.url.path.startswith(settings.api_prefix) or request.url.path.startswith("/receiver/"):
        return JSONResponse(status_code=exc.status_code, content={"detail": detail}, headers=exc.headers)
    return JSONResponse(status_code=exc.status_code, content={"detail": detail}, headers=exc.headers)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled error on path %s", request.url.path)
    await log_security_event(
        "SECURITY_UNHANDLED_EXCEPTION",
        {
            "classification": "error",
            "path": request.url.path,
            "country": getattr(request.state, "geo_country", None),
        },
        ip=_get_client_ip(request),
        path=request.url.path,
        method=request.method,
        user_agent=str(request.headers.get("user-agent") or ""),
        status_code=500,
        request_id=getattr(request.state, "request_id", None),
        error_message=type(exc).__name__,
    )
    if request.url.path.startswith(settings.api_prefix) or request.url.path.startswith("/receiver/"):
        if request.url.path.startswith(f"{settings.api_prefix}/admin/stripe"):
            return JSONResponse(
                status_code=500,
                content={"detail": f"Stripe endpoint error: {type(exc).__name__}: {str(exc)[:300]}"},
            )
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"},
        )
    return HTMLResponse("<h1>Internal server error</h1>", status_code=500)


def login_page(error: str | None = None, mode: str = "client") -> HTMLResponse:
    error_html = f'<div class="error">{error}</div>' if error else ""

    html = """<!doctype html>
<html lang="ar" dir="rtl">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>ALSHUMOOKH — تسجيل الدخول</title>
  <link rel="icon" type="image/png" href="/favicon.ico">
  <link rel="apple-touch-icon" href="/apple-touch-icon.png">
  <style>
    :root {
      --bg:#eef2f6;
      --ink:#111827;
      --muted:#667085;
      --line:#d8e0ea;
      --brand:#1f5fd0;
      --brand-dark:#17479c;
      --gold:#c79a45;
      --bad:#b83232;
      --ok:#0f8a5f;
      --shadow:0 24px 80px rgba(15,23,42,.14);
    }

    * { box-sizing:border-box; }

    body {
      min-height:100vh;
      margin:0;
      font-family:Arial,Tahoma,sans-serif;
      color:var(--ink);
      background:linear-gradient(180deg,#f8fafc,var(--bg));
    }

    .shell {
      min-height:100vh;
      display:grid;
      grid-template-columns:minmax(360px,440px) minmax(0,1fr);
    }

    .brand-side {
      display:flex;
      flex-direction:column;
      justify-content:space-between;
      padding:34px;
      color:white;
      background:linear-gradient(180deg,#172232,#0e1621);
    }

    .lang-toggle {
      display:flex;
      justify-content:flex-end;
      margin-bottom:18px;
    }

    .lang-btn {
      background:rgba(255,255,255,.10);
      border:1px solid rgba(255,255,255,.20);
      color:#d6b46c;
      border-radius:6px;
      padding:5px 12px;
      font-size:12px;
      font-weight:900;
      cursor:pointer;
    }

    .lang-btn:hover { background:rgba(255,255,255,.18); }

    .brand-row {
      display:flex;
      gap:16px;
      align-items:center;
    }

    .brand-row img {
      width:88px;
      height:70px;
      object-fit:contain;
      border:1px solid rgba(199,154,69,.32);
      border-radius:8px;
      padding:7px;
      background:#05070a;
    }

    .brand-mark {
      width:70px;
      height:70px;
      display:none;
      place-items:center;
      border-radius:8px;
      background:var(--gold);
      color:#111820;
      font-weight:900;
    }

    .eyebrow {
      margin:0 0 8px;
      color:#d6b46c;
      font-size:12px;
      font-weight:900;
      text-transform:uppercase;
    }

    .brand-side h1 {
      margin:28px 0 14px;
      font-size:34px;
      line-height:1.18;
    }

    .brand-side p {
      margin:0;
      color:#b9c6d8;
      line-height:1.75;
    }

    .section-label {
      margin:24px 0 10px;
      color:#d6b46c;
      font-size:12px;
      font-weight:900;
      text-transform:uppercase;
      letter-spacing:.06em;
    }

    .feature-grid {
      display:grid;
      grid-template-columns:1fr 1fr;
      gap:10px;
    }

    .feature {
      min-height:82px;
      padding:13px;
      border:1px solid rgba(255,255,255,.10);
      border-radius:8px;
      background:rgba(255,255,255,.045);
    }

    .feature strong {
      display:block;
      margin-bottom:5px;
      color:white;
    }

    .feature span {
      color:#9fb0c6;
      font-size:12px;
      line-height:1.5;
    }

    .pay-icons {
      display:flex;
      flex-wrap:wrap;
      gap:8px;
      margin-top:22px;
    }

    .pay-icons span {
      min-height:34px;
      display:inline-flex;
      align-items:center;
      gap:7px;
      padding:7px 10px;
      border:1px solid rgba(199,154,69,.28);
      border-radius:8px;
      color:#f4d48b;
      background:rgba(199,154,69,.10);
      font-size:12px;
      font-weight:900;
    }

    .pay-icons b {
      display:grid;
      place-items:center;
      width:20px;
      height:20px;
      border-radius:6px;
      background:#f4d48b;
      color:#111820;
      font-size:11px;
    }

    .brand-foot {
      color:#8fa0b6;
      font-size:12px;
      line-height:1.6;
    }

    .login-area {
      display:grid;
      place-items:center;
      padding:34px;
    }

    .box {
      width:min(760px,100%);
      padding:26px;
      border:1px solid var(--line);
      border-radius:8px;
      background:white;
      box-shadow:var(--shadow);
    }

    .box-top {
      display:flex;
      justify-content:space-between;
      align-items:center;
      margin-bottom:6px;
    }

    .brand-label {
      color:var(--gold);
      font-size:12px;
      font-weight:900;
      text-transform:uppercase;
    }

    .lang-btn-box {
      background:#f0f5ff;
      border:1px solid var(--line);
      color:var(--brand);
      border-radius:6px;
      padding:4px 11px;
      font-size:12px;
      font-weight:900;
      cursor:pointer;
      margin-top:0;
      min-height:auto;
    }

    .box h2 {
      margin:8px 0 8px;
      font-size:28px;
    }

    .box p {
      margin:0 0 18px;
      color:var(--muted);
      line-height:1.6;
    }

    .tabs {
      display:grid;
      grid-template-columns:1fr 1fr;
      gap:8px;
      margin:18px 0;
      padding:5px;
      border:1px solid var(--line);
      border-radius:8px;
      background:#f8fafc;
    }

    .tabs button {
      margin:0;
      min-height:38px;
      background:transparent;
      color:var(--ink);
      border:none;
    }

    .tabs button.active {
      background:var(--brand);
      color:white;
    }

    .form-grid {
      display:grid;
      grid-template-columns:1fr;
      gap:13px;
    }

    label {
      display:grid;
      gap:8px;
      color:var(--muted);
      font-size:13px;
      font-weight:800;
    }

    input {
      min-height:44px;
      border:1px solid var(--line);
      border-radius:7px;
      padding:10px 12px;
      font:inherit;
      direction:ltr;
      text-align:left;
    }

    input:focus {
      border-color:var(--brand);
      outline:0;
      box-shadow:0 0 0 3px rgba(31,95,208,.12);
    }

    button {
      width:100%;
      min-height:44px;
      margin-top:14px;
      border:1px solid var(--brand);
      border-radius:7px;
      background:var(--brand);
      color:white;
      font-weight:900;
      cursor:pointer;
    }

    button:hover {
      background:var(--brand-dark);
    }

    .muted-button {
      border-color:#c7d2df;
      background:#f8fbff;
      color:var(--brand-dark);
    }

    .muted-button:hover {
      background:#eef5ff;
    }

    .split-actions {
      display:grid;
      grid-template-columns:1fr 1fr;
      gap:10px;
    }

    .error {
      margin:0 0 14px;
      padding:10px 12px;
      border-radius:7px;
      color:var(--bad);
      background:#fff0f0;
      font-weight:800;
    }

    .hidden {
      display:none !important;
    }

    .message {
      min-height:22px;
      color:var(--muted);
      font-weight:800;
    }

    .message.bad { color:var(--bad); }
    .message.ok  { color:var(--ok); }

    .forgot-link {
      display:block;
      margin-top:10px;
      font-size:12px;
      color:var(--brand);
      text-align:center;
      cursor:pointer;
      text-decoration:underline;
    }

    .info-box {
      margin-top:12px;
      padding:10px 14px;
      border-radius:7px;
      border:1px solid #b8d2ff;
      background:#eef5ff;
      color:var(--brand-dark);
      font-size:13px;
      line-height:1.6;
    }

    .rate-warning {
      padding:10px 12px;
      border-radius:7px;
      color:#7a4000;
      background:#fff3e0;
      border:1px solid #ffe0a0;
      font-weight:800;
      font-size:13px;
    }

    @media (max-width:920px) {
      .shell { grid-template-columns:1fr; }
      .brand-side { min-height:auto; }
      .brand-side h1 { font-size:31px; }
    }

    @media (max-width:620px) {
      .brand-side, .login-area { padding:20px; }
      .feature-grid, .split-actions { grid-template-columns:1fr; }
      .box { padding:20px; }
    }
  </style>
</head>

<body>
  <main class="shell">
    <aside class="brand-side">
      <div>
        <div class="lang-toggle">
          <button class="lang-btn" onclick="toggleLang()" id="sideLangBtn">EN</button>
        </div>

        <div class="brand-row">
          <img
            src="/static/company-logo.png"
            alt="ALSHUMOOKH Logo"
            onerror="this.style.display='none';this.nextElementSibling.style.display='grid';"
          >
          <div class="brand-mark">AS</div>

          <div>
            <p class="eyebrow">ALSHUMOOKH GLOBAL</p>
            <strong>Banking Finance &amp; Credit</strong>
          </div>
        </div>

        <h1 id="sideTitle">بوابة دفع آمنة لإنشاء روابط الدفع</h1>
        <p id="sideSubtitle">
          أنشئ روابط دفع (Crypto) أو عبر (MoonPay) وتابع جميع معاملاتك بشكل آمن وبدون مشاركة أي بيانات حساسة.
        </p>

        <p class="section-label" id="chooseLabel">اختر طريقة الدفع المناسبة لإنشاء رابط جديد</p>

        <div class="feature-grid">
          <div class="feature">
            <strong>Admin</strong>
            <span id="adminFeatureText">لوحة تحكم لإدارة النظام والعمليات والتقارير.</span>
          </div>
          <div class="feature">
            <strong>Client</strong>
            <span id="clientFeatureText">إنشاء روابط الدفع ومتابعة العمليات الخاصة بك.</span>
          </div>
          <div class="feature">
            <strong>Security</strong>
            <span id="securityFeatureText">جلسات منفصلة، تسجيل العمليات، وحماية للبيانات الحساسة.</span>
          </div>
          <div class="feature">
            <strong>Payments</strong>
            <span id="paymentsFeatureText">MoonPay Commerce، التحويلات، وبطاقات الدفع.</span>
          </div>
        </div>

        <div class="pay-icons">
          <span><b>V</b> Visa</span>
          <span><b>M</b> Mastercard</span>
          <span><b>S</b> SEPA</span>
          <span><b>B</b> Bank Transfer</span>
          <span><b>C</b> Crypto</span>
        </div>
      </div>

      <div class="brand-foot">
        ALSHUMOOKH GLOBAL BANKING FINANCE &amp; CREDIT<br>
        <span id="footText">بوابة دفع آمنة ومحمية</span>
      </div>
    </aside>

    <section class="login-area">
      <div class="box">
        <div class="box-top">
          <div class="brand-label" id="secureLabel">Secure Login</div>
          <button class="lang-btn-box" onclick="toggleLang()" id="boxLangBtn">EN</button>
        </div>

        <h2 id="title">تسجيل الدخول</h2>
        <p id="subtitle">العميل يدخل بالإيميل أو رقم الهاتف مع كلمة المرور.</p>
        __ERROR_HTML__

        <div class="tabs">
          <button id="clientTab" class="active" type="button" onclick="showMode('client')" data-ar="دخول العميل" data-en="Client Login">دخول العميل</button>
          <button id="adminTab" type="button" onclick="showMode('admin')" data-ar="دخول الإدارة" data-en="Admin Login">دخول الإدارة</button>
        </div>

        <form id="adminForm" class="form-grid hidden" method="post" action="/dashboard/login">
          <label id="adminKeyLabel">Admin API Key
            <input name="admin_key" type="password" autocomplete="current-password">
          </label>
          <button type="submit" id="adminSubmitBtn">فتح لوحة الإدارة</button>
        </form>

        <form id="clientForm" class="form-grid">
          <label id="identifierLabel">الإيميل أو رقم الهاتف
            <input name="identifier" autocomplete="username" placeholder="client@example.com أو +971..." required>
          </label>

          <label id="passwordLabel">كلمة المرور
            <input name="password" type="password" autocomplete="current-password" minlength="6" required>
          </label>

          <div class="split-actions">
            <button id="clientLoginBtn" type="submit">تسجيل الدخول</button>
            <button id="clientRegisterBtn" class="muted-button" type="button">فتح حساب جديد</button>
          </div>

          <span class="forgot-link" id="forgotLink" onclick="showForgot()">نسيت كلمة المرور؟</span>

          <div id="forgotBox" class="info-box hidden">
            <strong id="forgotTitle">استعادة كلمة المرور</strong><br>
            <span id="forgotText">يرجى التواصل مع الإدارة عبر البريد الإلكتروني أو قناة الدعم لإعادة تعيين كلمة المرور. سيتم إضافة إعادة التعيين التلقائي قريباً.</span>
          </div>

          <div id="clientMessage" class="message"></div>
        </form>
      </div>
    </section>
  </main>

  <script>
    // ── Language Toggle ─────────────────────────────────────────────────────
    const STRINGS = {
      ar: {
        title: 'تسجيل الدخول',
        subtitle: 'العميل يدخل بالإيميل أو رقم الهاتف مع كلمة المرور.',
        sideTitle: 'بوابة دفع آمنة لإنشاء روابط الدفع',
        sideSubtitle: 'أنشئ روابط دفع (Crypto) أو عبر (MoonPay) وتابع جميع معاملاتك بشكل آمن وبدون مشاركة أي بيانات حساسة.',
        chooseLabel: 'اختر طريقة الدفع المناسبة لإنشاء رابط جديد',
        adminFeature: 'لوحة تحكم لإدارة النظام والعمليات والتقارير.',
        clientFeature: 'إنشاء روابط الدفع ومتابعة العمليات الخاصة بك.',
        securityFeature: 'جلسات منفصلة، تسجيل العمليات، وحماية للبيانات الحساسة.',
        paymentsFeature: 'MoonPay Commerce، التحويلات، وبطاقات الدفع.',
        footText: 'بوابة دفع آمنة ومحمية',
        identifierLabel: 'الإيميل أو رقم الهاتف',
        passwordLabel: 'كلمة المرور',
        loginBtn: 'تسجيل الدخول',
        registerBtn: 'فتح حساب جديد',
        forgotLink: 'نسيت كلمة المرور؟',
        forgotTitle: 'استعادة كلمة المرور',
        forgotText: 'يرجى التواصل مع الإدارة عبر البريد الإلكتروني أو قناة الدعم لإعادة تعيين كلمة المرور.',
        adminSubmit: 'فتح لوحة الإدارة',
        secureLabel: 'Secure Login',
        langBtn: 'EN',
        adminTitle: 'دخول الإدارة',
        adminSubtitle: 'الإدارة تدخل بمفتاح Admin API Key.',
        clientTitleMode: 'تسجيل الدخول',
        clientSubtitleMode: 'العميل يدخل بالإيميل أو رقم الهاتف مع كلمة المرور.',
      },
      en: {
        title: 'Login',
        subtitle: 'Enter your email or phone number and password.',
        sideTitle: 'Secure Payment Gateway',
        sideSubtitle: 'Create Crypto payment links or via MoonPay, and track all your transactions securely without sharing sensitive data.',
        chooseLabel: 'Choose the appropriate payment method to create a new link',
        adminFeature: 'Full system control — orders, logs, documents, and reports.',
        clientFeature: 'Create payment links and track your own transactions.',
        securityFeature: 'Separate sessions, event logging, and sensitive data protection.',
        paymentsFeature: 'MoonPay Commerce, transfers, and payment cards.',
        footText: 'Secure & Protected Payment Gateway',
        identifierLabel: 'Email or Phone Number',
        passwordLabel: 'Password',
        loginBtn: 'Login',
        registerBtn: 'Create Account',
        forgotLink: 'Forgot password?',
        forgotTitle: 'Password Recovery',
        forgotText: 'Please contact the admin via email or support channel to reset your password.',
        adminSubmit: 'Open Admin Dashboard',
        secureLabel: 'Secure Login',
        langBtn: 'عربي',
        adminTitle: 'Admin Login',
        adminSubtitle: 'Admin enters the Admin API Key.',
        clientTitleMode: 'Login',
        clientSubtitleMode: 'Enter your email or phone number and password.',
      }
    };

    let currentLang = localStorage.getItem('als_lang') || 'ar';
    let currentMode = 'client';

    function applyLang(lang) {
      const s = STRINGS[lang];
      const isRtl = lang === 'ar';
      document.documentElement.lang = lang;
      document.documentElement.dir = isRtl ? 'rtl' : 'ltr';

      document.getElementById('sideTitle').textContent = s.sideTitle;
      document.getElementById('sideSubtitle').textContent = s.sideSubtitle;
      document.getElementById('chooseLabel').textContent = s.chooseLabel;
      document.getElementById('adminFeatureText').textContent = s.adminFeature;
      document.getElementById('clientFeatureText').textContent = s.clientFeature;
      document.getElementById('securityFeatureText').textContent = s.securityFeature;
      document.getElementById('paymentsFeatureText').textContent = s.paymentsFeature;
      document.getElementById('footText').textContent = s.footText;
      document.getElementById('identifierLabel').childNodes[0].textContent = s.identifierLabel + ' ';
      document.getElementById('passwordLabel').childNodes[0].textContent = s.passwordLabel + ' ';
      document.getElementById('clientLoginBtn').textContent = s.loginBtn;
      document.getElementById('clientRegisterBtn').textContent = s.registerBtn;
      document.getElementById('forgotLink').textContent = s.forgotLink;
      document.getElementById('forgotTitle').textContent = s.forgotTitle;
      document.getElementById('forgotText').textContent = s.forgotText;
      document.getElementById('adminSubmitBtn').textContent = s.adminSubmit;
      document.getElementById('secureLabel').textContent = s.secureLabel;
      if (document.getElementById('sideLangBtn')) document.getElementById('sideLangBtn').textContent = s.langBtn;
      document.getElementById('boxLangBtn').textContent = s.langBtn;

      // Tab labels
      document.getElementById('clientTab').textContent = lang === 'ar' ? 'دخول العميل' : 'Client Login';
      document.getElementById('adminTab').textContent = lang === 'ar' ? 'دخول الإدارة' : 'Admin Login';

      // Update mode-specific title/subtitle
      if (currentMode === 'admin') {
        document.getElementById('title').textContent = s.adminTitle;
        document.getElementById('subtitle').textContent = s.adminSubtitle;
      } else {
        document.getElementById('title').textContent = s.clientTitleMode;
        document.getElementById('subtitle').textContent = s.clientSubtitleMode;
      }
    }

    function toggleLang() {
      currentLang = currentLang === 'ar' ? 'en' : 'ar';
      localStorage.setItem('als_lang', currentLang);
      applyLang(currentLang);
    }

    // ── Mode Toggle ─────────────────────────────────────────────────────────
    function showMode(mode) {
      currentMode = mode;
      const isAdmin = mode === 'admin';
      const s = STRINGS[currentLang];

      document.getElementById('adminTab').classList.toggle('active', isAdmin);
      document.getElementById('clientTab').classList.toggle('active', !isAdmin);
      document.getElementById('adminForm').classList.toggle('hidden', !isAdmin);
      document.getElementById('clientForm').classList.toggle('hidden', isAdmin);

      document.getElementById('title').textContent = isAdmin ? s.adminTitle : s.clientTitleMode;
      document.getElementById('subtitle').textContent = isAdmin ? s.adminSubtitle : s.clientSubtitleMode;

      document.getElementById('clientMessage').textContent = '';
      document.getElementById('clientMessage').className = 'message';
      document.getElementById('forgotBox').classList.add('hidden');
    }

    // ── Forgot Password ─────────────────────────────────────────────────────
    function showForgot() {
      document.getElementById('forgotBox').classList.toggle('hidden');
    }

    // ── Client Auth ─────────────────────────────────────────────────────────
    async function clientAuth(path) {
      const formData = new FormData(document.getElementById('clientForm'));
      const msg = document.getElementById('clientMessage');

      msg.textContent = currentLang === 'ar' ? 'جاري التحقق...' : 'Verifying...';
      msg.className = 'message';

      const response = await fetch(path, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          identifier: formData.get('identifier'),
          password: formData.get('password'),
        }),
      });

      const text = await response.text();
      const data = text ? JSON.parse(text) : {};

      if (!response.ok) {
        throw new Error(data.detail || text || 'HTTP ' + response.status);
      }

      window.location.href = '/client';
    }

    document.getElementById('clientForm').addEventListener('submit', async function (event) {
      event.preventDefault();
      try {
        await clientAuth('/client/login');
      } catch (error) {
        const msg = document.getElementById('clientMessage');
        msg.textContent = error.message;
        msg.className = 'message bad';
      }
    });

    document.getElementById('clientRegisterBtn').addEventListener('click', async function () {
      try {
        await clientAuth('/client/register');
      } catch (error) {
        const msg = document.getElementById('clientMessage');
        msg.textContent = error.message;
        msg.className = 'message bad';
      }
    });

    // ── Init ────────────────────────────────────────────────────────────────
    applyLang(currentLang);

    const params = new URLSearchParams(window.location.search);
    const serverMode = '__MODE__';
    showMode(params.get('type') === 'admin' || serverMode === 'admin' ? 'admin' : 'client');
  </script>
</body>
</html>"""

    html = html.replace("__ERROR_HTML__", error_html)
    html = html.replace("__MODE__", mode)

    return HTMLResponse(html)


@app.get("/login", response_class=HTMLResponse, tags=["auth"])
async def unified_login():
    return login_page()


@app.get("/dashboard/login", tags=["dashboard"])
async def dashboard_login():
    return RedirectResponse("/login?type=admin", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/dashboard/login", tags=["dashboard"])
async def dashboard_login_submit(request: Request, admin_key: str = Form(...)):
    ip = _get_client_ip(request)
    guard = login_guard(ip)

    if guard["is_locked"]:
        await log_security_event(
            "SECURITY_ADMIN_LOGIN_LOCKED",
            {
                "classification": "blocked",
                "lock_seconds": guard["lock_seconds"],
                "captcha_ready": guard["captcha_ready"],
            },
            ip=ip,
            path="/dashboard/login",
            method="POST",
            user_agent=str(request.headers.get("user-agent") or ""),
            status_code=429,
            request_id=getattr(request.state, "request_id", None),
        )
        return login_page(
            f"تم قفل هذا العنوان مؤقتاً. حاول بعد {guard['lock_seconds']} ثانية.",
            mode="admin",
        )

    if guard["is_backoff"]:
        return login_page(
            f"يرجى الانتظار {guard['backoff_seconds']} ثانية قبل المحاولة التالية.",
            mode="admin",
        )

    expected_key = str(settings.admin_api_key or "")
    received_key = str(admin_key or "")

    if not received_key or not hmac.compare_digest(received_key, expected_key):
        failure = register_failed_login(ip)
        await log_security_event(
            "SECURITY_ADMIN_LOGIN_FAILED",
            {
                "classification": "suspicious",
                "failed_attempts": failure["failed_attempts"],
                "backoff_seconds": failure["backoff_seconds"],
                "captcha_ready": failure["captcha_ready"],
            },
            ip=ip,
            path="/dashboard/login",
            method="POST",
            user_agent=str(request.headers.get("user-agent") or ""),
            status_code=401,
            request_id=getattr(request.state, "request_id", None),
        )
        logger.warning("Admin login FAILED — IP: %s", ip)
        return login_page("مفتاح الإدارة غير صحيح. يمكن المحاولة مرة أخرى.", mode="admin")

    clear_login_failures(ip)
    clear_security_state(ip)
    logger.info("Admin login SUCCESS — IP: %s", ip)

    response = RedirectResponse("/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(
        ADMIN_SESSION_COOKIE,
        create_admin_session_token(request),
        max_age=ADMIN_SESSION_MAX_AGE,
        httponly=True,
        secure=_is_secure_cookie_context(),
        samesite="lax",
        path="/",
    )
    return response


@app.get("/dashboard/legacy", tags=["dashboard"])
async def dashboard_legacy(request: Request):
    """Old single-page dashboard — kept for reference."""
    if not is_admin_request_authenticated(request):
        return RedirectResponse("/login?type=admin", status_code=status.HTTP_303_SEE_OTHER)
    return FileResponse("app/static/dashboard.html")


@app.get("/swift", tags=["dashboard"])
async def swift_terminal(request: Request):
    if not is_admin_request_authenticated(request):
        return RedirectResponse("/login?type=admin", status_code=status.HTTP_303_SEE_OTHER)

    return FileResponse("app/static/swift.html")


@app.get("/health", tags=["system"])
async def health(request: Request):
    return {"status": "ok"}


@app.get("/ready", tags=["system"])
async def ready(request: Request):
    return {"status": "ready"}


@app.get("/version", tags=["system"])
async def version():
    return {
        "app": settings.app_name,
        "environment": settings.app_env,
        "commit": (
            os.getenv("RENDER_GIT_COMMIT")
            or os.getenv("GIT_COMMIT")
            or os.getenv("COMMIT_SHA")
            or "unknown"
        ),
        "started_at": APP_STARTED_AT,
    }


@app.get("/internal/health", include_in_schema=False)
async def internal_health(request: Request):
    if not _is_health_authorized(request):
        return Response(status_code=404)
    return {"status": "ok", "scope": "internal"}


@app.get("/.env.bak", include_in_schema=False)
@app.get("/wp-admin/install.php", include_in_schema=False)
@app.get("/adminer.php", include_in_schema=False)
@app.get("/phpinfo.php", include_in_schema=False)
@app.get("/backup.zip", include_in_schema=False)
async def honeypot(request: Request):
    ip = _get_client_ip(request)
    path = request.url.path
    add_risk_score(ip, 8, reason="honeypot", path=path)
    ban_ip(ip)
    await log_security_event(
        "SECURITY_HONEYPOT_TRIGGERED",
        {
            "classification": "scanner",
            "path": path,
            "country": getattr(request.state, "geo_country", None),
        },
        ip=ip,
        path=path,
        method=request.method,
        user_agent=str(request.headers.get("user-agent") or ""),
        status_code=404,
        request_id=getattr(request.state, "request_id", None),
    )
    return Response(status_code=404)


@app.get("/receiver/openapi.json", include_in_schema=False)
async def receiver_openapi():
    return JSONResponse(_receiver_openapi_schema())


@app.get("/receiver/docs", include_in_schema=False)
async def receiver_docs():
    return get_swagger_ui_html(
        openapi_url="/receiver/openapi.json",
        title="ALSHUMOOKH Receiver API Docs",
        swagger_favicon_url="/favicon.ico",
    )


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return FileResponse("app/static/company-logo.png", media_type="image/png")


@app.get("/favicon.png", include_in_schema=False)
async def favicon_png():
    return FileResponse("app/static/company-logo.png", media_type="image/png")


@app.get("/apple-touch-icon.png", include_in_schema=False)
async def apple_touch_icon():
    return FileResponse("app/static/company-logo.png", media_type="image/png")


@app.get("/apple-touch-icon-precomposed.png", include_in_schema=False)
async def apple_touch_icon_precomposed():
    return FileResponse("app/static/company-logo.png", media_type="image/png")


@app.get("/robots.txt", include_in_schema=False)
async def robots_txt():
    content = """User-agent: *
Disallow: /

# Private financial system - indexing is not permitted.
"""
    return Response(content=content, media_type="text/plain; charset=utf-8")


@app.get("/.well-known/security.txt", include_in_schema=False)
async def well_known_security_txt():
    content = """Contact: mailto:ceo@alshumookhgroup.ae
Expires: 2027-05-11T00:00:00.000Z
Preferred-Languages: ar, en
Policy: https://api.alshumookh-pay.com/login
Canonical: https://api.alshumookh-pay.com/.well-known/security.txt
"""
    return Response(content=content, media_type="text/plain; charset=utf-8")


@app.get("/security.txt", include_in_schema=False)
async def security_txt():
    return await well_known_security_txt()


@app.head("/", tags=["system"])
async def root_head():
    return Response(status_code=200)


@app.get("/", tags=["system"])
async def root():
    """Redirect root to login page — avoids exposing API info publicly."""
    return RedirectResponse("/login", status_code=status.HTTP_302_FOUND)
