from typing import Annotated
from fastapi import Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession
from app.auth import require_admin_api_key, require_client_api_key
from app.database import get_db
from app.models import ApiClient

DbSession = Annotated[AsyncSession, Depends(get_db)]
AdminKey = Annotated[str, Depends(require_admin_api_key)]


async def client_api_key_dependency(
    request: Request,
    db: DbSession,
    x_api_key: str | None = Header(default=None),
) -> ApiClient:
    return await require_client_api_key(request, db, x_api_key)


ClientApiKey = Annotated[ApiClient, Depends(client_api_key_dependency)]
