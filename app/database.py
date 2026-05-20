from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings

settings = get_settings()
DATABASE_URL = settings.database_url

# Normalise URL schemes — handle Render/Heroku "postgres://" and plain "postgresql://"
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+asyncpg://", 1)
elif DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

if DATABASE_URL.startswith("sqlite:///"):
    DATABASE_URL = DATABASE_URL.replace("sqlite:///", "sqlite+aiosqlite:///", 1)


connect_args = {}

if DATABASE_URL.startswith("sqlite+aiosqlite:///"):
    connect_args = {"check_same_thread": False}


engine = create_async_engine(
    DATABASE_URL,
    echo=settings.app_debug,
    future=True,
    pool_pre_ping=True,
    connect_args=connect_args,
)


AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncIterator[AsyncSession]:
    async with AsyncSessionLocal() as session:
        yield session


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

        if conn.dialect.name == "postgresql":
            await conn.exec_driver_sql("ALTER TYPE provider ADD VALUE IF NOT EXISTS 'MOONPAY'")
            await conn.exec_driver_sql("ALTER TYPE provider ADD VALUE IF NOT EXISTS 'circle'")
            await conn.exec_driver_sql(
                "ALTER TABLE payment_orders ADD COLUMN IF NOT EXISTS checkout_url TEXT"
            )
            await conn.exec_driver_sql(
                "ALTER TABLE payment_orders ADD COLUMN IF NOT EXISTS provider_order_id VARCHAR(128)"
            )
            await conn.exec_driver_sql(
                "ALTER TABLE payment_orders ADD COLUMN IF NOT EXISTS client_id VARCHAR(36)"
            )
            await conn.exec_driver_sql(
                "ALTER TABLE payment_orders ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(160)"
            )
            await conn.exec_driver_sql(
                "ALTER TABLE payment_orders ADD COLUMN IF NOT EXISTS treasury_wallet_address VARCHAR(128)"
            )
            await conn.exec_driver_sql(
                "ALTER TABLE payment_orders ADD COLUMN IF NOT EXISTS customer_wallet_address VARCHAR(128)"
            )
            await conn.exec_driver_sql(
                "ALTER TABLE payment_orders ADD COLUMN IF NOT EXISTS payer_email VARCHAR(255)"
            )
            await conn.exec_driver_sql(
                "ALTER TABLE payment_orders ADD COLUMN IF NOT EXISTS payment_reference VARCHAR(128)"
            )
            await conn.exec_driver_sql(
                "ALTER TABLE payment_orders ADD COLUMN IF NOT EXISTS coinbase_session_url TEXT"
            )
            await conn.exec_driver_sql(
                "ALTER TABLE payment_orders ADD COLUMN IF NOT EXISTS coinbase_session_raw JSON"
            )

            await conn.exec_driver_sql(
                "ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS client_id VARCHAR(36)"
            )
            await conn.exec_driver_sql(
                "ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS endpoint VARCHAR(255)"
            )
            await conn.exec_driver_sql(
                "ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS method VARCHAR(16)"
            )
            await conn.exec_driver_sql(
                "ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS ip VARCHAR(64)"
            )
            await conn.exec_driver_sql(
                "ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS user_agent TEXT"
            )
            await conn.exec_driver_sql(
                "ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS status_code INTEGER"
            )
            await conn.exec_driver_sql(
                "ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS transaction_id VARCHAR(128)"
            )
            await conn.exec_driver_sql(
                "ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS request_id VARCHAR(128)"
            )
            await conn.exec_driver_sql(
                "ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS error_message TEXT"
            )

            await conn.exec_driver_sql(
                "CREATE TABLE IF NOT EXISTS client_accounts ("
                "id VARCHAR(36) PRIMARY KEY, "
                "api_client_id VARCHAR(36) NOT NULL REFERENCES api_clients(id), "
                "email_or_phone VARCHAR(255) UNIQUE NOT NULL, "
                "password_hash VARCHAR(255) NOT NULL, "
                "is_active BOOLEAN NOT NULL DEFAULT TRUE, "
                "created_at TIMESTAMPTZ DEFAULT now() NOT NULL"
                ")"
            )

            await conn.exec_driver_sql(
                "ALTER TABLE client_accounts ADD COLUMN IF NOT EXISTS api_client_id VARCHAR(36)"
            )
            await conn.exec_driver_sql(
                "ALTER TABLE client_accounts ADD COLUMN IF NOT EXISTS email_or_phone VARCHAR(255)"
            )
            await conn.exec_driver_sql(
                "ALTER TABLE client_accounts ADD COLUMN IF NOT EXISTS password_hash VARCHAR(255)"
            )
            await conn.exec_driver_sql(
                "ALTER TABLE client_accounts ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE"
            )
            await conn.exec_driver_sql(
                "ALTER TABLE client_accounts ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT now() NOT NULL"
            )

            # مهم: لو كانت الأعمدة أُنشئت سابقا كـ UUID، نحولها إلى VARCHAR حتى لا يظهر خطأ varchar = uuid.
            await conn.exec_driver_sql(
                "ALTER TABLE payment_orders ALTER COLUMN client_id TYPE VARCHAR(36) USING client_id::text"
            )
            await conn.exec_driver_sql(
                "ALTER TABLE audit_logs ALTER COLUMN client_id TYPE VARCHAR(36) USING client_id::text"
            )
            await conn.exec_driver_sql(
                "ALTER TABLE client_accounts ALTER COLUMN id TYPE VARCHAR(36) USING id::text"
            )
            await conn.exec_driver_sql(
                "ALTER TABLE client_accounts ALTER COLUMN api_client_id TYPE VARCHAR(36) USING api_client_id::text"
            )

            await conn.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_payment_orders_provider_order_id "
                "ON payment_orders (provider_order_id)"
            )
            await conn.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_payment_orders_client_id "
                "ON payment_orders (client_id)"
            )
            await conn.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_payment_orders_idempotency_key "
                "ON payment_orders (idempotency_key)"
            )
            await conn.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_payment_orders_checkout_url "
                "ON payment_orders (checkout_url)"
            )
            await conn.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_audit_logs_client_id "
                "ON audit_logs (client_id)"
            )
            await conn.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_audit_logs_request_id "
                "ON audit_logs (request_id)"
            )
            await conn.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_client_accounts_api_client_id "
                "ON client_accounts (api_client_id)"
            )
            await conn.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_client_accounts_email_or_phone "
                "ON client_accounts (email_or_phone)"
            )

            await conn.exec_driver_sql(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_payment_orders_client_idempotency_key "
                "ON payment_orders (client_id, idempotency_key) "
                "WHERE client_id IS NOT NULL AND idempotency_key IS NOT NULL"
            )
            await conn.exec_driver_sql(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_client_accounts_email_or_phone "
                "ON client_accounts (email_or_phone)"
            )

            # ── v2 settlement upgrade: hmac_required on api_clients ──────────
            await conn.exec_driver_sql(
                "ALTER TABLE api_clients ADD COLUMN IF NOT EXISTS hmac_required BOOLEAN NOT NULL DEFAULT FALSE"
            )
            await conn.exec_driver_sql(
                "ALTER TABLE api_clients ADD COLUMN IF NOT EXISTS oauth_client_id_hash VARCHAR(128)"
            )
            await conn.exec_driver_sql(
                "ALTER TABLE api_clients ADD COLUMN IF NOT EXISTS oauth_client_secret_hash VARCHAR(128)"
            )
            await conn.exec_driver_sql(
                "ALTER TABLE api_clients ADD COLUMN IF NOT EXISTS oauth_required BOOLEAN NOT NULL DEFAULT FALSE"
            )
            await conn.exec_driver_sql(
                "ALTER TABLE api_clients ADD COLUMN IF NOT EXISTS mtls_required BOOLEAN NOT NULL DEFAULT FALSE"
            )
            await conn.exec_driver_sql(
                "ALTER TABLE api_clients ADD COLUMN IF NOT EXISTS mtls_cert_fingerprint VARCHAR(128)"
            )
            await conn.exec_driver_sql(
                "ALTER TABLE api_clients ADD COLUMN IF NOT EXISTS jws_required BOOLEAN NOT NULL DEFAULT FALSE"
            )
            await conn.exec_driver_sql(
                "ALTER TABLE api_clients ADD COLUMN IF NOT EXISTS jws_public_key_pem TEXT"
            )
            await conn.exec_driver_sql(
                "ALTER TABLE api_clients ADD COLUMN IF NOT EXISTS jwe_required BOOLEAN NOT NULL DEFAULT FALSE"
            )

            # ── v2 settlement upgrade: external_payloads table ───────────────
            await conn.exec_driver_sql(
                """
                CREATE TABLE IF NOT EXISTS external_payloads (
                    id VARCHAR(36) PRIMARY KEY,
                    api_client_id VARCHAR(36) REFERENCES api_clients(id),
                    client_ip VARCHAR(64),
                    user_agent TEXT,
                    request_id VARCHAR(128),
                    idempotency_key VARCHAR(255),
                    raw_payload TEXT NOT NULL,
                    pretty_payload TEXT,
                    headers_json JSON,
                    parsed_payload JSON,
                    transaction_reference VARCHAR(255),
                    tx_hash VARCHAR(128),
                    sender_wallet VARCHAR(128),
                    receiver_wallet VARCHAR(128),
                    amount NUMERIC(30,18),
                    asset VARCHAR(32),
                    network_name VARCHAR(32),
                    token_contract VARCHAR(128),
                    callback_url TEXT,
                    settlement_type VARCHAR(64),
                    authorization_code VARCHAR(255),
                    payload_hash VARCHAR(128),
                    parsing_status VARCHAR(32) NOT NULL DEFAULT 'PENDING',
                    verification_status VARCHAR(32) NOT NULL DEFAULT 'RECEIVED',
                    security_level VARCHAR(96) NOT NULL DEFAULT 'api_key_only',
                    auth_method VARCHAR(32),
                    jws_verified BOOLEAN NOT NULL DEFAULT FALSE,
                    jwe_decrypted BOOLEAN NOT NULL DEFAULT FALSE,
                    mtls_verified BOOLEAN NOT NULL DEFAULT FALSE,
                    blockchain_result JSON,
                    block_number BIGINT,
                    confirmations INTEGER,
                    explorer_url TEXT,
                    verified_at TIMESTAMPTZ,
                    error_message TEXT,
                    review_priority VARCHAR(16) NOT NULL DEFAULT 'NORMAL',
                    review_decision VARCHAR(32),
                    review_note TEXT,
                    reviewed_by VARCHAR(128),
                    reviewed_at TIMESTAMPTZ,
                    hold_reason TEXT,
                    created_at TIMESTAMPTZ DEFAULT now() NOT NULL,
                    updated_at TIMESTAMPTZ DEFAULT now() NOT NULL
                )
                """
            )
            await conn.exec_driver_sql(
                "ALTER TABLE external_payloads ADD COLUMN IF NOT EXISTS payload_hash VARCHAR(128)"
            )
            await conn.exec_driver_sql(
                "ALTER TABLE external_payloads ADD COLUMN IF NOT EXISTS auth_method VARCHAR(32)"
            )
            await conn.exec_driver_sql(
                "ALTER TABLE external_payloads ADD COLUMN IF NOT EXISTS jws_verified BOOLEAN NOT NULL DEFAULT FALSE"
            )
            await conn.exec_driver_sql(
                "ALTER TABLE external_payloads ADD COLUMN IF NOT EXISTS jwe_decrypted BOOLEAN NOT NULL DEFAULT FALSE"
            )
            await conn.exec_driver_sql(
                "ALTER TABLE external_payloads ADD COLUMN IF NOT EXISTS mtls_verified BOOLEAN NOT NULL DEFAULT FALSE"
            )
            await conn.exec_driver_sql(
                "ALTER TABLE external_payloads ALTER COLUMN security_level TYPE VARCHAR(96)"
            )
            await conn.exec_driver_sql(
                "ALTER TABLE external_payloads ADD COLUMN IF NOT EXISTS review_priority VARCHAR(16) NOT NULL DEFAULT 'NORMAL'"
            )
            await conn.exec_driver_sql(
                "ALTER TABLE external_payloads ADD COLUMN IF NOT EXISTS review_decision VARCHAR(32)"
            )
            await conn.exec_driver_sql(
                "ALTER TABLE external_payloads ADD COLUMN IF NOT EXISTS review_note TEXT"
            )
            await conn.exec_driver_sql(
                "ALTER TABLE external_payloads ADD COLUMN IF NOT EXISTS reviewed_by VARCHAR(128)"
            )
            await conn.exec_driver_sql(
                "ALTER TABLE external_payloads ADD COLUMN IF NOT EXISTS reviewed_at TIMESTAMPTZ"
            )
            await conn.exec_driver_sql(
                "ALTER TABLE external_payloads ADD COLUMN IF NOT EXISTS hold_reason TEXT"
            )
            await conn.exec_driver_sql(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_api_clients_oauth_client_id_hash "
                "ON api_clients (oauth_client_id_hash) WHERE oauth_client_id_hash IS NOT NULL"
            )
            await conn.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_external_payloads_api_client_id "
                "ON external_payloads (api_client_id)"
            )
            await conn.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_external_payloads_tx_hash "
                "ON external_payloads (tx_hash)"
            )
            await conn.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_external_payloads_transaction_reference "
                "ON external_payloads (transaction_reference)"
            )
            await conn.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_external_payloads_verification_status "
                "ON external_payloads (verification_status)"
            )
            await conn.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_external_payloads_idempotency_key "
                "ON external_payloads (idempotency_key)"
            )
            await conn.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_external_payloads_created_at "
                "ON external_payloads (created_at)"
            )
            await conn.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_external_payloads_review_priority "
                "ON external_payloads (review_priority)"
            )
            await conn.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_external_payloads_review_decision "
                "ON external_payloads (review_decision)"
            )
