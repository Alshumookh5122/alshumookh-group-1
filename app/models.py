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
    PENDING_CONFIRMATION = "PENDING_CONFIRMATION"
    CONFIRMED        = "CONFIRMED"
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

    bridge_contract_address: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
    )

    egress_ip: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )

    # ── Outbound endpoint (where WE send responses/files TO this client) ────
    endpoint_url: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Sender's API endpoint URL — where ALSHUMOOKH pushes response documents",
    )

    endpoint_auth_header: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Authorization header value for outbound calls to sender endpoint (e.g. Bearer <token>)",
    )

    endpoint_content_type: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        default="application/json",
        comment="Content-Type to use when posting to sender endpoint",
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


# ─── M1 Funds Reserve Tokenization Module ────────────────────────────────────

class M1FundReserve(Base):
    """
    Isolated reserve ledger for the M1 Funds tokenization module.
    This does not alter the existing USDT settlement or M1 tokenization job flow.
    """

    __tablename__ = "m1_funds"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    fund_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    asset_name: Mapped[str] = mapped_column(String(128), default="M1 Fund", nullable=False)
    symbol: Mapped[str] = mapped_column(String(16), default="M1F", nullable=False)
    currency: Mapped[str] = mapped_column(String(8), default="USD", nullable=False)

    total_reserve_value: Mapped[Decimal] = mapped_column(Numeric(30, 8), default=Decimal("0"), nullable=False)
    tokenized_value: Mapped[Decimal] = mapped_column(Numeric(30, 8), default=Decimal("0"), nullable=False)
    issued_tokens: Mapped[Decimal] = mapped_column(Numeric(30, 8), default=Decimal("0"), nullable=False)
    available_to_mint: Mapped[Decimal] = mapped_column(Numeric(30, 8), default=Decimal("0"), nullable=False)
    backing_ratio: Mapped[str] = mapped_column(String(64), default="N/A", nullable=False)

    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False, index=True)
    proof_document_hash: Mapped[str | None] = mapped_column(String(256), nullable=True)
    valuation_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_updated: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class M1ReserveSnapshot(Base):
    __tablename__ = "m1_reserve_snapshots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    fund_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    total_reserve_value: Mapped[Decimal] = mapped_column(Numeric(30, 8), nullable=False)
    tokenized_value: Mapped[Decimal] = mapped_column(Numeric(30, 8), nullable=False)
    issued_tokens: Mapped[Decimal] = mapped_column(Numeric(30, 8), nullable=False)
    available_to_mint: Mapped[Decimal] = mapped_column(Numeric(30, 8), nullable=False)
    backing_ratio: Mapped[str] = mapped_column(String(64), nullable=False)
    proof_document_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    valuation_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    approved_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)


