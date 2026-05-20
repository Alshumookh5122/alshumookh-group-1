from __future__ import annotations

import uuid

from fastapi import Request, Response
from starlette.middleware.base import RequestResponseEndpoint

from app.audit_service import log_event
from app.database import AsyncSessionLocal
from app.request_utils import get_client_ip


PROTECTED_PREFIXES = (
    '/api/v1/admin',
    '/api/v1/oauth',
    '/api/v1/payloads',
    '/api/v1/transfer-request',
    '/api/v1/transfers',
    '/api/v1/transfer/',
    '/api/v1/transactions',
    '/api/v1/payments/ledger/status',
)


def _should_audit(path: str) -> bool:
    return any(path.startswith(prefix) for prefix in PROTECTED_PREFIXES)


def _client_ip(request: Request) -> str | None:
    return get_client_ip(request)


def _transaction_id_from_path(path: str) -> str | None:
    marker = '/transactions/'
    if marker in path:
        tail = path.split(marker, 1)[1].strip('/')
        if tail and not tail.startswith('external/'):
            return tail.split('/', 1)[0]

    marker = '/payments/ledger/status/'
    if marker in path:
        tail = path.split(marker, 1)[1].strip('/')
        if tail:
            return tail.split('/', 1)[0]

    return None


async def audit_request_middleware(
    request: Request,
    call_next: RequestResponseEndpoint,
) -> Response:
    path = request.url.path
    if not _should_audit(path):
        return await call_next(request)

    request_id = (
        getattr(request.state, 'request_id', None)
        or request.headers.get('x-request-id')
        or str(uuid.uuid4())
    )
    request.state.request_id = request_id
    status_code = 500
    error_message = None

    try:
        response = await call_next(request)
        status_code = response.status_code
        response.headers['X-Request-ID'] = request_id
        return response
    except Exception as exc:
        error_message = str(exc)
        raise
    finally:
        try:
            async with AsyncSessionLocal() as db:
                await log_event(
                    db,
                    'API_REQUEST',
                    {
                        'client_name': getattr(request.state, 'client_name', None),
                    },
                    getattr(request.state, 'order_id', None),
                    client_id=getattr(request.state, 'client_id', None),
                    endpoint=path,
                    method=request.method,
                    ip=_client_ip(request),
                    user_agent=request.headers.get('user-agent'),
                    status_code=status_code,
                    transaction_id=getattr(request.state, 'transaction_id', None) or _transaction_id_from_path(path),
                    request_id=request_id,
                    error_message=error_message,
                )
        except Exception:
            pass
