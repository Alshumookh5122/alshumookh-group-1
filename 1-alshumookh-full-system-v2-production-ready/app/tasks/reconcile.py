from celery import shared_task
from app.config import get_settings

settings = get_settings()


@shared_task(name='app.tasks.reconcile.run')
def run_reconcile_task() -> dict:
    return {'status': 'queued', 'note': 'Wire DB session + reconcile service here for periodic jobs'}
