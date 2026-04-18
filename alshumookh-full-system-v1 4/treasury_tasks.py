"""Treasury background tasks."""

import asyncio
import structlog

logger = structlog.get_logger()


def check_and_sweep():
    from app.app.treasury import TreasuryService
    asyncio.run(TreasuryService.check_and_sweep())
