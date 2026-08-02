import hashlib
import hmac
import secrets
import time
from typing import Any

import jwt
from fastapi import Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.config import get_settings
from app.models import ApiClient
from app.request_utils import get_client_ip

ADMIN_SESSION_COOKIE = 'asg_admin_session'
ADMIN_SESSION_MAX_AGE = 60 * 60 * 12
CLIENT_SESSION_COOKIE = 'asg_client_session'
CLIENT_SESSION_MAX_AGE = 60 * 60 * 24 * 7
PASSWORD_ITERATIONS = 120_000


def _request_ip(request: Request) -> str | None:
    return get_client_ip(request)


def _csv_values(value: str | None) -> list[str]:
    if not value:
        return []

    return [item.strip() for item in value.split(',') if item.strip()]


def _admin_serializer() -> URLSafeTimedSerializer:
    settings = get_settings()
    secret = str(settings.admin_api_key or '')
    return URLSafeTimedSerializer(secret_key=secret, salt='asg-admin-session')


def _client_serializer() -> URLSafeTimedSerializer:
    settings = get_settings()
    secret = str(settings.admin_api_key or '')
    return URLSafeTimedSerializer(secret_key=secret, salt='asg-client-session')


def create_admin_session_token(request: Request) -> str:
    return _admin_serializer().dumps(
        {
            'scope': 'admin',
            'ip': _request_ip(request),
        }
    )


def verify_admin_session_token(token: str | None, request: Request) -> bool:
    if not token:
        return False

    try:
        data = _admin_serializer().loads(token, max_age=ADMIN_SESSION_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return False

    if data.get('scope') != 'admin':
        return False

    settings = get_settings()
    allowed_ips = _csv_values(getattr(settings, 'admin_allowed_ips', None))
    request_ip = _request_ip(request)

    if allowed_ips and request_ip not in allowed_ips:
        return False

    return True


def is_admin_request_authenticated(request: Request) -> bool:
    session_token = request.cookies.get(ADMIN_SESSION_COOKIE)
    if verify_admin_session_token(session_token, request):
        return True

    settings = get_settings()
    expected_key = str(settings.admin_api_key or '')
    cookie_key = str(request.cookies.get('als_ak') or '')
    if expected_key and cookie_key and hmac.compare_digest(cookie_key, expected_key):
        allowed_ips = _csv_values(getattr(settings, 'admin_allowed_ips', None))
        request_ip = _request_ip(request)
        if allowed_ips and request_ip not in allowed_ips:
            return False
        return True

    return False


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        'sha256',
        password.encode('utf-8'),
        salt.encode('utf-8'),
        PASSWORD_ITERATIONS,
    ).hex()
    return f'pbkdf2_sha256${PASSWORD_ITERATIONS}${salt}${digest}'


def verify_password(password: str, stored_hash: str | None) -> bool:
    if not stored_hash:
        return False

    try:
        algorithm, iterations_text, salt, digest = stored_hash.split('$', 3)
        iterations = int(iterations_text)
    except ValueError:
        return False

    if algorithm != 'pbkdf2_sha256':
        return False

    expected = hashlib.pbkdf2_hmac(
        'sha256',
        password.encode('utf-8'),
        salt.encode('utf-8'),
        iterations,
    ).hex()
    return hmac.compare_digest(expected, digest)


def create_client_session_token(account_id: str, api_client_id: str, request: Request) -> str:
    return _client_serializer().dumps(
        {
            'scope': 'client',
            'account_id': account_id,
            'api_client_id': api_client_id,
            'ip': _request_ip(request),
        }
    )


def get_client_session_payload(request: Request) -> dict[str, Any] | None:
    token = request.cookies.get(CLIENT_SESSION_COOKIE)

    if not token:
        return None

    try:
        data = _client_serializer().loads(token, max_age=CLIENT_SESSION_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None

    if data.get('scope') != 'client':
        return None

    if not data.get('account_id') or not data.get('api_client_id'):
        return None

    return data


async def require_admin_api_key(
    request: Request,
    x_admin_api_key: str | None = Header(default=None),
) -> str:
    settings = get_settings()

    expected_key = str(settings.admin_api_key or '')
    received_key = str(x_admin_api_key or '')
    cookie_key = str(request.cookies.get('als_ak') or '')

    header_is_valid = bool(received_key) and hmac.compare_digest(received_key, expected_key)
    cookie_key_is_valid = bool(cookie_key) and hmac.compare_digest(cookie_key, expected_key)
    session_is_valid = is_admin_request_authenticated(request)

    if not header_is_valid and not cookie_key_is_valid and not session_is_valid:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Unauthorized')

    allowed_ips = _csv_values(getattr(settings, 'admin_allowed_ips', None))
    request_ip = _request_ip(request)

    if allowed_ips and request_ip not in allowed_ips:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Unauthorized')

    request.state.admin_authenticated = True
    request.state.admin_ip = request_ip
    return x_admin_api_key or ('admin-cookie-key' if cookie_key_is_valid else 'admin-session')


def create_api_key() -> str:
    return f'asgbfc_{secrets.token_urlsafe(32)}'


def create_oauth_client_id() -> str:
    return f'asg_oauth_{secrets.token_urlsafe(24)}'


def create_oauth_client_secret() -> str:
    return f'asg_secret_{secrets.token_urlsafe(40)}'


def create_hmac_secret() -> str:
    return secrets.token_urlsafe(48)


def hash_api_key(api_key: str) -> str:
    return hashlib.sha256(api_key.encode('utf-8')).hexdigest()


def hash_oauth_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode('utf-8')).hexdigest()


def create_settlement_access_token(client: ApiClient, scopes: list[str] | None = None) -> str:
    settings = get_settings()
    now = int(time.time())
    ttl = max(60, int(getattr(settings, "settlement_oauth_token_ttl_seconds", 900) or 900))
    payload = {
        "iss": settings.settlement_oauth_issuer,
        "aud": settings.settlement_oauth_audience,
        "sub": str(client.id),
        "client_name": client.name,
        "scope": " ".join(scopes or ["settlement:ingest"]),
        "iat": now,
        "exp": now + ttl,
    }
    return jwt.encode(payload, str(settings.admin_api_key), algorithm="HS256")


def verify_settlement_access_token(token: str) -> dict[str, Any]:
    settings = get_settings()
    try:
        data = jwt.decode(
            token,
            str(settings.admin_api_key),
            algorithms=["HS256"],
            audience=settings.settlement_oauth_audience,
            issuer=settings.settlement_oauth_issuer,
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "invalid_bearer_token", "message": "Bearer token is invalid or expired"},
        ) from exc

    scope_text = str(data.get("scope") or "")
    if "settlement:ingest" not in scope_text.split():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "insufficient_scope", "message": "Token is missing settlement:ingest scope"},
        )
    return data


async def require_client_api_key(
    request: Request,
    db: AsyncSession,
    x_api_key: str | None = Header(default=None),
) -> ApiClient:
    if not x_api_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Missing API key')

    result = await db.execute(select(ApiClient).where(ApiClient.api_key_hash == hash_api_key(x_api_key)))
    client = result.scalar_one_or_none()
    if not client or not client.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Invalid API key')

    request_ip = _request_ip(request)
    if client.allowed_ips and request_ip not in client.allowed_ips:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='IP address is not allowed')

    request.state.client_id = client.id
    request.state.client_name = client.name
    return client
