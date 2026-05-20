import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    JSON,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


# ─── New Enums ────────────────────────────────────────────────────────────────

class OutboundTransferStatus(str, enum.Enum):
    PENDING          = "PENDING"
    AWAITING_APPROVAL= "AWAITING_APPROVAL"
    APPROVED         = "APPROVED"
    BROADCASTING     = "BROADCASTING"
    COMPLETED        = "COMPLETED"
    FAILED           = "FAILED"
    CANCELLED        = "CANCELLED"


class M1TokenizationStatus(str, enum.Enum):
    QUEUED      = "QUEUED"
    FX_FETCHED  = "FX_FETCHED"
    CONVERTING  = "CONVERTING"
    SENDING     = "SENDING"
    COMPLETED   = "COMPLETED"
    FAILED      = "FAILED"


class PayloadVerificationStatus(str, enum.Enum):
    RECEIVED = "RECEIVED"
    PARSED = "PARSED"
    AWAITING_TX_HASH = "AWAITING_TX_HASH"
    ALCHEMY_PENDING = "ALCHEMY_PENDING"
    ALCHEMY_VERIFIED = "ALCHEMY_VERIFIED"
    ON_CHAIN_CONFIRMED = "ON_CHAIN_CONFIRMED"
    RECONCILED = "RECONCILED"
    FAILED = "FAILED"
    MANUAL_REVIEW = "MANUAL_REVIEW"


class Provider(str, enum.Enum):
    COINBASE = "coinbase"
    MOONPAY = "moonpay"
    CIRCLE = "circle"
    STRIPE = "stripe"
    LEDGER = "ledger"
    MANUAL = "manual"


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
    BASE = "base"
    ETHEREUM = "ethereum"
    TRON = "tron"


class ApiClient(Base):
    __tablename__ = "api_clients"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )

    name: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        index=True,
    )

    api_key_hash: Mapped[str] = mapped_column(
        String(128),
        unique=True,
        nullable=False,
        index=True,
    )

    hmac_secret: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
    )

    allowed_ips: Mapped[list[str] | None] = mapped_column(
        JSON,
        nullable=True,
    )

    is_active: Mapped[bool] = mapped_column(
        default=True,
        nullable=False,
        index=True,
    )

    # If True, all ingest requests from this client MUST include a valid HMAC signature.
    # If False, X-API-Key + Idempotency-Key alone are accepted (compatibility mode).
    hmac_required: Mapped[bool] = mapped_column(
        default=False,
        nullable=False,
    )

    # Enterprise settlement controls. These are disabled by default to keep
    # existing integrations working, then can be enabled per counterparty.
    oauth_client_id_hash: Mapped[str | None] = mapped_column(
        String(128),
        unique=True,
        nullable=True,
        index=True,
    )

    oauth_client_secret_hash: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
    )

    oauth_required: Mapped[bool] = mapped_column(
        default=False,
        nullable=False,
    )

    mtls_required: Mapped[bool] = mapped_column(
        default=False,
        nullable=False,
    )

    mtls_cert_fingerprint: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
    )

    jws_required: Mapped[bool] = mapped_column(
        default=False,
        nullable=False,
    )

    jws_public_key_pem: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    jwe_required: Mapped[bool] = mapped_column(
        default=False,
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    orders: Mapped[list["PaymentOrder"]] = relationship(
        back_populates="client",
    )

    audit_logs: Mapped[list["AuditLog"]] = relationship(
        back_populates="client",
    )

    accounts: Mapped[list["ClientAccount"]] = relationship(
        back_populates="api_client",
        cascade="all,delete-orphan",
    )

    external_payloads: Mapped[list["ExternalPayload"]] = relationship(
        back_populates="api_client",
        cascade="all,delete-orphan",
    )


class ClientAccount(Base):
    __tablename__ = "client_accounts"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )

    api_client_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("api_clients.id"),
        nullable=False,
        index=True,
    )

    email_or_phone: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
        index=True,
    )

    password_hash: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    is_active: Mapped[bool] = mapped_column(
        default=True,
        nullable=False,
        index=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    api_client: Mapped[ApiClient] = relationship(
        back_populates="accounts",
    )


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
        default="Treasury Wallet",
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

    __table_args__ = (
        UniqueConstraint(
            "client_id",
            "idempotency_key",
            name="uq_payment_orders_client_id_idempotency_key",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )

    client_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("api_clients.id"),
        nullable=True,
        index=True,
    )

    idempotency_key: Mapped[str | None] = mapped_column(
        String(160),
        nullable=True,
        index=True,
    )

    external_id: Mapped[str | None] = mapped_column(
        String(128),
        index=True,
        nullable=True,
    )

    provider: Mapped[Provider] = mapped_column(
        Enum(Provider),
        default=Provider.COINBASE,
        nullable=False,
        index=True,
    )

    side: Mapped[OrderSide] = mapped_column(
        Enum(OrderSide),
        default=OrderSide.BUY,
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
        default=Network.ETHEREUM,
        nullable=False,
        index=True,
    )

    fiat_currency: Mapped[str] = mapped_column(
        String(16),
        default="USD",
        nullable=False,
    )

    fiat_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 8),
        nullable=True,
    )

    crypto_currency: Mapped[str] = mapped_column(
        String(16),
        default="USDC",
        nullable=False,
        index=True,
    )

    crypto_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(30, 18),
        nullable=True,
    )

    user_wallet_address: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
        index=True,
    )

    customer_wallet_address: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
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

    coinbase_session_url: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    checkout_url: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    coinbase_session_raw: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
    )

    quote_json: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
    )

    tx_hash: Mapped[str | None] = mapped_column(
        String(128),
        index=True,
        nullable=True,
    )

    provider_order_id: Mapped[str | None] = mapped_column(
        String(128),
        index=True,
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

    client: Mapped[ApiClient | None] = relationship(
        back_populates="orders",
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

    client_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("api_clients.id"),
        nullable=True,
        index=True,
    )

    event_type: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        index=True,
    )

    endpoint: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        index=True,
    )

    method: Mapped[str | None] = mapped_column(
        String(16),
        nullable=True,
        index=True,
    )

    ip: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        index=True,
    )

    user_agent: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    status_code: Mapped[int | None] = mapped_column(
        nullable=True,
        index=True,
    )

    transaction_id: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
        index=True,
    )

    request_id: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
        index=True,
    )

    error_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
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

    client: Mapped[ApiClient | None] = relationship(
        back_populates="audit_logs",
    )


