from __future__ import annotations

from typing import Any
import httpx

from app.config import settings
from app.models import Provider

settings = get_settings()


class TransakProvider:
    def __init__(self) -> None:
        self.base_url = settings.transak_staging_base_url if settings.transak_env.lower() == 'staging' else settings.transak_base_url

    async def refresh_access_token(self) -> str:
        """Create/refresh a Transak partner access token.

        The returned access token is used for Create Widget URL API and for
        decoding Transak webhook JWT payloads.
        """
        url = f'{self.base_url}/partners/api/v2/refresh-token'
        async with httpx.AsyncClient(timeout=30) as client:
            res = await client.post(
                url,
                headers={
                    'accept': 'application/json',
                    'api-secret': settings.transak_api_secret,
                    'content-type': 'application/json',
                },
                json={'apiKey': settings.transak_api_key},
            )
            res.raise_for_status()
            body = res.json()
            return body.get('data', {}).get('accessToken') or body['accessToken']

    async def create_widget_url(self, payload: dict[str, Any]) -> str:
        token = await self.refresh_access_token()
        url = f'{self.base_url}/api/v2/widgets/create-widget-url'
        async with httpx.AsyncClient(timeout=30) as client:
            res = await client.post(
                url,
                headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'},
                json=payload,
            )
            res.raise_for_status()
            body = res.json()
            return body.get('data', {}).get('widgetUrl') or body['widgetUrl']


async def get_provider(provider: Provider | str):
    if isinstance(provider, str):
        provider = Provider(provider.lower())
    if provider == Provider.TRANSAK:
        return TransakProvider()
    raise NotImplementedError(f'Provider {provider} is not wired yet')
