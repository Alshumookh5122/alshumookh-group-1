"""
Shared utility functions — references, encryption, QR codes, formatting.
"""

import os
import hmac
import hashlib
import secrets
import string
import base64
import qrcode
import io
from datetime import datetime
from decimal import Decimal
from typing import Optional
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes

from app.app.config import settings


# ── Reference Generation ─────────────────────────────────────────────────────

def generate_payment_reference(prefix: str = "PAY") -> str:
    """Generate a human-readable unique payment reference like PAY-2024-X7KP2M."""
    year = datetime.utcnow().strftime("%Y")
    chars = string.ascii_uppercase + string.digits
    suffix = "".join(secrets.choice(chars) for _ in range(6))
    return f"{prefix}-{year}-{suffix}"


def generate_api_key() -> str:
    """Generate a 32-byte hex API key."""
    return secrets.token_hex(32)


# ── Encryption (for private keys) ────────────────────────────────────────────

def _get_fernet() -> Fernet:
    """Derive a stable Fernet key from SECRET_KEY."""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"alshumookh-v1",
        iterations=100_000,
    )
    key_bytes = kdf.derive(settings.SECRET_KEY.encode())
    return Fernet(base64.urlsafe_b64encode(key_bytes))


def encrypt_private_key(private_key: str) -> str:
    """Encrypt a wallet private key for storage."""
    f = _get_fernet()
    return f.encrypt(private_key.encode()).decode()


def decrypt_private_key(encrypted: str) -> str:
    """Decrypt a stored wallet private key."""
    f = _get_fernet()
    return f.decrypt(encrypted.encode()).decode()


# ── HMAC Verification ────────────────────────────────────────────────────────

def verify_webhook_signature(payload: bytes, signature: str, secret: str) -> bool:
    """Verify an HMAC-SHA256 webhook signature."""
    expected = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    # Support 'sha256=<hex>' format used by many providers
    if signature.startswith("sha256="):
        signature = signature[7:]
    return hmac.compare_digest(expected, signature)


def verify_alchemy_signature(payload: bytes, signature: str) -> bool:
    return verify_webhook_signature(payload, signature, settings.ALCHEMY_WEBHOOK_SECRET)


# ── QR Code ──────────────────────────────────────────────────────────────────

def generate_qr_code_base64(data: str) -> str:
    """Generate a base64-encoded PNG QR code."""
    qr = qrcode.QRCode(version=1, box_size=10, border=4)
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode()


def generate_crypto_payment_uri(address: str, token: str, amount: Optional[Decimal] = None) -> str:
    """Generate an EIP-681 payment URI for QR codes."""
    if token == "ETH":
        uri = f"ethereum:{address}"
        if amount:
            uri += f"?value={int(amount * Decimal('1e18'))}"
    else:
        uri = f"ethereum:{address}"
    return uri


# ── Amount Helpers ───────────────────────────────────────────────────────────

def wei_to_eth(wei: int) -> Decimal:
    return Decimal(str(wei)) / Decimal("1e18")


def eth_to_wei(eth: Decimal) -> int:
    return int(eth * Decimal("1e18"))


def token_to_base_units(amount: Decimal, decimals: int = 18) -> int:
    return int(amount * Decimal(f"1e{decimals}"))


def base_units_to_token(units: int, decimals: int = 18) -> Decimal:
    return Decimal(str(units)) / Decimal(f"1e{decimals}")


def format_amount(amount: Decimal, decimals: int = 6) -> str:
    return f"{amount:.{decimals}f}".rstrip("0").rstrip(".")


# ── Pagination Math ───────────────────────────────────────────────────────────

def calc_offset(page: int, per_page: int) -> int:
    return (page - 1) * per_page


def calc_pages(total: int, per_page: int) -> int:
    return max(1, (total + per_page - 1) // per_page)


# ── Masking ──────────────────────────────────────────────────────────────────

def mask_address(address: str) -> str:
    """Return 0x1234...abcd format."""
    if len(address) < 10:
        return address
    return f"{address[:6]}...{address[-4:]}"


def mask_email(email: str) -> str:
    parts = email.split("@")
    if len(parts) != 2:
        return email
    local = parts[0]
    masked_local = local[0] + "*" * (len(local) - 2) + local[-1] if len(local) > 2 else local
    return f"{masked_local}@{parts[1]}"
