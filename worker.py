from celery import Celery
from app.config import get_settings

settings = get_settings()
celery_app = Celery('alshumookh_global_banking_finance_credit', broker=settings.celery_broker_url, backend=settings.celery_result_backend)
celery_app.conf.task_default_queue = 'default'
celery_app.autodiscover_tasks(['app.tasks'])