class ExternalPayload(Base):
    """
    Stores every inbound payload from external counterparties.
    Acts as the central audit log and reconciliation anchor for
    the settlement receiver pipeline.
    """

    __tablename__ = "external_payloads"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )

    # ── Client / Auth ──────────────────────────────────────────
    api_client_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("api_clients.id"),
        nullable=True,
        index=True,
    )

    # ── Request metadata ────────────────────────────────────────
    client_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)

    # ── Raw storage ─────────────────────────────────────────────
    raw_payload: Mapped[str] = mapped_column(Text, nullable=False)
    pretty_payload: Mapped[str | None] = mapped_column(Text, nullable=True)
    headers_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # ── Parsed / normalized fields ───────────────────────────────
    parsed_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    transaction_reference: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    tx_hash: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    sender_wallet: Mapped[str | None] = mapped_column(String(128), nullable=True)
    receiver_wallet: Mapped[str | None] = mapped_column(String(128), nullable=True)
    amount: Mapped[Decimal | None] = mapped_column(Numeric(30, 18), nullable=True)
    asset: Mapped[str | None] = mapped_column(String(32), nullable=True)
    network_name: Mapped[str | None] = mapped_column(String(32), nullable=True)
    token_contract: Mapped[str | None] = mapped_column(String(128), nullable=True)
    callback_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    settlement_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    authorization_code: Mapped[str | None] = mapped_column(String(255), nullable=True)
    payload_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # ── Status ───────────────────────────────────────────────────
    parsing_status: Mapped[str] = mapped_column(String(32), default="PENDING", nullable=False)
    verification_status: Mapped[str] = mapped_column(
        String(32),
        default=PayloadVerificationStatus.RECEIVED.value,
        nullable=False,
        index=True,
    )
    # "hmac_verified" | "api_key_only" | "unsigned"
    security_level: Mapped[str] = mapped_column(String(96), default="api_key_only", nullable=False)
    auth_method: Mapped[str | None] = mapped_column(String(32), nullable=True)
    jws_verified: Mapped[bool] = mapped_column(default=False, nullable=False)
    jwe_decrypted: Mapped[bool] = mapped_column(default=False, nullable=False)
    mtls_verified: Mapped[bool] = mapped_column(default=False, nullable=False)

    # ── Blockchain verification result ───────────────────────────
    blockchain_result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    block_number: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    confirmations: Mapped[int | None] = mapped_column(Integer, nullable=True)
    explorer_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # ── Error handling ───────────────────────────────────────────
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── Operational review / exception handling ─────────────────
    review_priority: Mapped[str] = mapped_column(String(16), default="NORMAL", nullable=False)
    review_decision: Mapped[str | None] = mapped_column(String(32), nullable=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    hold_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── Timestamps ───────────────────────────────────────────────
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

    # ── Relationship ─────────────────────────────────────────────
    api_client: Mapped["ApiClient | None"] = relationship(
        back_populates="external_payloads",
    )


class TransactionFile(Base):
    """
    Attached documents / evidence files for payment orders and settlement payloads.
    Files are stored as binary blobs in the database (no filesystem dependency).
    """

    __tablename__ = "transaction_files"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )

    # Link to either a PaymentOrder or ExternalPayload (or both / neither)
    order_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
        index=True,
    )
    payload_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
        index=True,
    )
    # Free-form reference so files can be attached by reference number too
    transaction_ref: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        index=True,
    )

    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(
        String(128),
        default="application/octet-stream",
        nullable=False,
    )
    file_data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    uploaded_by: Mapped[str | None] = mapped_column(String(128), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )


