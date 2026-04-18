"""Reconciliation background tasks."""

import asyncio
import structlog

logger = structlog.get_logger()


def run_daily_reconciliation():
    from app.app.reconciliation_service import ReconciliationService
    asyncio.run(ReconciliationService.run_daily_reconciliation())
