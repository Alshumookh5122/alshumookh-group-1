"""
Alshumookh — Celery Worker Entry Point
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
    task_soft_time_limit=300,
    task_time_limit=600,
    result_expires=86400,
)

# Periodic Tasks (Beat)
celery_app.conf.beat_schedule = {
    "poll-pending-crypto-payments": {
        "task": "worker.poll_pending_crypto_payments",
        "schedule": 120.0,
    },
    "daily-reconciliation": {
        "task": "worker.run_daily_reconciliation",
        "schedule": crontab(hour=0, minute=5),
    },
    "treasury-sweep-check": {
        "task": "worker.check_and_sweep_treasury",
        "schedule": 900.0,
    },
    "expire-stale-addresses": {
        "task": "worker.expire_stale_payments",
        "schedule": 600.0,
    },
    "daily-admin-summary": {
        "task": "worker.send_admin_summary",
        "schedule": crontab(hour=8, minute=0),
    },
}


@celery_app.task(bind=True, name="worker.send_payment_confirmation_email", max_retries=3, default_retry_delay=60)
def send_payment_confirmation_email(self, payment_id: str, user_email: str):
    try:
        from app.app.notification_service import NotificationService
        import asyncio
        asyncio.run(NotificationService.send_payment_confirmation(payment_id, user_email))
    except Exception as exc:
        raise self.retry(exc=exc)


@celery_app.task(bind=True, name="worker.confirm_crypto_transaction", max_retries=5, default_retry_delay=30)
def confirm_crypto_transaction(self, payment_id: str, tx_hash: str):
    try:
        from app.app.alchemy_service import AlchemyService
        import asyncio
        asyncio.run(AlchemyService.confirm_transaction(payment_id, tx_hash))
    except Exception as exc:
        raise self.retry(exc=exc)


@celery_app.task(name="worker.sweep_wallet_to_treasury")
def sweep_wallet_to_treasury(wallet_address: str, token: str = "ETH"):
    from app.app.treasury import TreasuryService
    import asyncio
    asyncio.run(TreasuryService.sweep_to_treasury(wallet_address, token))


@celery_app.task(name="worker.poll_pending_crypto_payments")
def poll_pending_crypto_payments():
    from app.app.tasks.payment_tasks import poll_pending_crypto_payments as _poll
    _poll()


@celery_app.task(name="worker.run_daily_reconciliation")
def run_daily_reconciliation():
    from app.app.tasks.reconciliation_tasks import run_daily_reconciliation as _run
    _run()


@celery_app.task(name="worker.check_and_sweep_treasury")
def check_and_sweep_treasury():
    from app.app.tasks.treasury_tasks import check_and_sweep as _sweep
    _sweep()


@celery_app.task(name="worker.expire_stale_payments")
def expire_stale_payments():
    from app.app.tasks.payment_tasks import expire_stale_payment_addresses as _expire
    _expire()


@celery_app.task(name="worker.send_admin_summary")
def send_admin_summary():
    from app.app.tasks.notification_tasks import send_daily_admin_summary as _send
    _send()


if __name__ == "__main__":
    celery_app.start()
