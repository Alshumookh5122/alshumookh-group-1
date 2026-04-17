"""Payments Router — create, retrieve, list, and cancel payments."""

from decimal import Decimal
from typing import List, Optional
import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, update, and_

from app.app.config import settings
from app.app.database import get_db
from app.app.deps import get_current_active_user, get_client_ip
from app.app.models import Payment, PaymentStatus, PaymentType, AuditLog, AuditAction, User
from app.app.schemas import (
    CreatePaymentRequest, PaymentResponse, PaymentListResponse, CancelPaymentRequest
)
from app.app.provider_service import ProviderService
from app.app.utils import calc_offset, calc_pages, generate_qr_code_base64, generate_crypto_payment_uri
import structlog

logger = structlog.get_logger()
router = APIRouter(prefix="/api/v1/payments", tags=["Payments"])


@router.post("/", response_model=PaymentResponse, status_code=status.HTTP_201_CREATED)
async def create_payment(
    data: CreatePaymentRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    if data.payment_type == PaymentType.FIAT:
        if data.amount < Decimal(str(settings.MIN_FIAT_AMOUNT_USD)):
            raise HTTPException(400, f"Minimum payment: ${settings.MIN_FIAT_AMOUNT_USD}")
        if data.amount > Decimal(str(settings.MAX_FIAT_AMOUNT_USD)):
            raise HTTPException(400, f"Maximum payment: ${settings.MAX_FIAT_AMOUNT_USD}")

    if data.payment_type == PaymentType.CRYPTO:
        if data.token_symbol not in settings.SUPPORTED_TOKEN_LIST:
            raise HTTPException(400, f"Unsupported token. Supported: {settings.SUPPORTED_TOKEN_LIST}")

    ip = get_client_ip(request)
    payment = await ProviderService.create_payment(db, current_user.id, data, ip)
    db.add(AuditLog(
        user_id=current_user.id,
        action=AuditAction.PAYMENT_CREATED,
        resource_type="payment",
        resource_id=payment.id,
        details={"reference": payment.reference, "amount": str(payment.amount), "type": payment.payment_type.value},
        ip_address=ip,
    ))
    await db.commit()
    return payment


@router.get("/", response_model=PaymentListResponse)
async def list_payments(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    payment_status: Optional[PaymentStatus] = None,
    payment_type: Optional[PaymentType] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    filters = [Payment.user_id == current_user.id]
    if payment_status:
        filters.append(Payment.status == payment_status)
    if payment_type:
        filters.append(Payment.payment_type == payment_type)

    count_result = await db.execute(select(func.count(Payment.id)).where(and_(*filters)))
    total = count_result.scalar_one()

    result = await db.execute(
        select(Payment).where(and_(*filters))
        .order_by(Payment.created_at.desc())
        .offset(calc_offset(page, per_page))
        .limit(per_page)
    )
    items = result.scalars().all()
    return PaymentListResponse(items=items, total=total, page=page, per_page=per_page, pages=calc_pages(total, per_page))


@router.get("/{payment_id}", response_model=PaymentResponse)
async def get_payment(
    payment_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    result = await db.execute(
        select(Payment).where(
            Payment.user_id == current_user.id,
            (Payment.id == payment_id) | (Payment.reference == payment_id),
        )
    )
    payment = result.scalar_one_or_none()
    if not payment:
        raise HTTPException(404, "Payment not found")

    if (payment.status == PaymentStatus.AWAITING_PAYMENT and payment.expires_at
            and payment.expires_at < datetime.datetime.utcnow()):
        await db.execute(update(Payment).where(Payment.id == payment.id).values(status=PaymentStatus.EXPIRED))
        await db.commit()
        await db.refresh(payment)
    return payment


@router.get("/{payment_id}/qr")
async def get_payment_qr(
    payment_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    result = await db.execute(
        select(Payment).where(
            Payment.id == payment_id,
            Payment.user_id == current_user.id,
            Payment.payment_type == PaymentType.CRYPTO,
        )
    )
    payment = result.scalar_one_or_none()
    if not payment:
        raise HTTPException(404, "Crypto payment not found")

    uri = generate_crypto_payment_uri(payment.deposit_address, payment.token_symbol, payment.amount)
    return {
        "qr_code_base64": generate_qr_code_base64(uri),
        "payment_uri": uri,
        "address": payment.deposit_address,
        "amount": str(payment.amount),
        "token": payment.token_symbol,
    }


@router.post("/{payment_id}/cancel", response_model=PaymentResponse)
async def cancel_payment(
    payment_id: str,
    data: CancelPaymentRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    result = await db.execute(
        select(Payment).where(Payment.id == payment_id, Payment.user_id == current_user.id)
    )
    payment = result.scalar_one_or_none()
    if not payment:
        raise HTTPException(404, "Payment not found")

    if payment.status not in {PaymentStatus.PENDING, PaymentStatus.AWAITING_PAYMENT}:
        raise HTTPException(400, f"Cannot cancel payment in status: {payment.status.value}")

    if payment.provider_payment_id and payment.payment_type == PaymentType.FIAT:
        try:
            import stripe
            stripe.api_key = settings.STRIPE_SECRET_KEY
            stripe.PaymentIntent.cancel(payment.provider_payment_id)
        except Exception as e:
            logger.warning("stripe.cancel_failed", error=str(e))

    await db.execute(update(Payment).where(Payment.id == payment.id).values(status=PaymentStatus.CANCELLED))
    db.add(AuditLog(user_id=current_user.id, action=AuditAction.PAYMENT_CANCELLED,
                    resource_type="payment", resource_id=payment.id, details={"reason": data.reason}))
    await db.commit()
    await db.refresh(payment)
    return payment
