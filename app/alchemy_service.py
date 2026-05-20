from __future__ import annotations

import hashlib
import hmac
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit_service import log_event
from app.config import settings
from app.models import Network, OrderStatus, PaymentOrder


ETHEREUM_LEDGER_WALLET = "0xBD682cfD8382a90adfDd6745780D3D7959c4d939"

ETHEREUM_USDT_CONTRACT = "0xdac17f958d2ee523a2206206994597c13d831ec7"
ETHEREUM_USDC_CONTRACT = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"
BASE_USDC_CONTRACT = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"

OFFICIAL_ETH_TOKEN_CONTRACTS = {
    ETHEREUM_USDT_CONTRACT: "USDT",
    ETHEREUM_USDC_CONTRACT: "USDC",
    BASE_USDC_CONTRACT: "USDC",
}

SUPPORTED_ETH_ASSETS = {"ETH", "USDT", "USDC"}


def alchemy_rpc_url(network: Network | str = Network.ETHEREUM) -> str:
    if isinstance(network, str):
        network_value = network.lower()
    else:
        network_value = network.value.lower()

    if network_value in {"ethereum", "eth", "erc20"}:
        url = (
            getattr(settings, "alchemy_eth_rpc_url", None)
            or getattr(settings, "alchemy_rpc_url", None)
            or getattr(settings, "ethereum_rpc_url", None)
        )

        if url:
            url = str(url).strip()

            if url.startswith(("http://", "https://")):
                return url

            return f"https://eth-mainnet.g.alchemy.com/v2/{url}"

        api_key = getattr(settings, "alchemy_api_key", None)

        if api_key:
            return f"https://eth-mainnet.g.alchemy.com/v2/{api_key}"

    if network_value in {"base", "base-mainnet"}:
        url = (
            getattr(settings, "alchemy_base_rpc_url", None)
            or getattr(settings, "base_rpc_url", None)
        )

        if url:
            url = str(url).strip()

            if url.startswith(("http://", "https://")):
                return url

            return f"https://base-mainnet.g.alchemy.com/v2/{url}"

        api_key = getattr(settings, "alchemy_api_key", None)

        if api_key:
            return f"https://base-mainnet.g.alchemy.com/v2/{api_key}"

    raise ValueError(f"Alchemy RPC URL is not configured for network: {network_value}")


def verify_alchemy_signature(raw_body: bytes, signature: str | None) -> bool:
    signing_key = getattr(settings, "alchemy_webhook_signing_key", None)

    if not signing_key:
        return False

    signing_key = str(signing_key).strip()

    if not signing_key:
        return False

    if not signature:
        return False

    expected = hmac.new(
        signing_key.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).hexdigest()

    received = signature.replace("sha256=", "").strip()

    return hmac.compare_digest(expected, received)


def _lower(value: Any) -> str:
    return str(value or "").lower()


def _decimal(value: Any) -> Decimal | None:
    try:
        if value in {None, ""}:
            return None

        return Decimal(str(value))
    except Exception:
        return None


def _decimal_from_raw(value: Any, decimals: Any) -> Decimal | None:
    if value in {None, ""}:
        return None

    try:
        if isinstance(value, str) and value.startswith("0x"):
            integer = int(value, 16)
        else:
            integer = int(str(value))

        scale = int(decimals or 0)
        return Decimal(integer) / (Decimal(10) ** scale)
    except Exception:
        return None


def _get_activity_items(payload: dict) -> list[dict]:
    event = payload.get("event") or {}
    activity = event.get("activity") or payload.get("activity") or []

    if isinstance(activity, list):
        return [item for item in activity if isinstance(item, dict)]

    if isinstance(activity, dict):
        return [activity]

    return []


