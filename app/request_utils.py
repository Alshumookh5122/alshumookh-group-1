from __future__ import annotations

import ipaddress

from fastapi import Request

from app.config import get_settings

IP_HEADER_CANDIDATES = (
    "cf-connecting-ip",
    "true-client-ip",
    "x-forwarded-for",
    "x-real-ip",
)


def _parse_ip(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return str(ipaddress.ip_address(str(value).strip()))
    except ValueError:
        return None


def _trusted_proxy_host(request: Request) -> str | None:
    if getattr(request.state, "trusted_proxy", False):
        return getattr(request.state, "proxy_ip", None)

    client_host = _parse_ip(request.client.host) if request.client else None
    if not client_host:
        return None

    settings = get_settings()
    trusted_proxies = set(settings.trusted_proxy_ips())
    if client_host in trusted_proxies:
        return client_host

    return None


def get_client_ip(request: Request) -> str | None:
    """
    Return the best-effort client IP address.

    Preference order favors headers commonly set by Cloudflare and reverse
    proxies, then falls back to the direct client socket.
    """
    state_ip = _parse_ip(getattr(request.state, "client_ip", None))
    if state_ip:
        return state_ip

    trusted_proxy = _trusted_proxy_host(request)
    if trusted_proxy:
        for header in IP_HEADER_CANDIDATES:
            value = request.headers.get(header)
            if not value:
                continue
            if header == "x-forwarded-for":
                return _parse_ip(value.split(",")[0].strip())
            parsed = _parse_ip(value.strip())
            if parsed:
                return parsed

    if request.client:
        return _parse_ip(request.client.host) or request.client.host

    return None
