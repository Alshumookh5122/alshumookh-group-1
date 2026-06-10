"""
payload_service.py
──────────────────
Field normalization engine + Alchemy/RPC blockchain TX verifier
for the ALSHUMOOKH settlement receiver pipeline.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
import base64
import re
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import httpx
import jwt
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.config import settings

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Known ERC-20 token contracts
# ─────────────────────────────────────────────────────────────────────────────
KNOWN_CONTRACTS: dict[str, str] = {
    "0xdac17f958d2ee523a2206206994597c13d831ec7": "USDT",   # ETH USDT
    "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48": "USDC",   # ETH USDC
    "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913": "USDC",   # Base USDC
}

ERC20_TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"

# ─────────────────────────────────────────────────────────────────────────────
# Field alias mapping
# ─────────────────────────────────────────────────────────────────────────────
FIELD_ALIASES: dict[str, list[str]] = {
    "transaction_reference": [
        "transaction_reference",
        "transaction_id",
        "txRef",
        "reference",
        "ref",
        "transactionCode",
        "referenceId",
        "payment_reference",
    ],
    "tx_hash": [
        "tx_hash",
        "transaction_hash",
        "hash",
        "blockchain_hash",
        "txid",
        "txHash",
        "transactionHash",
    ],
    "sender_wallet": [
        "sender_wallet",
        "from_wallet",
        "from",
        "source_wallet",
        "origin_wallet",
        "fromAddress",
        "from_address",
        "senderAddress",
    ],
    "receiver_wallet": [
        "receiver_wallet",
        "to_wallet",
        "to",
        "destination_wallet",
        "beneficiary_wallet",
        "toAddress",
        "to_address",
        "recipientAddress",
    ],
    "amount": [
        "amount",
        "value",
        "token_amount",
        "transfer_amount",
        "settlement_amount",
        "tokenAmount",
        "transferAmount",
    ],
    "asset": [
        "asset",
        "currency",
        "token",
        "symbol",
        "crypto_currency",
        "tokenSymbol",
        "cryptoCurrency",
    ],
    "network": [
        "network",
        "chain",
        "blockchain",
        "protocol",
        "chainName",
        "networkName",
    ],
    "token_contract": [
        "token_contract",
        "contract_address",
        "contract",
        "token_address",
        "contractAddress",
        "tokenContract",
    ],
    "timestamp": [
        "timestamp",
        "created_at",
        "time",
        "tx_time",
        "txTime",
        "transaction_time",
    ],
    "sender": [
        "sender",
        "sender_name",
        "from_name",
        "senderName",
        "fromName",
        "payer",
    ],
    "receiver": [
        "receiver",
        "receiver_name",
        "to_name",
        "beneficiary",
        "receiverName",
        "toName",
        "payee",
    ],
    "authorization_code": [
        "authorization_code",
        "auth_code",
        "authorization",
        "authCode",
        "authorizationCode",
    ],
    "settlement_type": [
        "settlement_type",
        "settlement",
        "type",
        "settlementType",
        "paymentType",
        "payment_type",
    ],
    "callback_url": [
        "callback_url",
        "callback",
        "webhook_url",
        "notify_url",
        "callbackUrl",
        "webhookUrl",
        "notifyUrl",
    ],
    "signature": [
        "signature",
        "sig",
        "x_signature",
        "xSignature",
        "payloadSignature",
    ],
    "payload_hash": [
        "payload_hash",
        "hash_payload",
        "content_hash",
        "payloadHash",
        "contentHash",
    ],
}


# ─────────────────────────────────────────────────────────────────────────────
# Normalization helpers
# ─────────────────────────────────────────────────────────────────────────────

def _find_field(data: dict, aliases: list[str]) -> Any:
    """Search top-level and one level deep for any alias."""
    for alias in aliases:
        if alias in data:
            return data[alias]
    for key, val in data.items():
        if isinstance(val, dict):
            for alias in aliases:
                if alias in val:
                    return val[alias]
    return None


def normalize_payload(raw: dict) -> dict:
    """
    Extract and normalize all known fields from an arbitrary JSON payload.
    Returns a flat dict with canonical field names.
    """
    result: dict[str, Any] = {}
    for field, aliases in FIELD_ALIASES.items():
        value = _find_field(raw, aliases)
        if value is not None:
            result[field] = value

    if str(raw.get("document_type") or "").upper() == "PAYMENT_ORDER":
        result.update(_normalize_payment_order(raw, result))
    return result


def _normalize_payment_order(raw: dict, existing: dict[str, Any]) -> dict[str, Any]:
    """Normalize sender payment-order documents without treating proposed hashes as settled funds."""
    amount = raw.get("amount") if isinstance(raw.get("amount"), dict) else {}
    blockchain_anchor = raw.get("blockchain_anchor") if isinstance(raw.get("blockchain_anchor"), dict) else {}
    settlement_instructions = (
        raw.get("settlement_instructions") if isinstance(raw.get("settlement_instructions"), dict) else {}
    )
    payee = raw.get("payee") if isinstance(raw.get("payee"), dict) else {}
    payer = raw.get("payer") if isinstance(raw.get("payer"), dict) else {}
    bank_account = payer.get("bank_account") if isinstance(payer.get("bank_account"), dict) else {}
    receiver_wallet = (
        settlement_instructions.get("receiver_wallet")
        or blockchain_anchor.get("receiver_wallet")
        or blockchain_anchor.get("beneficiary_wallet")
        or blockchain_anchor.get("destination_wallet")
        or payee.get("receiver_wallet")
        or existing.get("receiver_wallet")
    )

    token_contract = str(blockchain_anchor.get("contract") or "").strip()
    contract_match = re.search(r"0x[a-fA-F0-9]{40}", token_contract)
    normalized: dict[str, Any] = {
        "transaction_reference": raw.get("reference") or existing.get("transaction_reference"),
        "settlement_type": "payment_order",
        "document_type": "PAYMENT_ORDER",
        "sender": payer.get("legal_name") or existing.get("sender"),
        "receiver": payee.get("legal_name") or existing.get("receiver"),
        "receiver_wallet": receiver_wallet,
        "network": blockchain_anchor.get("chain") or existing.get("network"),
        "token_contract": contract_match.group(0).lower() if contract_match else existing.get("token_contract"),
        "proposed_tx_hash": blockchain_anchor.get("proposed_tx_hash"),
        "payer_bank_name": bank_account.get("bank_name"),
        "payer_iban": bank_account.get("iban"),
        "payer_swift": bank_account.get("swift"),
        "valid_until": raw.get("valid_until"),
        "nonce": raw.get("nonce"),
    }

    if amount.get("usdt") is not None:
        normalized["amount"] = amount.get("usdt")
        normalized["asset"] = "USDT"
    elif amount.get("usd") is not None:
        normalized["amount"] = amount.get("usd")
        normalized["asset"] = "USD"

    return {key: value for key, value in normalized.items() if value is not None}


def detect_network(payload: dict, normalized: dict) -> str | None:
    """Best-effort network detection from normalized + raw fields."""
    net = str(normalized.get("network") or "").lower()
    if not net:
        tx = str(normalized.get("tx_hash") or "").lower()
        # Tron hashes are base58 and don't start with 0x
        if tx and not tx.startswith("0x") and len(tx) > 20:
            return "tron"
        return None

    if net in {"ethereum", "ethereum mainnet", "eth", "erc20", "eth-mainnet"}:
        return "ethereum"
    if net in {"base", "base-mainnet", "base_mainnet"}:
        return "base"
    if net in {"tron", "trx", "trc20"}:
        return "tron"
    return net


# ─────────────────────────────────────────────────────────────────────────────
# HMAC verification
# ─────────────────────────────────────────────────────────────────────────────

def verify_payload_hmac(
    raw_body: bytes,
    x_timestamp: str | None,
    x_signature: str | None,
    hmac_secret: str,
) -> bool:
    """
    Verify the HMAC-SHA256 signature on an inbound payload.
    Signature base string: timestamp + "." + raw_body
    """
    if not x_timestamp or not x_signature:
        return False

    try:
        ts = int(x_timestamp)
        age_seconds = abs(time.time() - ts)
        if age_seconds > 300:  # 5 minutes
            return False
    except (ValueError, TypeError):
        return False

    base = x_timestamp.encode() + b"." + raw_body
    expected = hmac.new(
        hmac_secret.encode("utf-8"),
        base,
        hashlib.sha256,
    ).hexdigest()

    received = x_signature.removeprefix("sha256=").strip()
    return hmac.compare_digest(expected, received)


def payload_sha256(raw_body: bytes | str) -> str:
    if isinstance(raw_body, str):
        raw_body = raw_body.encode("utf-8")
    return hashlib.sha256(raw_body).hexdigest()


def _b64url_decode(value: str) -> bytes:
    padded = value + "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii"))


def verify_payload_jws(
    raw_body: bytes,
    compact_jws: str | None,
    public_key_pem: str | None,
) -> tuple[bool, str | None]:
    """
    Verify a detached JWS/JWT-style signature for the raw payload.

    Expected JWS claims:
      payload_hash = sha256(raw_body)
      iat / exp are recommended and validated by PyJWT when exp exists.

    Supported algorithms: RS256, PS256, ES256, ES384.
    """
    if not compact_jws or not public_key_pem:
        return False, "missing_jws_or_public_key"

    try:
        claims = jwt.decode(
            compact_jws,
            public_key_pem,
            algorithms=["RS256", "PS256", "ES256", "ES384"],
            options={"require": ["payload_hash"]},
        )
    except jwt.PyJWTError as exc:
        return False, f"invalid_jws: {exc}"

    expected_hash = payload_sha256(raw_body)
    received_hash = str(claims.get("payload_hash") or "").lower()
    if not hmac.compare_digest(expected_hash, received_hash):
        return False, "jws_payload_hash_mismatch"

    return True, None


def _load_jwe_private_key():
    raw = getattr(settings, "settlement_jwe_private_key_pem", None)
    if not raw:
        return None

    text = str(raw).strip()
    if "BEGIN" not in text:
        try:
            text = base64.b64decode(text).decode("utf-8")
        except Exception:
            pass

    password = getattr(settings, "settlement_jwe_private_key_passphrase", None)
    return serialization.load_pem_private_key(
        text.encode("utf-8"),
        password=password.encode("utf-8") if password else None,
    )


def decrypt_payload_jwe(raw_body: bytes) -> tuple[bytes, dict[str, Any]]:
    """
    Decrypt a compact JSON JWE envelope:

    {
      "alg": "RSA-OAEP-256",
      "enc": "A256GCM",
      "encrypted_key": "...base64url...",
      "iv": "...base64url...",
      "ciphertext": "...base64url...",
      "tag": "...base64url...",
      "aad": "optional-base64url"
    }

    This is intentionally minimal and open-source only. It is mTLS/JWS/HMAC
    compatible and can be replaced later by a full JOSE gateway without
    changing the external endpoint.
    """
    key = _load_jwe_private_key()
    if key is None:
        raise ValueError("JWE private key is not configured")

    envelope = json.loads(raw_body.decode("utf-8"))
    alg = envelope.get("alg") or "RSA-OAEP-256"
    enc = envelope.get("enc") or "A256GCM"
    if alg != "RSA-OAEP-256" or enc != "A256GCM":
        raise ValueError("Unsupported JWE alg/enc")

    cek = key.decrypt(
        _b64url_decode(envelope["encrypted_key"]),
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None,
        ),
    )
    iv = _b64url_decode(envelope["iv"])
    ciphertext = _b64url_decode(envelope["ciphertext"])
    tag = _b64url_decode(envelope["tag"])
    aad = _b64url_decode(envelope["aad"]) if envelope.get("aad") else None

    plaintext = AESGCM(cek).decrypt(iv, ciphertext + tag, aad)
    return plaintext, {"alg": alg, "enc": enc, "aad_present": bool(aad)}


# ─────────────────────────────────────────────────────────────────────────────
# RPC helpers
# ─────────────────────────────────────────────────────────────────────────────

def _get_rpc_url(network: str) -> str | None:
    """Resolve the best available RPC URL for the given network."""
    n = network.lower()
    if n in {"ethereum", "eth", "erc20"}:
        url = (
            getattr(settings, "alchemy_ethereum_rpc_url", None)
            or getattr(settings, "alchemy_eth_rpc_url", None)
            or getattr(settings, "alchemy_rpc_url", None)
            or getattr(settings, "ethereum_rpc_url", None)
        )
        if url:
            url = str(url).strip()
            if url.startswith(("http://", "https://")):
                return url
            api_key = getattr(settings, "alchemy_api_key", None)
            if api_key and api_key != "test":
                return f"https://eth-mainnet.g.alchemy.com/v2/{api_key}"
        api_key = getattr(settings, "alchemy_api_key", None)
        if api_key and api_key != "test":
            return f"https://eth-mainnet.g.alchemy.com/v2/{api_key}"
        return None

    if n in {"base", "base-mainnet"}:
        url = (
            getattr(settings, "alchemy_base_rpc_url", None)
            or getattr(settings, "base_rpc_url", None)
        )
        if url:
            url = str(url).strip()
            if url.startswith(("http://", "https://")):
                return url
        api_key = getattr(settings, "alchemy_api_key", None)
        if api_key and api_key != "test":
            return f"https://base-mainnet.g.alchemy.com/v2/{api_key}"
        return None

    return None


def _get_master_wallet(network: str) -> str | None:
    """Return our approved master receiver wallet for a network."""
    n = network.lower()
    if n in {"ethereum", "eth", "erc20"}:
        return (
            getattr(settings, "master_wallet_ethereum", None)
            or getattr(settings, "ledger_ethereum_address", None)
            or getattr(settings, "eth_treasury_address", None)
        )
    if n in {"base", "base-mainnet"}:
        return (
            getattr(settings, "master_wallet_base", None)
            or getattr(settings, "ledger_base_address", None)
            or getattr(settings, "eth_treasury_address", None)
        )
    if n in {"tron", "trx", "trc20"}:
        return (
            getattr(settings, "master_wallet_tron", None)
            or getattr(settings, "tron_treasury_address", None)
        )
    return None


async def _json_rpc(
    rpc_url: str,
    method: str,
    params: list,
    timeout: float = 15.0,
) -> dict:
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(
            rpc_url,
            json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
        )
        resp.raise_for_status()
        return resp.json()


def _hex_to_int(value: Any) -> int | None:
    try:
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.startswith("0x"):
            return int(value, 16)
        if value is not None:
            return int(str(value))
    except Exception:
        pass
    return None


def _decode_erc20_amount(raw_hex: str, decimals: int = 6) -> Decimal | None:
    """Decode a 32-byte ABI-encoded uint256 to a human decimal."""
    try:
        value = int(raw_hex, 16)
        return Decimal(value) / (Decimal(10) ** decimals)
    except Exception:
        return None


def _addr_from_topic(topic: str) -> str:
    """Extract an Ethereum address from a 32-byte log topic."""
    return "0x" + topic[-40:].lower()


def _explorer_url(network: str, tx_hash: str) -> str:
    n = network.lower()
    if n in {"base", "base-mainnet"}:
        return f"https://basescan.org/tx/{tx_hash}"
    if n in {"tron", "trx", "trc20"}:
        return f"https://tronscan.org/#/transaction/{tx_hash}"
    return f"https://etherscan.io/tx/{tx_hash}"


# ─────────────────────────────────────────────────────────────────────────────
# Blockchain TX verification
# ─────────────────────────────────────────────────────────────────────────────

async def verify_tx_on_chain(
    tx_hash: str,
    network: str,
    expected_receiver: str | None = None,
    expected_sender: str | None = None,
    expected_amount: Decimal | None = None,
    expected_contract: str | None = None,
    expected_asset: str | None = None,
) -> dict:
    """
    Verify a transaction hash against the blockchain.
    Returns a structured result dict suitable for storing in ExternalPayload.blockchain_result.
    """
    result: dict[str, Any] = {
        "network": network,
        "tx_hash": tx_hash,
        "verified": False,
        "checks": {},
        "error": None,
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
    }

    # ── Tron placeholder ──────────────────────────────────────────────────────
    if network.lower() in {"tron", "trx", "trc20"}:
        result["error"] = "Tron verification is not yet implemented — manual review required."
        result["status"] = "TRON_PLACEHOLDER"
        return result

    rpc_url = _get_rpc_url(network)
    if not rpc_url:
        result["error"] = f"RPC URL not configured for network: {network}"
        result["status"] = "RPC_NOT_CONFIGURED"
        return result

    master_wallet = _get_master_wallet(network)

    try:
        # 1. Get transaction
        tx_resp = await _json_rpc(rpc_url, "eth_getTransactionByHash", [tx_hash])
        tx = tx_resp.get("result")

        if not tx:
            result["error"] = "Transaction not found on chain"
            result["status"] = "TX_NOT_FOUND"
            return result

        # 2. Get receipt
        receipt_resp = await _json_rpc(rpc_url, "eth_getTransactionReceipt", [tx_hash])
        receipt = receipt_resp.get("result")

        if not receipt:
            result["error"] = "Transaction receipt not found — may be pending"
            result["status"] = "RECEIPT_PENDING"
            return result

        # 3. Get latest block for confirmations
        block_resp = await _json_rpc(rpc_url, "eth_blockNumber", [])
        latest_block_hex = block_resp.get("result", "0x0")
        latest_block = _hex_to_int(latest_block_hex) or 0

        tx_block = _hex_to_int(receipt.get("blockNumber"))
        confirmations = (latest_block - tx_block) if tx_block is not None else 0

        # 4. Check success status
        receipt_status = _hex_to_int(receipt.get("status"))
        tx_success = receipt_status == 1

        result["block_number"] = tx_block
        result["confirmations"] = max(0, confirmations)
        result["tx_success"] = tx_success
        result["explorer_url"] = _explorer_url(network, tx_hash)

        if not tx_success:
            result["error"] = "Transaction reverted or failed on chain"
            result["status"] = "TX_FAILED"
            return result

        # 5. Parse ERC-20 Transfer logs
        logs = receipt.get("logs") or []
        transfer_log = None
        for log_entry in logs:
            topics = log_entry.get("topics") or []
            if topics and topics[0].lower() == ERC20_TRANSFER_TOPIC:
                transfer_log = log_entry
                break

        on_chain_receiver: str | None = None
        on_chain_sender: str | None = None
        on_chain_amount: Decimal | None = None
        on_chain_contract: str | None = None
        on_chain_asset: str | None = None
        is_native_transfer = False

        if transfer_log:
            topics = transfer_log.get("topics") or []
            if len(topics) >= 3:
                on_chain_sender = _addr_from_topic(topics[1])
                on_chain_receiver = _addr_from_topic(topics[2])
            on_chain_contract = str(transfer_log.get("address") or "").lower()
            on_chain_asset = KNOWN_CONTRACTS.get(on_chain_contract)
            raw_data = transfer_log.get("data", "0x")
            if raw_data and raw_data != "0x":
                decimals = 6 if on_chain_asset in {"USDT", "USDC"} else 18
                on_chain_amount = _decode_erc20_amount(raw_data[2:].zfill(64), decimals)
        else:
            # Native ETH transfer
            is_native_transfer = True
            on_chain_sender = str(tx.get("from") or "").lower()
            on_chain_receiver = str(tx.get("to") or "").lower()
            on_chain_asset = "ETH"
            value_hex = tx.get("value", "0x0")
            raw_value = _hex_to_int(value_hex)
            if raw_value is not None:
                on_chain_amount = Decimal(raw_value) / (Decimal(10) ** 18)

        result["on_chain"] = {
            "sender": on_chain_sender,
            "receiver": on_chain_receiver,
            "amount": str(on_chain_amount) if on_chain_amount is not None else None,
            "asset": on_chain_asset,
            "contract": on_chain_contract,
            "is_native": is_native_transfer,
        }

        # 6. Verification checks
        checks: dict[str, bool | str] = {}

        # Receiver must match our master wallet
        if master_wallet:
            receiver_ok = (
                on_chain_receiver is not None
                and on_chain_receiver.lower() == master_wallet.lower()
            )
            checks["receiver_is_master_wallet"] = receiver_ok
            if not receiver_ok:
                result["error"] = (
                    f"Receiver {on_chain_receiver} does not match "
                    f"master wallet {master_wallet}"
                )
        else:
            checks["receiver_is_master_wallet"] = "MASTER_WALLET_NOT_CONFIGURED"
            if expected_receiver:
                receiver_ok = (
                    on_chain_receiver is not None
                    and on_chain_receiver.lower() == expected_receiver.lower()
                )
                checks["receiver_matches_declared"] = receiver_ok

        # Sender check
        if expected_sender and on_chain_sender:
            checks["sender_matches"] = on_chain_sender.lower() == expected_sender.lower()

        # Amount check
        if expected_amount is not None and on_chain_amount is not None:
            checks["amount_matches"] = abs(on_chain_amount - expected_amount) < Decimal("0.01")
        elif on_chain_amount is not None:
            checks["amount_detected"] = str(on_chain_amount)

        # Contract check
        if expected_contract and on_chain_contract:
            checks["contract_matches"] = on_chain_contract.lower() == expected_contract.lower()

        # Asset check
        if expected_asset and on_chain_asset:
            checks["asset_matches"] = on_chain_asset.upper() == expected_asset.upper()

        result["checks"] = checks

        # Overall verified = tx succeeded + receiver is master wallet (if known)
        master_ok = checks.get("receiver_is_master_wallet", False)
        result["verified"] = tx_success and (
            master_ok is True or master_ok == "MASTER_WALLET_NOT_CONFIGURED"
        )
        result["status"] = "VERIFIED" if result["verified"] else "VERIFICATION_FAILED"

    except httpx.HTTPStatusError as exc:
        result["error"] = f"RPC HTTP error: {exc.response.status_code}"
        result["status"] = "RPC_ERROR"
    except httpx.RequestError as exc:
        result["error"] = f"RPC connection error: {exc}"
        result["status"] = "RPC_ERROR"
    except Exception as exc:
        log.exception("Unexpected error during TX verification: %s", exc)
        result["error"] = f"Unexpected error: {exc}"
        result["status"] = "ERROR"

    return result


# ─────────────────────────────────────────────────────────────────────────────
# Callback signing
# ─────────────────────────────────────────────────────────────────────────────

def sign_callback(payload: dict, secret: str) -> str:
    """Return HMAC-SHA256 hex of the JSON-serialised callback payload."""
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