class M1MintRequest(Base):
    __tablename__ = "m1_mint_requests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    mint_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    fund_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    wallet: Mapped[str] = mapped_column(String(128), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(30, 8), nullable=False)
    network: Mapped[str] = mapped_column(String(32), default="ERC20", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="approved", nullable=False, index=True)
    nonce: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    signature: Mapped[str] = mapped_column(Text, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    tx_hash: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    contract_address: Mapped[str | None] = mapped_column(String(128), nullable=True)
    block_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class M1RedeemRequest(Base):
    __tablename__ = "m1_redeem_requests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    redeem_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    fund_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    wallet: Mapped[str] = mapped_column(String(128), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(30, 8), nullable=False)
    network: Mapped[str] = mapped_column(String(32), default="ERC20", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="approved", nullable=False, index=True)
    nonce: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    signature: Mapped[str] = mapped_column(Text, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    tx_hash: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    contract_address: Mapped[str | None] = mapped_column(String(128), nullable=True)
    block_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class M1TokenizationBatch(Base):
    __tablename__ = "m1_tokenization_batches"
    __table_args__ = (
        UniqueConstraint("fund_id", "sender_reference", name="uq_m1_batch_fund_sender_reference"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    batch_id: Mapped[str] = mapped_column(String(96), unique=True, nullable=False, index=True)
    fund_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    sender_reference: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    sender_name: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    sender_wallet: Mapped[str | None] = mapped_column(String(128), nullable=True)
    source_asset_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_network: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_transaction_hash: Mapped[str | None] = mapped_column(String(256), nullable=True, index=True)

    total_reserve_value: Mapped[Decimal] = mapped_column(Numeric(30, 8), nullable=False)
    tokenized_value: Mapped[Decimal] = mapped_column(Numeric(30, 8), nullable=False)
    issued_tokens: Mapped[Decimal] = mapped_column(Numeric(30, 8), default=Decimal("0"), nullable=False)
    available_to_mint: Mapped[Decimal] = mapped_column(Numeric(30, 8), nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, index=True)
    fx_rate_to_usd: Mapped[Decimal] = mapped_column(Numeric(20, 8), default=Decimal("1"), nullable=False)
    total_reserve_value_usd: Mapped[Decimal] = mapped_column(Numeric(30, 8), nullable=False)
    tokenized_value_usd: Mapped[Decimal] = mapped_column(Numeric(30, 8), nullable=False)
    issued_tokens_value_usd: Mapped[Decimal] = mapped_column(Numeric(30, 8), default=Decimal("0"), nullable=False)
    fx_rate_source: Mapped[str | None] = mapped_column(String(64), nullable=True)
    fx_rate_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    m1_contract_address: Mapped[str] = mapped_column(String(128), nullable=False)
    treasury_wallet: Mapped[str] = mapped_column(String(128), nullable=False)
    proof_document_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    valuation_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    mint_tx_hash: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    burn_tx_hash: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)

    status: Mapped[str] = mapped_column(String(32), default="draft", nullable=False, index=True)
    approved_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class M1BlockchainConfirmation(Base):
    __tablename__ = "m1_blockchain_confirmations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    fund_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    request_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    request_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    tx_hash: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    contract_address: Mapped[str] = mapped_column(String(128), nullable=False)
    wallet: Mapped[str] = mapped_column(String(128), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(30, 8), nullable=False)
    network: Mapped[str] = mapped_column(String(32), nullable=False)
    block_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    verification_status: Mapped[str] = mapped_column(String(64), default="recorded_not_chain_verified", nullable=False)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)


class M1AuditLog(Base):
    __tablename__ = "m1_audit_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    event_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    fund_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    batch_id: Mapped[str | None] = mapped_column(String(96), nullable=True, index=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    old_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    actor: Mapped[str | None] = mapped_column(String(128), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    tx_hash: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    proof_document_hash: Mapped[str | None] = mapped_column(String(256), nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class M1OracleRead(Base):
    __tablename__ = "m1_oracle_reads"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    fund_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    client_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    response_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="ok", nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)


class WalletVerification(Base):
    __tablename__ = "wallet_verifications"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    wallet: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    signature: Mapped[str] = mapped_column(Text, nullable=False)
    nonce: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)


class WalletOTP(Base):
    """OTP-based wallet address verification — sent via WhatsApp."""
    __tablename__ = "wallet_otps"

    id:             Mapped[str]           = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    wallet_address: Mapped[str]           = mapped_column(String(128), nullable=False, index=True)
    phone_number:   Mapped[str]           = mapped_column(String(50), nullable=False)
    otp_hash:       Mapped[str]           = mapped_column(String(64), nullable=False)   # SHA-256 of 6-digit OTP
    is_verified:    Mapped[bool]          = mapped_column(Boolean, default=False, nullable=False, index=True)
    is_used:        Mapped[bool]          = mapped_column(Boolean, default=False, nullable=False)
    expires_at:     Mapped[datetime]      = mapped_column(DateTime(timezone=True), nullable=False)
    verified_at:    Mapped[datetime|None] = mapped_column(DateTime(timezone=True), nullable=True)
    notes:          Mapped[str|None]      = mapped_column(Text, nullable=True)
    created_by:     Mapped[str|None]      = mapped_column(String(64), nullable=True)   # admin IP
    created_at:     Mapped[datetime]      = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)


class ApiSignature(Base):
    __tablename__ = "api_signatures"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    scope: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    client_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    signature: Mapped[str] = mapped_column(Text, nullable=False)
    response_hash: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class WebhookEvent(Base):
    __tablename__ = "webhook_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    event: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    fund_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    target_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    signature: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="queued", nullable=False, index=True)
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    request_body: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    response_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


# ─── Top-Up Engine ────────────────────────────────────────────────────────────

class TopUpWalletStatus(str, enum.Enum):
    ACTIVE   = "active"
    INACTIVE = "inactive"