def _extract_network(payload: dict, item: dict) -> Network:
    event = payload.get("event") or {}

    raw = str(
        item.get("network")
        or item.get("chain")
        or event.get("network")
        or event.get("chain")
        or payload.get("network")
        or payload.get("chain")
        or ""
    ).lower()

    if raw in {"base", "base-mainnet", "base_mainnet", "base-mainnet.g.alchemy.com"}:
        return Network.BASE

    return Network.ETHEREUM


def _extract_tx_hash(item: dict) -> str | None:
    log = item.get("log") or {}

    return (
        item.get("hash")
        or item.get("txHash")
        or item.get("transactionHash")
        or item.get("transaction_hash")
        or log.get("transactionHash")
    )


def _extract_to_address(item: dict) -> str | None:
    raw_contract = item.get("rawContract") or {}
    erc20_transfer = item.get("erc20TokenTransfer") or {}

    return (
        item.get("toAddress")
        or item.get("to")
        or item.get("recipient")
        or item.get("recipientAddress")
        or item.get("to_address")
        or erc20_transfer.get("to")
        or erc20_transfer.get("toAddress")
        or raw_contract.get("to")
    )


def _extract_contract_address(item: dict) -> str | None:
    raw_contract = item.get("rawContract") or {}
    erc20_transfer = item.get("erc20TokenTransfer") or {}
    log = item.get("log") or {}

    return (
        item.get("contractAddress")
        or item.get("contract_address")
        or erc20_transfer.get("contractAddress")
        or raw_contract.get("address")
        or log.get("address")
    )


def _extract_from_address(item: dict) -> str | None:
    erc20_transfer = item.get("erc20TokenTransfer") or {}

    return (
        item.get("fromAddress")
        or item.get("from")
        or item.get("sender")
        or item.get("senderAddress")
        or item.get("from_address")
        or erc20_transfer.get("from")
        or erc20_transfer.get("fromAddress")
    )


def _raw_asset(item: dict) -> str:
    return str(
        item.get("asset")
        or item.get("tokenSymbol")
        or item.get("symbol")
        or ""
    ).upper()


def _normalized_asset(item: dict, contract_address: str | None) -> str:
    contract = _lower(contract_address)

    if contract in OFFICIAL_ETH_TOKEN_CONTRACTS:
        return OFFICIAL_ETH_TOKEN_CONTRACTS[contract]

    category = str(item.get("category") or "").lower()

    if category in {"external", "internal", "native"} and not contract:
        return "ETH"

    return _raw_asset(item)


def _extract_amount(item: dict) -> Decimal | None:
    raw_contract = item.get("rawContract") or {}
    erc20_transfer = item.get("erc20TokenTransfer") or {}

    value = (
        item.get("value")
        or item.get("amount")
        or item.get("tokenAmount")
        or erc20_transfer.get("value")
        or raw_contract.get("value")
    )

    amount = _decimal(value)

    if amount is not None:
        return amount

    raw_value = (
        raw_contract.get("rawValue")
        or raw_contract.get("value")
        or erc20_transfer.get("rawValue")
        or erc20_transfer.get("value")
    )
    decimals = (
        raw_contract.get("decimals")
        or erc20_transfer.get("decimals")
        or item.get("decimals")
    )

    return _decimal_from_raw(raw_value, decimals)


def _addresses_match(left: str | None, right: str | None) -> bool:
    return _lower(left) == _lower(right)


def _amount_matches(order_amount: Any, received_amount: Decimal | None) -> bool:
    if received_amount is None or order_amount is None:
        return True

    expected = _decimal(order_amount)

    if expected is None:
        return True

    return expected == received_amount


def _order_wallet(order: PaymentOrder) -> str:
    return (
        getattr(order, "treasury_wallet_address", None)
        or order.user_wallet_address
        or ETHEREUM_LEDGER_WALLET
    )


