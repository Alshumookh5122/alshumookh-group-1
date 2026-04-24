from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

import httpx
from fastapi import HTTPException

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
        url = f"{self.base_url}/refresh-token"
        headers = {
            "accept": "application/json",
            "content-type": "application/json",
            "api-key": settings.transak_api_key,
        }
        payload = {"apiSecret": settings.transak_api_secret}
        async with httpx.AsyncClient(timeout=30) as client:
            res = await client.post(url, headers=headers, json=payload)
        if res.status_code >= 400:
            raise HTTPException(status_code=400, detail=f"Transak authentication failed: {res.text}")
        body = res.json()
        token = body.get("data", {}).get("accessToken") or body.get("accessToken")
        if not token:
            raise HTTPException(status_code=400, detail=f"Transak did not return accessToken: {body}")
        return token

    async def create_widget_url(self, payload: dict[str, Any]) -> str:
        if settings.transak_mock_enabled:
            query = urlencode({
                "provider": "transak-mock",
                "wallet": payload.get("walletAddress", ""),
                "amount": payload.get("fiatAmount") or payload.get("cryptoAmount") or "",
                "currency": payload.get("cryptoCurrency", "USDT"),
                "network": str(payload.get("network", "ethereum")),
            })
            base = settings.public_base_url or "https://alshumookh-group-1.onrender.com"
            return f"{base.rstrip('/')}/pay/mock?{query}"

        token = await self.refresh_access_token()
        url = f"{self.base_url}/widgets/create-widget-url"
        headers = {
            "accept": "application/json",
            "content-type": "application/json",
            "Authorization": f"Bearer {token}",
        }
        async with httpx.AsyncClient(timeout=30) as client:
            res = await client.post(url, headers=headers, json=payload)
        if res.status_code >= 400:
            raise HTTPException(status_code=400, detail=f"Transak widget creation failed: {res.text}")
        body = res.json()
        widget_url = body.get("data", {}).get("widgetUrl") or body.get("widgetUrl")
        if not widget_url:
            raise HTTPException(status_code=400, detail=f"Transak did not return widgetUrl: {body}")
        return widget_url


async def get_provider(provider: Provider | str):
    if isinstance(provider, str):
        provider = Provider(provider.lower())
    if provider == Provider.TRANSAK:
        return TransakProvider()
    raise NotImplementedError(f"Provider {provider} is not wired yet")