# ─── Outbound Transfer ────────────────────────────────────────────────────────

class OutboundTransfer(Base):
    """
    Tracks every outbound USDT payout initiated by the system.
    Supports ETH / TRON / Base networks with a full approval workflow.
    """

    __tablename__ = "outbound_transfers"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4()),
    )
    order_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    payload_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    tokenization_job_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)

    network: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    asset: Mapped[str] = mapped_column(String(16), default="USDT", nullable=False)
    from_address: Mapped[str | None] = mapped_column(String(128), nullable=True)
    to_address: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(30, 6), nullable=False)
    contract_address: Mapped[str | None] = mapped_column(String(128), nullable=True)

    tx_hash: Mapped[str | None] = mapped_column(String(128), nullable=True, unique=True, index=True)
    gas_used: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    block_number: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    confirmations: Mapped[int | None] = mapped_column(Integer, nullable=True)
    explorer_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[str] = mapped_column(
        String(32), default=OutboundTransferStatus.PENDING.value, nullable=False, index=True,
    )
    approved_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancel_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    initiated_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_result: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    callback_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    webhook_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    webhook_status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False,
    )
    broadcasted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


# ─── M1 Tokenization Job ──────────────────────────────────────────────────────

class M1TokenizationJob(Base):
    """
    Tracks every EUR → USD → USDT tokenization job from the M1 Fund pipeline.
    """

    __tablename__ = "m1_tokenization_jobs"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4()),
    )
    payload_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    sender_reference: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    sender_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sender_iban: Mapped[str | None] = mapped_column(String(64), nullable=True)

    eur_amount: Mapped[Decimal] = mapped_column(Numeric(30, 6), nullable=False)
    eur_received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    fx_rate_eur_usd: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    usd_amount: Mapped[Decimal | None] = mapped_column(Numeric(30, 6), nullable=True)
    fx_provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    fx_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    usdt_amount: Mapped[Decimal | None] = mapped_column(Numeric(30, 6), nullable=True)
    network: Mapped[str] = mapped_column(String(32), default="ethereum", nullable=False)
    destination_wallet: Mapped[str | None] = mapped_column(String(128), nullable=True)
    outbound_transfer_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)

    status: Mapped[str] = mapped_column(
        String(32), default=M1TokenizationStatus.QUEUED.value, nullable=False, index=True,
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    processed_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False,
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