class TopUpCardStatus(str, enum.Enum):
    ACTIVE    = "active"
    SUSPENDED = "suspended"
    CLOSED    = "closed"

class TopUpTransactionStatus(str, enum.Enum):
    PENDING   = "pending"
    SUCCESS   = "success"
    FAILED    = "failed"
    REJECTED  = "rejected"


class TopUpWallet(Base):
    """Internal wallet that holds balance for top-up cards."""
    __tablename__ = "topup_wallets"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    currency: Mapped[str] = mapped_column(String(16), default="USDT", nullable=False)
    balance: Mapped[Decimal] = mapped_column(
        Numeric(30, 6), default=Decimal("0"), nullable=False
    )
    blockchain_address: Mapped[str | None] = mapped_column(String(128), nullable=True)
    network: Mapped[str] = mapped_column(String(32), default="ethereum", nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), default=TopUpWalletStatus.ACTIVE.value, nullable=False, index=True
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    cards: Mapped[list["TopUpCard"]] = relationship(back_populates="wallet", cascade="all,delete-orphan")


class TopUpCard(Base):
    """Prepaid card linked to a TopUpWallet."""
    __tablename__ = "topup_cards"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    card_number: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    wallet_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("topup_wallets.id"), nullable=False, index=True
    )
    holder_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    provider_name: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    status: Mapped[str] = mapped_column(
        String(16), default=TopUpCardStatus.ACTIVE.value, nullable=False, index=True
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    wallet: Mapped["TopUpWallet"] = relationship(back_populates="cards")
    transactions: Mapped[list["TopUpTransaction"]] = relationship(
        back_populates="card", cascade="all,delete-orphan"
    )


class TopUpTransaction(Base):
    """Records every top-up request from a provider."""
    __tablename__ = "topup_transactions"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    reference: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False, index=True,
        default=lambda: f"TUP-{str(uuid.uuid4())[:8].upper()}"
    )
    card_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("topup_cards.id"), nullable=False, index=True
    )
    card_number: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    provider_name: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(30, 6), nullable=False)
    currency: Mapped[str] = mapped_column(String(16), default="USDT", nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), default=TopUpTransactionStatus.PENDING.value, nullable=False, index=True
    )
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider_ref: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    raw_request: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    card: Mapped["TopUpCard"] = relationship(back_populates="transactions")


# ─── OTC & Fiat Receiving Enums ───────────────────────────────────────────────

class FiatDepositStatus(str, enum.Enum):
    PENDING   = "PENDING"    # Registered, awaiting confirmation
    RECEIVED  = "RECEIVED"   # Bank confirmed receipt
    MATCHED   = "MATCHED"    # Linked to a TransferRequest
    REFUNDED  = "REFUNDED"   # Returned to sender
    CANCELLED = "CANCELLED"

class FiatPaymentMethod(str, enum.Enum):
    SEPA  = "SEPA"
    SWIFT = "SWIFT"
    LOCAL = "LOCAL"
    PSP   = "PSP"

class OtcQuoteStatus(str, enum.Enum):
    REQUESTED = "REQUESTED"  # Rate fetched, awaiting admin approval
    APPROVED  = "APPROVED"   # Admin approved
    LOCKED    = "LOCKED"     # Rate locked for execution
    EXECUTED  = "EXECUTED"   # Conversion done
    EXPIRED   = "EXPIRED"    # Lock time elapsed
    CANCELLED = "CANCELLED"

class OtcRateSource(str, enum.Enum):
    BINANCE = "BINANCE"
    MANUAL  = "MANUAL"

class TransferRequestStatus(str, enum.Enum):
    CREATED        = "CREATED"
    EUR_RECEIVED   = "EUR_RECEIVED"
    QUOTE_REQUESTED= "QUOTE_REQUESTED"
    QUOTE_APPROVED = "QUOTE_APPROVED"
    CONVERTING     = "CONVERTING"
    USDT_SENT      = "USDT_SENT"
    CONFIRMED      = "CONFIRMED"
    COMPLETED      = "COMPLETED"
    FAILED         = "FAILED"
    CANCELLED      = "CANCELLED"


# ─── FiatDeposit ──────────────────────────────────────────────────────────────

