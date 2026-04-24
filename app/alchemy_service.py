from __future__ import annotations

import hashlib
import hmac
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit_service import log_event
from app.config import settings
from app.models import Network, OrderStatus, PaymentOrder


def verify_alchemy_signature(raw_body: bytes, signature: str | None) -> bool:
    signing_key = getattr(settings, "alchemy_webhook_signing_key", None)

    if not signing_key:
        return True

    if not signature:
        return False

    expected = hmac.new(
        signing_key.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).hexdigest()

    received = signature.replace("sha256=", "").strip()

    return hmac.compare_digest(expected, received)


def _lower(value: str | None) -> str:
    return str(value or "").lower()


def _decimal(value) -> Decimal | None:
    try:
        if value is None:
            return None
        return Decimal(str(value))
    except Exception:
        return None


def _get_activity_items(payload: dict) -> list[dict]:
    event = payload.get("event") or {}
    activity = event.get("activity") or payload.get("activity") or []

    if isinstance(activity, list):
        return activity

    if isinstance(activity, dict):
        return [activity]

    return []


def _extract_tx_hash(item: dict) -> str | None:
    return (
        item.get("hash")
        or item.get("txHash")
        or item.get("transactionHash")
        or item.get("transaction_hash")
    )


def _extract_to_address(item: dict) -> str | None:
    return (
        item.get("toAddress")
        or item.get("to")
        or item.get("recipient")
        or item.get("rawContract", {}).get("address")
    )


def _extract_from_address(item: dict) -> str | None:
    return item.get("fromAddress") or item.get("from") or item.get("sender")


def _extract_asset(item: dict) -> str:
    return str(
        item.get("asset")
        or item.get("tokenSymbol")
        or item.get("symbol")
        or ""
    ).upper()


def _extract_amount(item: dict) -> Decimal | None:
    value = (
        item.get("value")
        or item.get("amount")
        or item.get("tokenAmount")
        or item.get("erc20TokenTransfer", {}).get("value")
    )
    return _decimal(value)


async def process_alchemy_webhook(db: AsyncSession, payload: dict) -> int:
    processed = 0
    items = _get_activity_items(payload)

    for item in items:
        to_address = _extract_to_address(item)
        from_address = _extract_from_address(item)
        tx_hash = _extract_tx_hash(item)
        asset = _extract_asset(item)
        amount = _extract_amount(item)

        if not to_address:
            continue

        result = await db.execute(
            select(PaymentOrder)
            .where(
                PaymentOrder.network == Network.ETHEREUM,
                PaymentOrder.treasury_wallet_address.is_not(None),
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

        for order in orders:
            treasury_match = _lower(order.treasury_wallet_address) == _lower(to_address)

            currency_match = (
                not asset
                or asset == str(order.crypto_currency).upper()
            )

            amount_match = (
                amount is None
                or order.crypto_amount is None
                or amount == Decimal(str(order.crypto_amount))
            )

            if treasury_match and currency_match and amount_match:
                matched_order = order
                break

        if not matched_order:
            await log_event(
                db,
                "ALCHEMY_PAYMENT_NOT_MATCHED",
                {
                    "to_address": to_address,
                    "from_address": from_address,
                    "asset": asset,
                    "amount": str(amount) if amount is not None else None,
                    "tx_hash": tx_hash,
                    "raw": item,
                },
                None,
            )
            continue

        matched_order.status = OrderStatus.COMPLETED
        matched_order.tx_hash = tx_hash
        matched_order.webhook_payload = payload

        await log_event(
            db,
            "ALCHEMY_PAYMENT_CONFIRMED",
            {
                "order_id": str(matched_order.id),
                "to_address": to_address,
                "from_address": from_address,
                "asset": asset,
                "amount": str(amount) if amount is not None else None,
                "tx_hash": tx_hash,
            },
            matched_order.id,
        )

        processed += 1

    await db.commit()
    return processed
