import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Enum, ForeignKey, JSON, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Provider(str, enum.Enum):
    TRANSAK = "transak"
    MOONPAY = "moonpay"
    MANUAL = "manual"
    LEDGER = "ledger"


class OrderSide(str, enum.Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderStatus(str, enum.Enum):
    CREATED = "CREATED"
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    REFUNDED = "REFUNDED"
    EXPIRED = "EXPIRED"


class Network(str, enum.Enum):
    ETHEREUM = "ethereum"
    TRON = "tron"


class TreasuryWallet(Base):
    __tablename__ = "treasury_wallets"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )

    network: Mapped[Network] = mapped_column(
        Enum(Network),
        nullable=False,
        index=True,
    )

    address: Mapped[str] = mapped_column(
        String(128),
        unique=True,
        nullable=False,
        index=True,
    )

    label: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
    )

    is_active: Mapped[bool] = mapped_column(
        default=True,
        nullable=False,
        index=True,
    )

    metadata_json: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class PaymentOrder(Base):
    __tablename__ = "payment_orders"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )

    external_id: Mapped[str | None] = mapped_column(
        String(128),
        index=True,
        nullable=True,
    )

    provider: Mapped[Provider] = mapped_column(
        Enum(Provider),
        nullable=False,
        index=True,
    )

    side: Mapped[OrderSide] = mapped_column(
        Enum(OrderSide),
        nullable=False,
    )

    status: Mapped[OrderStatus] = mapped_column(
        Enum(OrderStatus),
        default=OrderStatus.CREATED,
        nullable=False,
        index=True,
    )

    network: Mapped[Network] = mapped_column(
        Enum(Network),
        nullable=False,
        index=True,
    )

    fiat_currency: Mapped[str] = mapped_column(
        String(16),
        default="USD",
        nullable=False,
    )

    crypto_currency: Mapped[str] = mapped_column(
        String(16),
        default="USDT",
        nullable=False,
        index=True,
    )

    fiat_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 8),
        nullable=True,
    )

    crypto_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(30, 18),
        nullable=True,
    )

    user_wallet_address: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        index=True,
    )

    treasury_wallet_address: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
        index=True,
    )

    payer_email: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        index=True,
    )

    payment_reference: Mapped[str | None] = mapped_column(
        String(128),
        index=True,
        nullable=True,
    )

    tx_hash: Mapped[str | None] = mapped_column(
        String(128),
        index=True,
        nullable=True,
    )

    quote_json: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
    )

    webhook_payload: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
    )

    failure_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    audit_logs: Mapped[list["AuditLog"]] = relationship(
        back_populates="order",
        cascade="all,delete-orphan",
    )


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )

    order_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("payment_orders.id"),
        nullable=True,
        index=True,
    )

    event_type: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        index=True,
    )

    details: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )

    order: Mapped[PaymentOrder | None] = relationship(
        back_populates="audit_logs",
    )
