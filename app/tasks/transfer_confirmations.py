from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from web3.exceptions import TransactionNotFound

from app.audit_service import log_event
from app.config import get_settings
from app.database import AsyncSessionLocal
from app.models import ExternalPayload, OutboundTransfer, OutboundTransferStatus
from app.notification_service import notify_transfer_completed, notify_transfer_failed
from app.transfer_service import base_client, ethereum_mainnet_client

log = logging.getLogger(__name__)
settings = get_settings()


def _receipt_value(receipt: Any, key: str) -> Any:
    if receipt is None:
        return None
    if isinstance(receipt, dict):
        return receipt.get(key)
    return getattr(receipt, key, None)


def _web3_for_network(network: str):
    normalized = (network or "ethereum").strip().lower()
    if normalized in {"ethereum", "eth", "erc20"}:
        return ethereum_mainnet_client(), "https://etherscan.io/tx/"
    if normalized == "base":
        return base_client(), "https://basescan.org/tx/"
    raise ValueError(f"Confirmation monitor does not support network: {network}")


async def _link_confirmed_transfer_to_payload(db, transfer: OutboundTransfer) -> None:
    if not transfer.payload_id:
        return

    result = await db.execute(select(ExternalPayload).where(ExternalPayload.id == transfer.payload_id))
    payload = result.scalar_one_or_none()
    if not payload:
        return

    payload.tx_hash = transfer.tx_hash
    payload.block_number = transfer.block_number
    payload.confirmations = transfer.confirmations
    payload.blockchain_result = {
        **(payload.blockchain_result or {}),
        "outbound_transfer_id": transfer.id,
        "tx_hash": transfer.tx_hash,
        "asset": transfer.asset,
        "network": transfer.network,
        "status": "CONFIRMED",
        "block_number": transfer.block_number,
        "confirmations": transfer.confirmations,
        "explorer_url": transfer.explorer_url,
        "confirmed_at": datetime.now(timezone.utc).isoformat(),
    }


async def check_pending_transfer_confirmations_once(limit: int = 100) -> int:
    """
    Check pending outbound transfers once and update confirmed/failed records.
    Returns the number of transfer rows inspected.
    """
    required = max(1, int(settings.transfer_confirmations_required or 12))
    inspected = 0

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(OutboundTransfer)
            .where(OutboundTransfer.status == OutboundTransferStatus.PENDING_CONFIRMATION.value)
            .where(OutboundTransfer.tx_hash.is_not(None))
            .order_by(OutboundTransfer.broadcasted_at.asc().nulls_last(), OutboundTransfer.created_at.asc())
            .limit(limit)
        )
        transfers = result.scalars().all()

        for transfer in transfers:
            inspected += 1
            try:
                client, explorer_base = _web3_for_network(transfer.network)
                current_block = int(client.eth.block_number)
                receipt = client.eth.get_transaction_receipt(transfer.tx_hash)
                block_number = _receipt_value(receipt, "blockNumber")
                status = _receipt_value(receipt, "status")
                gas_used = _receipt_value(receipt, "gasUsed")

                if block_number is None:
                    continue

                block_number = int(block_number)
                confirmations = max(0, current_block - block_number + 1)

                transfer.block_number = block_number
                transfer.confirmations = confirmations
                transfer.gas_used = int(gas_used) if gas_used is not None else transfer.gas_used
                if transfer.tx_hash and not transfer.explorer_url:
                    transfer.explorer_url = f"{explorer_base}{transfer.tx_hash}"

                if status is not None and int(status) == 0:
                    transfer.status = OutboundTransferStatus.FAILED.value
                    transfer.error_message = "On-chain transaction failed"
                    await db.commit()
                    await log_event(
                        db,
                        "OUTBOUND_TRANSFER_CHAIN_FAILED",
                        {
                            "transfer_id": transfer.id,
                            "tx_hash": transfer.tx_hash,
                            "network": transfer.network,
                            "block_number": block_number,
                            "confirmations": confirmations,
                        },
                        transfer.order_id,
                    )
                    webhook_result = await notify_transfer_failed(
                        transfer.callback_url,
                        transfer.id,
                        "On-chain transaction failed",
                        str(transfer.amount),
                        transfer.network,
                    )
                    transfer.webhook_sent_at = datetime.now(timezone.utc) if webhook_result else transfer.webhook_sent_at
                    transfer.webhook_status_code = (
                        webhook_result.get("status_code") if webhook_result else transfer.webhook_status_code
                    )
                    await db.commit()
                    continue

                if confirmations >= required:
                    transfer.status = OutboundTransferStatus.CONFIRMED.value
                    transfer.completed_at = datetime.now(timezone.utc)
                    transfer.error_message = None
                    await _link_confirmed_transfer_to_payload(db, transfer)
                    await db.commit()
                    await db.refresh(transfer)

                    await log_event(
                        db,
                        "OUTBOUND_TRANSFER_CONFIRMED",
                        {
                            "transfer_id": transfer.id,
                            "tx_hash": transfer.tx_hash,
                            "asset": transfer.asset,
                            "network": transfer.network,
                            "block_number": transfer.block_number,
                            "confirmations": transfer.confirmations,
                        },
                        transfer.order_id,
                    )
                    webhook_result = await notify_transfer_completed(
                        transfer.callback_url,
                        transfer.id,
                        transfer.tx_hash,
                        str(transfer.amount),
                        transfer.network,
                        transfer.to_address,
                        transfer.explorer_url,
                        asset=transfer.asset,
                    )
                    transfer.webhook_sent_at = datetime.now(timezone.utc) if webhook_result else transfer.webhook_sent_at
                    transfer.webhook_status_code = (
                        webhook_result.get("status_code") if webhook_result else transfer.webhook_status_code
                    )
                    await db.commit()
                else:
                    await db.commit()
            except TransactionNotFound:
                log.info("Transfer tx not found yet: %s", transfer.tx_hash)
            except Exception as exc:
                await db.rollback()
                log.exception("Transfer confirmation check failed for %s: %s", transfer.id, exc)
                try:
                    await log_event(
                        db,
                        "OUTBOUND_TRANSFER_CONFIRMATION_CHECK_FAILED",
                        {
                            "transfer_id": transfer.id,
                            "tx_hash": transfer.tx_hash,
                            "network": transfer.network,
                            "error": str(exc),
                        },
                        transfer.order_id,
                    )
                except Exception:
                    log.exception("Failed to write confirmation monitor audit log")

    return inspected


async def transfer_confirmation_monitor_loop() -> None:
    interval = max(10, int(settings.transfer_confirmation_interval_seconds or 60))
    log.info("Outbound transfer confirmation monitor started; interval=%ss", interval)
    while True:
        try:
            await check_pending_transfer_confirmations_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Outbound transfer confirmation monitor iteration failed")
        await asyncio.sleep(interval)
