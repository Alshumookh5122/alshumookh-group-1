import logging
from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


def notify_ops(subject: str, body: str) -> None:
    logger.info('notify_ops subject=%s body=%s to=%s', subject, body, settings.notify_to_email)
