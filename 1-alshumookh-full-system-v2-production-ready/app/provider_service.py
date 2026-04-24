from __future__ import annotations

from typing import Any

import httpx

from app.config import settings
from app.models import Provider


class TransakProvider:
    def __init__(self) -> None:
        self.base_url = (
            settings.transak_staging_base_url.rstrip("/")
            if settings.transak_env.lower() == "staging"
            else settings.transak_base_url.rstrip("/")
        )

    async def refresh_access_token(self) -> str:
        """
        Create/refresh a Transak partner access token.
        """

        url = f"{self.base_url}/refresh-token"

        headers = {
            "accept": "application/json",
            "content-type": "application/json",
            "api-key": settings.transak_api_key,
        }

        payload = {
            "apiSecret": settings.transak_api_secret,
        }

        async with httpx.AsyncClient(timeout=30) as client:
            res = await client.post(url, headers=headers, json=payload)
            res.raise_for_status()

        body = res.json()
        return body.get("data", {}).get("accessToken") or body.get("accessToken")

    async def create_widget_url(self, payload: dict[str, Any]) -> str:
        token = await self.refresh_access_token()

        url = f"{self.base_url}/widgets/create-widget-url"

        headers = {
            "accept": "application/json",
            "content-type": "application/json",
            "Authorization": f"Bearer {token}",
        }

        async with httpx.AsyncClient(timeout=30) as client:
            res = await client.post(url, headers=headers, json=payload)
            res.raise_for_status()

        body = res.json()
        return body.get("data", {}).get("widgetUrl") or body.get("widgetUrl")


async def get_provider(provider: Provider | str):
    if isinstance(provider, str):
        provider = Provider(provider.lower())

    if provider == Provider.TRANSAK:
        return TransakProvider()

    raise NotImplementedError(f"Provider {provider} is not wired yet")
