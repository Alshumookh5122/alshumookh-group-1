import hashlib
import hmac
import json
from typing import Any


def stable_hash(payload: Any) -> str:
    body = json.dumps(payload, sort_keys=True, default=str).encode('utf-8')
    return hashlib.sha256(body).hexdigest()


def verify_hmac_sha256(secret: str, body: bytes, signature: str) -> bool:
    digest = hmac.new(secret.encode('utf-8'), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(digest, signature)
