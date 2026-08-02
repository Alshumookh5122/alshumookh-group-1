from __future__ import annotations

import hmac
import time

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit_service import log_event
from app.auth import (
    create_settlement_access_token,
    hash_api_key,
    hash_oauth_secret,
)
from app.config import get_settings
from app.database import get_db
from app.models import ApiClient
from app.request_utils import get_client_ip

router = APIRouter(prefix="/oauth", tags=["settlement-oauth"])
settings = get_settings()

@router.post("/token")
async def token(
    request: Request,
    grant_type: str = Form(...),
    client_id: str = Form(...),
    client_secret: str = Form(...),
    scope: str | None = Form(default="settlement:ingest"),
    db: AsyncSession = Depends(get_db),
):
    """
    OAuth2 Client Credentials endpoint for institutional counterparties.

    Existing X-API-Key integrations continue to work. Counterparties that
    require OAuth2 can request a short-lived bearer token here and use it on
    POST /api/v1/payloads/ingest.
    """
    if grant_type != "client_credentials":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "unsupported_grant_type"},
        )

    client_id_hash = hash_api_key(client_id)
    result = await db.execute(
        select(ApiClient).where(ApiClient.oauth_client_id_hash == client_id_hash)
    )
    client = result.scalar_one_or_none()

    if (
        not client
        or not client.is_active
        or not client.oauth_client_secret_hash
        or not hmac.compare_digest(hash_oauth_secret(client_secret), client.oauth_client_secret_hash)
    ):
        await log_event(
            db,
            "OAUTH_TOKEN_FAILED",
            {"client_id_prefix": client_id[:12], "ip": get_client_ip(request)},
            None,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "invalid_client"},
        )

    scopes = [item for item in str(scope or "settlement:ingest").split() if item]
    if "settlement:ingest" not in scopes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "invalid_scope", "required": "settlement:ingest"},
        )

    token_value = create_settlement_access_token(client, scopes=scopes)
    await log_event(
        db,
        "OAUTH_TOKEN_ISSUED",
        {
            "client_id": str(client.id),
            "client_name": client.name,
            "scope": " ".join(scopes),
            "ip": get_client_ip(request),
        },
        None,
        client_id=client.id,
    )

    return {
        "access_token": token_value,
        "token_type": "Bearer",
        "expires_in": max(60, int(settings.settlement_oauth_token_ttl_seconds or 900)),
        "scope": " ".join(scopes),
        "issued_at": int(time.time()),
    }
