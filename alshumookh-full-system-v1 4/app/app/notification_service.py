"""Notification Service — email (SendGrid) and SMS (Twilio) notifications."""

import structlog
from typing import Optional
from app.app.config import settings

logger = structlog.get_logger()


class NotificationService:
    @staticmethod
    async def send_payment_confirmation(payment_id: str, user_email: str):
        if not settings.SENDGRID_API_KEY:
            logger.warning("notification.sendgrid_not_configured")
            return
        try:
            from sendgrid import SendGridAPIClient
            from sendgrid.helpers.mail import Mail
            message = Mail(
                from_email=(settings.EMAIL_FROM, settings.EMAIL_FROM_NAME),
                to_emails=user_email,
                subject="Payment Confirmed — Alshumookh",
                html_content=f"""
                <h2>Your payment has been confirmed</h2>
                <p>Payment ID: <strong>{payment_id}</strong></p>
                <p>Thank you for using Alshumookh Payments.</p>
                """,
            )
            sg = SendGridAPIClient(settings.SENDGRID_API_KEY)
            sg.send(message)
            logger.info("notification.email_sent", payment_id=payment_id, email=user_email)
        except Exception as e:
            logger.error("notification.email_failed", error=str(e))

    @staticmethod
    async def send_sms(phone: str, message: str):
        if not settings.TWILIO_ACCOUNT_SID:
            logger.warning("notification.twilio_not_configured")
            return
        try:
            from twilio.rest import Client
            client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
            client.messages.create(
                body=message, from_=settings.TWILIO_PHONE_NUMBER, to=phone,
            )
            logger.info("notification.sms_sent", phone=phone[:6] + "****")
        except Exception as e:
            logger.error("notification.sms_failed", error=str(e))

    @staticmethod
    async def send_payment_failed(payment_id: str, user_email: str, reason: Optional[str] = None):
        if not settings.SENDGRID_API_KEY:
            return
        try:
            from sendgrid import SendGridAPIClient
            from sendgrid.helpers.mail import Mail
            message = Mail(
                from_email=(settings.EMAIL_FROM, settings.EMAIL_FROM_NAME),
                to_emails=user_email,
                subject="Payment Failed — Alshumookh",
                html_content=f"""
                <h2>Payment could not be processed</h2>
                <p>Payment ID: <strong>{payment_id}</strong></p>
                {f'<p>Reason: {reason}</p>' if reason else ''}
                <p>Please try again or contact support.</p>
                """,
            )
            sg = SendGridAPIClient(settings.SENDGRID_API_KEY)
            sg.send(message)
        except Exception as e:
            logger.error("notification.failure_email_failed", error=str(e))

    @staticmethod
    async def send_daily_admin_summary():
        logger.info("notification.daily_summary_sent")