async def process_alchemy_webhook(db: AsyncSession, payload: dict) -> int:
    processed = 0
    items = _get_activity_items(payload)

    if not items:
        await log_event(
            db,
            "ALCHEMY_WEBHOOK_EMPTY_ACTIVITY",
            {"payload": payload},
            None,
        )
        return processed

    for item in items:
        network = _extract_network(payload, item)
        to_address = _extract_to_address(item)
        from_address = _extract_from_address(item)
        contract_address = _extract_contract_address(item)
        tx_hash = _extract_tx_hash(item)
        asset = _normalized_asset(item, contract_address)
        amount = _extract_amount(item)
        category = str(item.get("category") or "").lower()

        event_details = {
            "network": network.value,
            "to_address": to_address,
            "from_address": from_address,
            "contract_address": contract_address,
            "raw_asset": _raw_asset(item),
            "asset": asset,
            "amount": str(amount) if amount is not None else None,
            "display_amount": f"{amount:f}" if amount is not None else None,
            "category": category,
            "tx_hash": tx_hash,
        }

        await log_event(db, "ALCHEMY_ACTIVITY_RECEIVED", event_details, None)

        if not to_address:
            await log_event(
                db,
                "ALCHEMY_ACTIVITY_SKIPPED_NO_TO_ADDRESS",
                event_details,
                None,
            )
            continue

        contract = _lower(contract_address)
        is_token_transfer = bool(contract) or category == "token"

        if is_token_transfer and contract not in OFFICIAL_ETH_TOKEN_CONTRACTS:
            await log_event(
                db,
                "ALCHEMY_UNSUPPORTED_TOKEN_CONTRACT",
                {
                    **event_details,
                    "reason": "Only official Ethereum/Base USDT and USDC contracts are accepted.",
                    "official_usdt_contract": ETHEREUM_USDT_CONTRACT,
                    "official_usdc_contract": ETHEREUM_USDC_CONTRACT,
                    "official_base_usdc_contract": BASE_USDC_CONTRACT,
                    "raw": item,
                },
                None,
            )
            continue

        if asset not in SUPPORTED_ETH_ASSETS:
            await log_event(
                db,
                "ALCHEMY_UNSUPPORTED_ASSET",
                {
                    **event_details,
                    "raw": item,
                },
                None,
            )
            continue

        result = await db.execute(
            select(PaymentOrder)
            .where(
                PaymentOrder.network == network,
                PaymentOrder.status.in_(
                    [
                        OrderStatus.CREATED,
                        OrderStatus.PENDING,
                        OrderStatus.PROCESSING,
                    ]
                ),
            )
            .order_by(PaymentOrder.created_at.desc())
        )

        orders = list(result.scalars().all())
        matched_order: PaymentOrder | None = None
        wallet_currency_matches: list[PaymentOrder] = []

        for order in orders:
            treasury_match = _addresses_match(_order_wallet(order), to_address)
            currency_match = asset == str(order.crypto_currency).upper()

            if treasury_match and currency_match:
                wallet_currency_matches.append(order)

                if _amount_matches(order.crypto_amount, amount):
                    matched_order = order
                    break

        if not matched_order and len(wallet_currency_matches) == 1:
            matched_order = wallet_currency_matches[0]

        if not matched_order:
            await log_event(
                db,
                "ALCHEMY_PAYMENT_NOT_MATCHED",
                {
                    **event_details,
                    "raw": item,
                },
                None,
            )
            continue

        matched_order.status = OrderStatus.COMPLETED
        matched_order.webhook_payload = payload

        if amount is not None and matched_order.crypto_amount is None:
            matched_order.crypto_amount = amount

        if tx_hash and hasattr(matched_order, "tx_hash"):
            matched_order.tx_hash = tx_hash

        await db.commit()
        await db.refresh(matched_order)

        await log_event(
            db,
            "ALCHEMY_PAYMENT_CONFIRMED",
            {
                **event_details,
                "order_id": str(matched_order.id),
            },
            matched_order.id,
            client_id=getattr(matched_order, "client_id", None),
        )

        processed += 1

    return processed
