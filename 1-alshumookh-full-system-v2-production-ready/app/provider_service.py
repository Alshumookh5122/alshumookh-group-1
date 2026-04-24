from __future__ import annotations

from typing import Any
import httpx

from fastapi import HTTPException

from app.config import settings
from app.models import Provider


class TransakProvider:
    def __init__(self) -> None:
        self.base_url = (
            settings.transak_staging_base_url
            if settings.transak_env.lower() == "staging"
            else settings.transak_base_url
        )

    async def refresh_access_token(self) -> str:
        url = f"{self.base_url}/api/v2/refresh-token/"

        async with httpx.AsyncClient(timeout=30) as client:
            try:
                res = await client.post(
                    url,
                    headers={
                        "accept": "application/json",
                        "api-secret": settings.transak_api_secret,
                        "content-type": "application/json",
                    },
                    json={"apiKey": settings.transak_api_key},
                )

                if res.status_code != 200:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Transak auth failed: {res.text}",
                    )

                body = res.json()
                return body.get("data", {}).get("accessToken") or body.get("accessToken")

            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))

    async def create_widget_url(self, payload: dict[str, Any]) -> str:
        token = await self.refresh_access_token()
        url = f"{self.base_url}/api/v2/widgets/create-widget-url"

        async with httpx.AsyncClient(timeout=30) as client:
            try:
                res = await client.post(
                    url,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )

                if res.status_code != 200:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Widget creation failed: {res.text}",
                    )

                body = res.json()
                return body.get("data", {}).get("widgetUrl") or body.get("widgetUrl")

            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))


async def get_provider(provider: Provider | str):
    if isinstance(provider, str):
        provider = Provider(provider.lower())

    if provider == Provider.TRANSAK:
        return TransakProvider()

    raise NotImplementedError(f"Provider {provider} is not wired yet")
