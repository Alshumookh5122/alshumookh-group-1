from fastapi import Header, HTTPException, status
from app.config import get_settings


async def require_admin_api_key(x_admin_api_key: str | None = Header(default=None)) -> str:
    settings = get_settings()
    if not x_admin_api_key or x_admin_api_key != settings.admin_api_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Invalid admin API key')
    return x_admin_api_key
