"""
Matching Service — correlates incoming blockchain transactions
with pending payment records using address + amount matching.
"""

from decimal import Decimal
from typing import Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
import datetime
import structlog

from app.app.models import (
    Payment, PaymentStatus, BlockchainTransaction,
    TransactionDirection, AuditLog, AuditAction
)

logger = structlog.get_logger()


class MatchingService:
    """
    Core matching engine.
    On receipt of an Alchemy ADDRESS_ACTIVITY webhook, this service:
    1. Finds the pending payment for the destination address
    2. Validates amount (with tolerance for gas/rounding)
    3. Updates payment status and records the transaction
    4. Triggers confirmation polling via Celery
    """

    AMOUNT_TOLERANCE = Decimal("0.001")  # 0.1% tolerance

    @classmethod
    async def process_incoming_transfer(
        cls,
        db: AsyncSession,
        to_address: str,
        from_address: str,
        amount: Decimal,
        token_symbol: str,
        tx_hash: str,
        block_number: Optional[int],
        network: str,
        raw_data: Dict[str, Any],
    ) -> Optional[Payment]:
        """
        Match a detected transfer to a pending payment.
        Returns the matched Payment or None.
        """
        logger.info(
            "matching.processing",
            to_address=to_address[:10],
            amount=str(amount),
            token=token_symbol,
            tx_hash=tx_hash[:12],
        )

        # 1. Find pending payment for this address
        result = await db.execute(
            select(Payment).where(
                Payment.deposit_address == to_address,
                Payment.token_symbol == token_symbol,
                Payment.status.in_([PaymentStatus.AWAITING_PAYMENT, PaymentStatus.PENDING]),
            )
        )
        payment = result.scalar_one_or_none()

        if not payment:
            logger.info("matching.no_payment_found", to_address=to_address)
            # Still record the transaction as unmatched
            await cls._record_transaction(
                db, None, tx_hash, from_address, to_address,
                amount, token_symbol, network, block_number,
                TransactionDirection.INBOUND, raw_data
            )
            return None

        # 2. Check expiry
        if payment.expires_at and payment.expires_at < datetime.datetime.utcnow():
            logger.warning("matching.payment_expired", payment_id=payment.id)
            await db.execute(
                update(Payment)
                .where(Payment.id == payment.id)
                .values(status=PaymentStatus.EXPIRED)
            )
            return None

        # 3. Validate amount
        expected = payment.amount
        if not cls._amount_matches(amount, expected):
            logger.warning(
                "matching.amount_mismatch",
                expected=str(expected),
                received=str(amount),
                payment_id=payment.id,
            )
            # Still update to processing but flag for review
            # In production you may want partial payment handling

        # 4. Check for duplicate tx
        dup = await db.execute(
            select(BlockchainTransaction).where(
                BlockchainTransaction.tx_hash == tx_hash
            )
        )
        if dup.scalar_one_or_none():
            logger.warning("matching.duplicate_tx", tx_hash=tx_hash)
            return payment

        # 5. Update payment → CONFIRMING
        await db.execute(
            update(Payment)
            .where(Payment.id == payment.id)
            .values(
                status=PaymentStatus.CONFIRMING,
                tx_hash=tx_hash,
                block_number=block_number,
                network=network,
                confirmation_count=0,
            )
        )

        # 6. Record blockchain transaction
        await cls._record_transaction(
            db, payment.id, tx_hash, from_address, to_address,
            amount, token_symbol, network, block_number,
            TransactionDirection.INBOUND, raw_data
        )

        # 7. Audit log
        db.add(AuditLog(
            user_id=payment.user_id,
            action=AuditAction.WEBHOOK_RECEIVED,
            resource_type="payment",
            resource_id=payment.id,
            details={
                "tx_hash": tx_hash,
                "amount": str(amount),
                "token": token_symbol,
                "from": from_address,
            },
        ))

        await db.commit()

        # 8. Enqueue Celery task for confirmation polling
        try:
            from worker import confirm_crypto_transaction
            confirm_crypto_transaction.apply_async(
                args=[payment.id, tx_hash],
                countdown=30,  # Start after 30s
            )
        except Exception as e:
            logger.warning("matching.celery_enqueue_failed", error=str(e))

        logger.info("matching.payment_matched", payment_id=payment.id, tx_hash=tx_hash)
        return payment

    @classmethod
    def _amount_matches(cls, received: Decimal, expected: Decimal) -> bool:
        if expected == 0:
            return False
        diff = abs(received - expected) / expected
        return diff <= cls.AMOUNT_TOLERANCE

    @staticmethod
    async def _record_transaction(
        db: AsyncSession,
        payment_id: Optional[str],
        tx_hash: str,
        from_address: str,
        to_address: str,
        amount: Decimal,
        token_symbol: str,
        network: str,
        block_number: Optional[int],
        direction: TransactionDirection,
        raw_data: Dict[str, Any],
    ) -> BlockchainTransaction:
        tx_record = BlockchainTransaction(
            payment_id=payment_id,
            tx_hash=tx_hash,
            from_address=from_address,
            to_address=to_address,
            amount=amount,
            token_symbol=token_symbol,
            network=network,
            block_number=block_number,
            direction=direction,
            raw_data=raw_data,
        )
        db.add(tx_record)
        await db.flush()
        return tx_record
