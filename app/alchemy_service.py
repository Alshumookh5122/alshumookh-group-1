import hashlib
import hmac
from app.config import get_settings

settings = get_settings()


def alchemy_rpc_url() -> str:
    return f'https://{settings.alchemy_network}.g.alchemy.com/v2/{settings.alchemy_api_key}'


def verify_alchemy_signature(body: bytes, signature: str | None) -> bool:
    if not settings.alchemy_webhook_signing_key or not signature:
        return False
    digest = hmac.new(settings.alchemy_webhook_signing_key.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(digest, signature)
