"""Admin Router — user management, stats, and system oversight."""

from decimal import Decimal
from typing import List, Optional
import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, update, and_

from app.app.config import settings
from app.app.database import get_db
from app.app.deps import require_admin
from app.app.models import User, Payment, PaymentStatus, PaymentType, AuditLog, AuditAction, UserStatus
from app.app.schemas import AdminStatsResponse, AdminUserUpdate, UserResponse, PaymentResponse
from app.app.treasury import TreasuryService
import structlog

logger = structlog.get_logger()
router = APIRouter(prefix="/api/v1/admin", tags=["Admin"])


@router.get("/stats", response_model=AdminStatsResponse)
async def get_admin_stats(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    now = datetime.datetime.utcnow()
    day_ago = now - datetime.timedelta(days=1)
    week_ago = now - datetime.timedelta(days=7)
    month_ago = now - datetime.timedelta(days=30)

    total_users = (await db.execute(select(func.count(User.id)))).scalar_one()
    active_users = (await db.execute(
        select(func.count(User.id)).where(User.status == UserStatus.ACTIVE)
    )).scalar_one()

    total_payments = (await db.execute(select(func.count(Payment.id)))).scalar_one()
    pending_payments = (await db.execute(
        select(func.count(Payment.id)).where(Payment.status.in_([
            PaymentStatus.PENDING, PaymentStatus.AWAITING_PAYMENT, PaymentStatus.CONFIRMING
        ]))
    )).scalar_one()

    completed_24h = (await db.execute(
        select(func.count(Payment.id)).where(
            Payment.status == PaymentStatus.COMPLETED,
            Payment.completed_at >= day_ago,
        )
    )).scalar_one()

    async def volume_usd(since: datetime.datetime) -> Decimal:
        result = await db.execute(
            select(func.coalesce(func.sum(Payment.amount_usd), 0)).where(
                Payment.status == PaymentStatus.COMPLETED,
                Payment.completed_at >= since,
            )
        )
        return result.scalar_one() or Decimal("0")

    vol_24h = await volume_usd(day_ago)
    vol_7d = await volume_usd(week_ago)
    vol_30d = await volume_usd(month_ago)

    crypto_vol = (await db.execute(
        select(func.coalesce(func.sum(Payment.amount_usd), 0)).where(
            Payment.status == PaymentStatus.COMPLETED,
            Payment.payment_type == PaymentType.CRYPTO,
            Payment.completed_at >= month_ago,
        )
    )).scalar_one() or Decimal("0")

    fiat_vol = vol_30d - crypto_vol
    crypto_ratio = float(crypto_vol / vol_30d) if vol_30d > 0 else 0.0
    fiat_ratio = 1.0 - crypto_ratio

    try:
        treasury_usd = await TreasuryService.get_total_usd_value()
    except Exception:
        treasury_usd = Decimal("0")

    return AdminStatsResponse(
        total_users=total_users,
        active_users=active_users,
        total_payments=total_payments,
        pending_payments=pending_payments,
        completed_payments_24h=completed_24h,
        volume_24h_usd=vol_24h,
        volume_7d_usd=vol_7d,
        volume_30d_usd=vol_30d,
        crypto_volume_ratio=crypto_ratio,
        fiat_volume_ratio=fiat_ratio,
        treasury_balance_usd=treasury_usd,
    )


@router.get("/users", response_model=List[UserResponse])
async def list_users(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    search: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    filters = []
    if search:
        filters.append(User.email.ilike(f"%{search}%"))

    offset = (page - 1) * per_page
    result = await db.execute(
        select(User)
        .where(and_(*filters) if filters else True)
        .order_by(User.created_at.desc())
        .offset(offset).limit(per_page)
    )
    return result.scalars().all()


@router.patch("/users/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: str,
    data: AdminUserUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(404, "User not found")

    update_data = data.model_dump(exclude_none=True)
    if update_data:
        await db.execute(update(User).where(User.id == user_id).values(**update_data))

    db.add(AuditLog(
        user_id=current_user.id,
        action=AuditAction.ADMIN_ACTION,
        resource_type="user",
        resource_id=user_id,
        details={"changes": update_data},
    ))
    await db.commit()
    await db.refresh(user)
    return user


@router.post("/users/{user_id}/suspend")
async def suspend_user(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    await db.execute(update(User).where(User.id == user_id).values(status=UserStatus.SUSPENDED))
    db.add(AuditLog(
        user_id=current_user.id,
        action=AuditAction.USER_SUSPENDED,
        resource_type="user",
        resource_id=user_id,
    ))
    await db.commit()
    return {"status": "suspended"}


@router.get("/payments", response_model=List[PaymentResponse])
async def list_all_payments(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    payment_status: Optional[PaymentStatus] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    filters = []
    if payment_status:
        filters.append(Payment.status == payment_status)

    offset = (page - 1) * per_page
    result = await db.execute(
        select(Payment)
        .where(and_(*filters) if filters else True)
        .order_by(Payment.created_at.desc())
        .offset(offset).limit(per_page)
    )
    return result.scalars().all()
