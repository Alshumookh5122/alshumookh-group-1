from celery import shared_task

from app.config import get_settings

settings = get_settings()


@shared_task(name="app.tasks.reconcile.run")
def run_reconcile_task() -> dict:
    return {
        "status": "queued",
        "service": settings.app_name,
        "note": (
            "Periodic reconciliation placeholder. "
            "MoonPay/Coinbase provider orders are updated by provider webhooks. "
            "Ledger direct orders are updated by Alchemy webhooks or manual admin confirmation."
        ),
    }
