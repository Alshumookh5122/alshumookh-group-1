import hashlib
import hmac
import json
import time
from typing import Any


def stable_hash(payload: Any) -> str:
    body = json.dumps(payload, sort_keys=True, default=str).encode('utf-8')
    return hashlib.sha256(body).hexdigest()


def verify_hmac_sha256(secret: str, body: bytes, signature: str) -> bool:
    if signature.startswith('sha256='):
        signature = signature.removeprefix('sha256=')
    digest = hmac.new(secret.encode('utf-8'), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(digest, signature)


def verify_hook0_signature(
    secret: str,
    body: bytes,
    signature_header: str,
    headers: dict[str, str],
    max_age_minutes: int = 5,
) -> bool:
    try:
        elements = dict(item.split('=', 1) for item in signature_header.split(',') if '=' in item)
        timestamp = int(elements['t'])
        header_names = elements['h']
        provided_signature = elements['v1']
    except (KeyError, ValueError):
        return False

    age_minutes = (time.time() - timestamp) / 60
    if age_minutes > max_age_minutes:
        return False

    normalized_headers = {key.lower(): value for key, value in headers.items()}
    header_values = '.'.join(normalized_headers.get(name.lower(), '') for name in header_names.split(' '))
    signed_payload = f'{timestamp}.{header_names}.{header_values}.{body.decode("utf-8")}'
    expected = hmac.new(secret.encode('utf-8'), signed_payload.encode('utf-8'), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, provided_signature)
