"""
Database models for the Alshumookh payment system.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional
from sqlalchemy import (
    String, Numeric, DateTime, Boolean, Integer, Text,
    ForeignKey, Enum as SAEnum, Index, JSON
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
import enum

from app.app.database import Base


def gen_uuid() -> str:
    return str(uuid.uuid4())


# ── Enums ────────────────────────────────────────────────────────────────────

class UserRole(str, enum.Enum):
    USER = "user"
    MERCHANT = "merchant"
    ADMIN = "admin"
    SUPER_ADMIN = "super_admin"


class UserStatus(str, enum.Enum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    PENDING_KYC = "pending_kyc"
    BANNED = "banned"


class PaymentStatus(str, enum.Enum):
    PENDING = "pending"
    AWAITING_PAYMENT = "awaiting_payment"
    PROCESSING = "processing"
    CONFIRMING = "confirming"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"
    EXPIRED = "expired"


class PaymentProvider(str, enum.Enum):
    STRIPE = "stripe"
    ALCHEMY = "alchemy"


class PaymentType(str, enum.Enum):
    FIAT = "fiat"
    CRYPTO = "crypto"


class TokenSymbol(str, enum.Enum):
    ETH = "ETH"
    USDT = "USDT"
    USDC = "USDC"
    DAI = "DAI"
    MATIC = "MATIC"


class TransactionDirection(str, enum.Enum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"
    SWEEP = "sweep"


class AuditAction(str, enum.Enum):
    PAYMENT_CREATED = "payment_created"
    PAYMENT_COMPLETED = "payment_completed"
    PAYMENT_FAILED = "payment_failed"
    PAYMENT_CANCELLED = "payment_cancelled"
    PAYMENT_REFUNDED = "payment_refunded"
    WEBHOOK_RECEIVED = "webhook_received"
    SWEEP_EXECUTED = "sweep_executed"
    USER_CREATED = "user_created"
    USER_SUSPENDED = "user_suspended"
    ADMIN_ACTION = "admin_action"


# ── Models ───────────────────────────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[Optional[str]] = mapped_column(String(255))
    phone: Mapped[Optional[str]] = mapped_column(String(50))
    role: Mapped[UserRole] = mapped_column(SAEnum(UserRole), default=UserRole.USER)
    status: Mapped[UserStatus] = mapped_column(SAEnum(UserStatus), default=UserStatus.ACTIVE)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    kyc_completed: Mapped[bool] = mapped_column(Boolean, default=False)
    api_key: Mapped[Optional[str]] = mapped_column(String(64), unique=True, index=True)
    metadata_: Mapped[Optional[dict]] = mapped_column("metadata", JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_login: Mapped[Optional[datetime]] = mapped_column(DateTime)

    payments: Mapped[list["Payment"]] = relationship("Payment", back_populates="user")
    wallets: Mapped[list["DepositWallet"]] = relationship("DepositWallet", back_populates="user")
    audit_logs: Mapped[list["AuditLog"]] = relationship("AuditLog", back_populates="user")

    __table_args__ = (
        Index("ix_users_email_status", "email", "status"),
    )


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    reference: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True)

    amount: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    currency: Mapped[str] = mapped_column(String(10), nullable=False)
    amount_usd: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 8))

    payment_type: Mapped[PaymentType] = mapped_column(SAEnum(PaymentType))
    provider: Mapped[PaymentProvider] = mapped_column(SAEnum(PaymentProvider))
    status: Mapped[PaymentStatus] = mapped_column(SAEnum(PaymentStatus), default=PaymentStatus.PENDING, index=True)

    provider_payment_id: Mapped[Optional[str]] = mapped_column(String(255), index=True)
    provider_client_secret: Mapped[Optional[str]] = mapped_column(String(500))

    deposit_address: Mapped[Optional[str]] = mapped_column(String(42), index=True)
    token_symbol: Mapped[Optional[str]] = mapped_column(String(10))
    token_contract: Mapped[Optional[str]] = mapped_column(String(42))
    tx_hash: Mapped[Optional[str]] = mapped_column(String(66), index=True)
    block_number: Mapped[Optional[int]] = mapped_column(Integer)
    confirmation_count: Mapped[int] = mapped_column(Integer, default=0)
    network: Mapped[Optional[str]] = mapped_column(String(30))

    description: Mapped[Optional[str]] = mapped_column(Text)
    metadata_: Mapped[Optional[dict]] = mapped_column("metadata", JSON)
    callback_url: Mapped[Optional[str]] = mapped_column(String(500))
    ip_address: Mapped[Optional[str]] = mapped_column(String(45))

    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, index=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user: Mapped["User"] = relationship("User", back_populates="payments")
    transactions: Mapped[list["BlockchainTransaction"]] = relationship("BlockchainTransaction", back_populates="payment")

    __table_args__ = (
        Index("ix_payments_status_created", "status", "created_at"),
        Index("ix_payments_user_status", "user_id", "status"),
    )


class DepositWallet(Base):
    __tablename__ = "deposit_wallets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True)
    payment_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("payments.id"), index=True)

    address: Mapped[str] = mapped_column(String(42), unique=True, index=True)
    derivation_path: Mapped[str] = mapped_column(String(50))
    encrypted_private_key: Mapped[str] = mapped_column(Text)

    network: Mapped[str] = mapped_column(String(30), default="ETH_MAINNET")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    swept: Mapped[bool] = mapped_column(Boolean, default=False)
    swept_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    sweep_tx_hash: Mapped[Optional[str]] = mapped_column(String(66))

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user: Mapped["User"] = relationship("User", back_populates="wallets")


class BlockchainTransaction(Base):
    __tablename__ = "blockchain_transactions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    payment_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("payments.id"), index=True)

    tx_hash: Mapped[str] = mapped_column(String(66), unique=True, index=True)
    from_address: Mapped[str] = mapped_column(String(42), index=True)
    to_address: Mapped[str] = mapped_column(String(42), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(30, 18))
    token_symbol: Mapped[str] = mapped_column(String(10))
    token_contract: Mapped[Optional[str]] = mapped_column(String(42))
    network: Mapped[str] = mapped_column(String(30))

    block_number: Mapped[Optional[int]] = mapped_column(Integer)
    confirmation_count: Mapped[int] = mapped_column(Integer, default=0)
    gas_used: Mapped[Optional[int]] = mapped_column(Integer)
    gas_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(30, 18))
    direction: Mapped[TransactionDirection] = mapped_column(SAEnum(TransactionDirection))

    raw_data: Mapped[Optional[dict]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    payment: Mapped[Optional["Payment"]] = relationship("Payment", back_populates="transactions")


class TreasuryTransaction(Base):
    __tablename__ = "treasury_transactions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    tx_hash: Mapped[Optional[str]] = mapped_column(String(66), unique=True, index=True)
    from_address: Mapped[str] = mapped_column(String(42))
    to_address: Mapped[str] = mapped_column(String(42))
    amount: Mapped[Decimal] = mapped_column(Numeric(30, 18))
    token_symbol: Mapped[str] = mapped_column(String(10))
    network: Mapped[str] = mapped_column(String(30))
    direction: Mapped[TransactionDirection] = mapped_column(SAEnum(TransactionDirection))
    notes: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class WebhookEvent(Base):
    __tablename__ = "webhook_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    provider: Mapped[str] = mapped_column(String(30), index=True)
    event_type: Mapped[str] = mapped_column(String(100), index=True)
    event_id: Mapped[Optional[str]] = mapped_column(String(255), index=True)
    payload: Mapped[dict] = mapped_column(JSON)
    processed: Mapped[bool] = mapped_column(Boolean, default=False)
    processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    error: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_webhook_provider_event", "provider", "event_id"),
    )


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    user_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("users.id"), index=True)
    action: Mapped[AuditAction] = mapped_column(SAEnum(AuditAction), index=True)
    resource_type: Mapped[Optional[str]] = mapped_column(String(50))
    resource_id: Mapped[Optional[str]] = mapped_column(String(36))
    details: Mapped[Optional[dict]] = mapped_column(JSON)
    ip_address: Mapped[Optional[str]] = mapped_column(String(45))
    user_agent: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    user: Mapped[Optional["User"]] = relationship("User", back_populates="audit_logs")


class ReconciliationReport(Base):
    __tablename__ = "reconciliation_reports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    report_date: Mapped[datetime] = mapped_column(DateTime, unique=True, index=True)
    total_payments: Mapped[int] = mapped_column(Integer, default=0)
    completed_payments: Mapped[int] = mapped_column(Integer, default=0)
    failed_payments: Mapped[int] = mapped_column(Integer, default=0)
    total_volume_usd: Mapped[Decimal] = mapped_column(Numeric(20, 2), default=Decimal("0"))
    crypto_volume_usd: Mapped[Decimal] = mapped_column(Numeric(20, 2), default=Decimal("0"))
    fiat_volume_usd: Mapped[Decimal] = mapped_column(Numeric(20, 2), default=Decimal("0"))
    discrepancies: Mapped[Optional[dict]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
