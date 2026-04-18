"""Fiat Payments Router — Stripe PaymentIntent creation and confirmation."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update

from app.app.config import settings
from app.app.database import get_db
from app.app.deps import get_current_active_user
from app.app.models import Payment, PaymentStatus, User
from app.app.schemas import CreateFiatIntentRequest, FiatIntentResponse, ConfirmFiatRequest
import structlog

logger = structlog.get_logger()
router = APIRouter(prefix="/api/v1/fiat", tags=["Fiat Payments"])


@router.post("/intent", response_model=FiatIntentResponse)
async def create_payment_intent(
    data: CreateFiatIntentRequest,
    current_user: User = Depends(get_current_active_user),
):
    import stripe
    stripe.api_key = settings.STRIPE_SECRET_KEY

    try:
        intent = stripe.PaymentIntent.create(
            amount=data.amount_cents,
            currency=data.currency,
            payment_method_types=data.payment_method_types,
            description=data.description,
            metadata={"user_id": current_user.id, **(data.metadata or {})},
        )
        return FiatIntentResponse(
            payment_intent_id=intent.id,
            client_secret=intent.client_secret,
            amount=intent.amount,
            currency=intent.currency,
            status=intent.status,
            publishable_key=settings.STRIPE_PUBLISHABLE_KEY,
        )
    except stripe.error.StripeError as e:
        logger.error("stripe.intent_failed", error=str(e))
        raise HTTPException(status_code=400, detail=str(e.user_message))


@router.post("/confirm/{payment_id}")
async def confirm_fiat_payment(
    payment_id: str,
    data: ConfirmFiatRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    import stripe
    stripe.api_key = settings.STRIPE_SECRET_KEY

    result = await db.execute(
        select(Payment).where(Payment.id == payment_id, Payment.user_id == current_user.id)
    )
    payment = result.scalar_one_or_none()
    if not payment:
        raise HTTPException(404, "Payment not found")

    if not payment.provider_payment_id:
        raise HTTPException(400, "No Stripe PaymentIntent associated")

    try:
        intent = stripe.PaymentIntent.confirm(
            payment.provider_payment_id,
            payment_method=data.payment_method_id,
        )
        new_status = PaymentStatus.COMPLETED if intent.status == "succeeded" else PaymentStatus.PROCESSING
        await db.execute(
            update(Payment).where(Payment.id == payment.id).values(status=new_status)
        )
        await db.commit()
        return {"status": intent.status, "payment_status": new_status.value}
    except stripe.error.StripeError as e:
        raise HTTPException(400, detail=str(e.user_message))