class FiatDeposit(Base):
    """Records incoming EUR payments via SEPA/SWIFT/Local before conversion."""
    __tablename__ = "fiat_deposits"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    reference: Mapped[str] = mapped_column(
        String(32), unique=True, nullable=False, index=True,
        default=lambda: f"FIAT-{str(uuid.uuid4())[:8].upper()}"
    )
    client_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("api_clients.id"), nullable=True, index=True
    )
    amount_eur: Mapped[Decimal] = mapped_column(Numeric(30, 6), nullable=False)
    sender_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    sender_bank: Mapped[str | None] = mapped_column(String(256), nullable=True)
    sender_iban: Mapped[str | None] = mapped_column(String(64), nullable=True)
    payment_method: Mapped[str] = mapped_column(
        String(16), default=FiatPaymentMethod.SWIFT.value, nullable=False
    )
    bank_reference: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    status: Mapped[str] = mapped_column(
        String(16), default=FiatDepositStatus.PENDING.value, nullable=False, index=True
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    client: Mapped["ApiClient | None"] = relationship("ApiClient", foreign_keys=[client_id])
    otc_quotes: Mapped[list["OtcQuote"]] = relationship(back_populates="fiat_deposit")
    transfer_requests: Mapped[list["TransferRequest"]] = relationship(back_populates="fiat_deposit")


# ─── OtcQuote ─────────────────────────────────────────────────────────────────

class OtcQuote(Base):
    """Live EUR→USDT OTC quote fetched from Binance and managed by admin."""
    __tablename__ = "otc_quotes"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    reference: Mapped[str] = mapped_column(
        String(32), unique=True, nullable=False, index=True,
        default=lambda: f"OTC-{str(uuid.uuid4())[:8].upper()}"
    )
    client_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("api_clients.id"), nullable=True, index=True
    )
    fiat_deposit_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("fiat_deposits.id"), nullable=True, index=True
    )
    amount_eur: Mapped[Decimal] = mapped_column(Numeric(30, 6), nullable=False)
    rate_eur_usdt: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    amount_usdt: Mapped[Decimal] = mapped_column(Numeric(30, 6), nullable=False)
    rate_source: Mapped[str] = mapped_column(
        String(16), default=OtcRateSource.BINANCE.value, nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(16), default=OtcQuoteStatus.REQUESTED.value, nullable=False, index=True
    )
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    raw_rate_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    client: Mapped["ApiClient | None"] = relationship("ApiClient", foreign_keys=[client_id])
    fiat_deposit: Mapped["FiatDeposit | None"] = relationship(back_populates="otc_quotes")
    transfer_requests: Mapped[list["TransferRequest"]] = relationship(back_populates="otc_quote")


# ─── TransferRequest ──────────────────────────────────────────────────────────

class TransferRequest(Base):
    """Full lifecycle: EUR deposit → OTC conversion → USDT transfer."""
    __tablename__ = "transfer_requests"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    reference: Mapped[str] = mapped_column(
        String(32), unique=True, nullable=False, index=True,
        default=lambda: f"TRQ-{str(uuid.uuid4())[:8].upper()}"
    )
    client_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("api_clients.id"), nullable=True, index=True
    )
    fiat_deposit_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("fiat_deposits.id"), nullable=True, index=True
    )
    otc_quote_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("otc_quotes.id"), nullable=True, index=True
    )
    outbound_transfer_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("outbound_transfers.id"), nullable=True, index=True
    )
    recipient_wallet: Mapped[str] = mapped_column(String(256), nullable=False)
    recipient_network: Mapped[str] = mapped_column(String(16), default="TRC20", nullable=False)
    amount_eur: Mapped[Decimal] = mapped_column(Numeric(30, 6), nullable=False)
    amount_usdt: Mapped[Decimal | None] = mapped_column(Numeric(30, 6), nullable=True)
    status: Mapped[str] = mapped_column(
        String(24), default=TransferRequestStatus.CREATED.value, nullable=False, index=True
    )
    sender_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    client: Mapped["ApiClient | None"] = relationship("ApiClient", foreign_keys=[client_id])
    fiat_deposit: Mapped["FiatDeposit | None"] = relationship(back_populates="transfer_requests")
    otc_quote: Mapped["OtcQuote | None"] = relationship(back_populates="transfer_requests")
    outbound_transfer: Mapped["OutboundTransfer | None"] = relationship("OutboundTransfer", foreign_keys=[outbound_transfer_id])
