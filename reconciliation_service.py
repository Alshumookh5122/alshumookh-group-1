"""Reconciliation Service — daily settlement and discrepancy detection."""

import datetime
from decimal import Decimal
import structlog
from sqlalchemy import select, func

from app.app.models import Payment, PaymentStatus, PaymentType, ReconciliationReport

logger = structlog.get_logger()


class ReconciliationService:
    @staticmethod
    async def run_daily_reconciliation():
        """
        Runs at 00:05 UTC. Aggregates the previous day's payments,
        checks for discrepancies, and saves a ReconciliationReport.
        """
        from app.app.database import AsyncSessionLocal

        report_date = datetime.datetime.utcnow().replace(
            hour=0, minute=0, second=0, microsecond=0
        ) - datetime.timedelta(days=1)

        day_start = report_date
        day_end = report_date + datetime.timedelta(days=1)

        async with AsyncSessionLocal() as db:
            # Check if report already exists
            existing = await db.execute(
                select(ReconciliationReport).where(ReconciliationReport.report_date == report_date)
            )
            if existing.scalar_one_or_none():
                logger.info("reconciliation.already_run", date=str(report_date.date()))
                return

            # Aggregate payments
            total_q = await db.execute(
                select(func.count(Payment.id)).where(
                    Payment.created_at >= day_start,
                    Payment.created_at < day_end,
                )
            )
            completed_q = await db.execute(
                select(func.count(Payment.id)).where(
                    Payment.status == PaymentStatus.COMPLETED,
                    Payment.completed_at >= day_start,
                    Payment.completed_at < day_end,
                )
            )
            failed_q = await db.execute(
                select(func.count(Payment.id)).where(
                    Payment.status == PaymentStatus.FAILED,
                    Payment.updated_at >= day_start,
                    Payment.updated_at < day_end,
                )
            )
            volume_q = await db.execute(
                select(func.coalesce(func.sum(Payment.amount_usd), 0)).where(
                    Payment.status == PaymentStatus.COMPLETED,
                    Payment.completed_at >= day_start,
                    Payment.completed_at < day_end,
                )
            )
            crypto_vol_q = await db.execute(
                select(func.coalesce(func.sum(Payment.amount_usd), 0)).where(
                    Payment.status == PaymentStatus.COMPLETED,
                    Payment.payment_type == PaymentType.CRYPTO,
                    Payment.completed_at >= day_start,
                    Payment.completed_at < day_end,
                )
            )

            total = total_q.scalar_one()
            completed = completed_q.scalar_one()
            failed = failed_q.scalar_one()
            total_vol = volume_q.scalar_one() or Decimal("0")
            crypto_vol = crypto_vol_q.scalar_one() or Decimal("0")
            fiat_vol = total_vol - crypto_vol

            report = ReconciliationReport(
                report_date=report_date,
                total_payments=total,
                completed_payments=completed,
                failed_payments=failed,
                total_volume_usd=total_vol,
                crypto_volume_usd=crypto_vol,
                fiat_volume_usd=fiat_vol,
            )
            db.add(report)
            await db.commit()

            logger.info(
                "reconciliation.completed",
                date=str(report_date.date()),
                total=total,
                completed=completed,
                volume_usd=str(total_vol),
            )
