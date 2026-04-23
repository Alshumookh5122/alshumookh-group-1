import enum
import uuid
from datetime import datetime
from sqlalchemy import DateTime, Enum, ForeignKey, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Provider(str, enum.Enum):
    TRANSAK = 'transak'
    MOONPAY = 'moonpay'
    MANUAL = 'manual'


class OrderSide(str, enum.Enum):
    BUY = 'BUY'
    SELL = 'SELL'


class OrderStatus(str, enum.Enum):
    CREATED = 'CREATED'
    PENDING = 'PENDING'
    PROCESSING = 'PROCESSING'
    COMPLETED = 'COMPLETED'
    FAILED = 'FAILED'
    REFUNDED = 'REFUNDED'
    EXPIRED = 'EXPIRED'


class Network(str, enum.Enum):
    ETHEREUM = 'ethereum'
    TRON = 'tron'


class TreasuryWallet(Base):
    __tablename__ = 'treasury_wallets'

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    network: Mapped[Network] = mapped_column(Enum(Network), nullable=False)
    address: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    label: Mapped[str] = mapped_column(String(128), nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    metadata_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PaymentOrder(Base):
    __tablename__ = 'payment_orders'

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    external_id: Mapped[str | None] = mapped_column(String(128), index=True)
    provider: Mapped[Provider] = mapped_column(Enum(Provider), nullable=False)
    side: Mapped[OrderSide] = mapped_column(Enum(OrderSide), nullable=False)
    status: Mapped[OrderStatus] = mapped_column(Enum(OrderStatus), default=OrderStatus.CREATED, nullable=False)
    network: Mapped[Network] = mapped_column(Enum(Network), nullable=False)
    fiat_currency: Mapped[str] = mapped_column(String(16), nullable=False)
    crypto_currency: Mapped[str] = mapped_column(String(16), nullable=False)
    fiat_amount: Mapped[float | None] = mapped_column(Numeric(20, 8))
    crypto_amount: Mapped[float | None] = mapped_column(Numeric(30, 18))
    user_wallet_address: Mapped[str] = mapped_column(String(128), nullable=False)
    quote_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    webhook_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    audit_logs: Mapped[list['AuditLog']] = relationship(back_populates='order', cascade='all,delete-orphan')


class AuditLog(Base):
    __tablename__ = 'audit_logs'

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey('payment_orders.id'))
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    details: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    order: Mapped[PaymentOrder | None] = relationship(back_populates='audit_logs')
