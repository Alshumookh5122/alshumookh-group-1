"""
Alshumookh — Celery Worker Entry Point
Handles background tasks: tx confirmation polling, notifications,
reconciliation, treasury sweeps, and report generation.
"""

import os
from celery import Celery
from celery.schedules import crontab
from dotenv import load_dotenv

load_dotenv()

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

celery_app = Celery(
    "alshumookh",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=[
        "app.app.tasks.payment_tasks",
        "app.app.tasks.notification_tasks",
        "app.app.tasks.reconciliation_tasks",
        "app.app.tasks.treasury_tasks",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_soft_time_limit=300,   # 5 min soft limit
    task_time_limit=600,        # 10 min hard limit
    result_expires=86400,       # 24 hours
)

# ── Periodic Tasks (Beat) ────────────────────────────────────────────────────
celery_app.conf.beat_schedule = {
    # Poll pending crypto payments every 2 minutes
    "poll-pending-crypto-payments": {
        "task": "app.app.tasks.payment_tasks.poll_pending_crypto_payments",
        "schedule": 120.0,
    },
    # Daily reconciliation at 00:05 UTC
    "daily-reconciliation": {
        "task": "app.app.tasks.reconciliation_tasks.run_daily_reconciliation",
        "schedule": crontab(hour=0, minute=5),
    },
    # Treasury sweep check every 15 minutes
    "treasury-sweep-check": {
        "task": "app.app.tasks.treasury_tasks.check_and_sweep",
        "schedule": 900.0,
    },
    # Expire stale payment addresses every 10 minutes
    "expire-stale-addresses": {
        "task": "app.app.tasks.payment_tasks.expire_stale_payment_addresses",
        "schedule": 600.0,
    },
    # Send daily summary to admins at 08:00 UTC
    "daily-admin-summary": {
        "task": "app.app.tasks.notification_tasks.send_daily_admin_summary",
        "schedule": crontab(hour=8, minute=0),
    },
}


# ── Standalone Tasks (inline for simple deployments) ────────────────────────
@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def send_payment_confirmation_email(self, payment_id: str, user_email: str):
    """Send payment confirmation email."""
    try:
        from app.app.services.notification_service import NotificationService
        import asyncio
        asyncio.run(NotificationService.send_payment_confirmation(payment_id, user_email))
    except Exception as exc:
        raise self.retry(exc=exc)


@celery_app.task(bind=True, max_retries=5, default_retry_delay=30)
def confirm_crypto_transaction(self, payment_id: str, tx_hash: str):
    """Poll blockchain for transaction confirmation."""
    try:
        from app.app.alchemy_service import AlchemyService
        import asyncio
        asyncio.run(AlchemyService.confirm_transaction(payment_id, tx_hash))
    except Exception as exc:
        raise self.retry(exc=exc)


@celery_app.task
def sweep_wallet_to_treasury(wallet_address: str, token: str = "ETH"):
    """Sweep funds from a deposit wallet to the treasury."""
    from app.app.treasury import TreasuryService
    import asyncio
    asyncio.run(TreasuryService.sweep_to_treasury(wallet_address, token))


if __name__ == "__main__":
    celery_app.start()
