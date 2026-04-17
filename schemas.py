"""
Pydantic v2 schemas for request validation and response serialization.
"""

from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator
from app.app.models import (
    PaymentStatus, PaymentProvider, PaymentType,
    UserRole, UserStatus, TokenSymbol, TransactionDirection
)


# ── Base ─────────────────────────────────────────────────────────────────────

class BaseResponse(BaseModel):
    class Config:
        from_attributes = True


# ── Auth ─────────────────────────────────────────────────────────────────────

class UserRegister(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=100)
    full_name: Optional[str] = Field(None, max_length=255)
    phone: Optional[str] = Field(None, max_length=50)


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds


class RefreshRequest(BaseModel):
    refresh_token: str


class UserResponse(BaseResponse):
    id: str
    email: str
    full_name: Optional[str]
    phone: Optional[str]
    role: UserRole
    status: UserStatus
    is_verified: bool
    kyc_completed: bool
    created_at: datetime


# ── Payments ─────────────────────────────────────────────────────────────────

class CreatePaymentRequest(BaseModel):
    amount: Decimal = Field(gt=0, decimal_places=8)
    currency: str = Field(min_length=2, max_length=10)
    payment_type: PaymentType
    token_symbol: Optional[str] = None   # For crypto
    description: Optional[str] = Field(None, max_length=500)
    callback_url: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

    @field_validator("currency")
    @classmethod
    def currency_upper(cls, v: str) -> str:
        return v.upper()

    @model_validator(mode="after")
    def validate_crypto_fields(self) -> "CreatePaymentRequest":
        if self.payment_type == PaymentType.CRYPTO and not self.token_symbol:
            raise ValueError("token_symbol required for crypto payments")
        return self


class PaymentResponse(BaseResponse):
    id: str
    reference: str
    amount: Decimal
    currency: str
    amount_usd: Optional[Decimal]
    payment_type: PaymentType
    provider: PaymentProvider
    status: PaymentStatus
    deposit_address: Optional[str]
    token_symbol: Optional[str]
    tx_hash: Optional[str]
    confirmation_count: int
    provider_payment_id: Optional[str]
    provider_client_secret: Optional[str]
    description: Optional[str]
    expires_at: Optional[datetime]
    completed_at: Optional[datetime]
    created_at: datetime


class PaymentListResponse(BaseModel):
    items: List[PaymentResponse]
    total: int
    page: int
    per_page: int
    pages: int


class CancelPaymentRequest(BaseModel):
    reason: Optional[str] = None


# ── Crypto ───────────────────────────────────────────────────────────────────

class GenerateAddressRequest(BaseModel):
    token_symbol: str
    network: Optional[str] = "ETH_MAINNET"


class AddressResponse(BaseModel):
    address: str
    token_symbol: str
    network: str
    qr_code_url: Optional[str] = None


class CryptoRateResponse(BaseModel):
    token: str
    price_usd: Decimal
    updated_at: datetime


class WalletBalanceResponse(BaseModel):
    address: str
    balances: Dict[str, Decimal]  # token -> amount
    network: str


# ── Fiat ─────────────────────────────────────────────────────────────────────

class CreateFiatIntentRequest(BaseModel):
    amount_cents: int = Field(gt=0)  # In cents (USD)
    currency: str = "usd"
    payment_method_types: List[str] = ["card"]
    description: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class FiatIntentResponse(BaseModel):
    payment_intent_id: str
    client_secret: str
    amount: int
    currency: str
    status: str
    publishable_key: str


class ConfirmFiatRequest(BaseModel):
    payment_method_id: str


# ── Treasury ─────────────────────────────────────────────────────────────────

class TreasuryBalanceResponse(BaseModel):
    address: str
    balances: Dict[str, Decimal]
    total_usd: Decimal
    network: str
    updated_at: datetime


class SweepRequest(BaseModel):
    wallet_address: str
    token_symbol: str = "ETH"
    force: bool = False


class SweepResponse(BaseModel):
    tx_hash: str
    from_address: str
    to_address: str
    amount: Decimal
    token_symbol: str
    network: str


class TreasuryTransactionResponse(BaseResponse):
    id: str
    tx_hash: Optional[str]
    from_address: str
    to_address: str
    amount: Decimal
    token_symbol: str
    network: str
    direction: TransactionDirection
    notes: Optional[str]
    created_at: datetime


# ── Blockchain ───────────────────────────────────────────────────────────────

class BlockchainTransactionResponse(BaseResponse):
    id: str
    tx_hash: str
    from_address: str
    to_address: str
    amount: Decimal
    token_symbol: str
    network: str
    block_number: Optional[int]
    confirmation_count: int
    direction: TransactionDirection
    created_at: datetime


# ── Admin ────────────────────────────────────────────────────────────────────

class AdminStatsResponse(BaseModel):
    total_users: int
    active_users: int
    total_payments: int
    pending_payments: int
    completed_payments_24h: int
    volume_24h_usd: Decimal
    volume_7d_usd: Decimal
    volume_30d_usd: Decimal
    crypto_volume_ratio: float
    fiat_volume_ratio: float
    treasury_balance_usd: Decimal


class AdminUserUpdate(BaseModel):
    status: Optional[UserStatus] = None
    role: Optional[UserRole] = None
    kyc_completed: Optional[bool] = None


class PaginationParams(BaseModel):
    page: int = Field(1, ge=1)
    per_page: int = Field(20, ge=1, le=100)


# ── Webhooks ─────────────────────────────────────────────────────────────────

class AlchemyWebhookEvent(BaseModel):
    webhookId: str
    id: str
    createdAt: str
    type: str
    event: Dict[str, Any]


class StripeWebhookEvent(BaseModel):
    id: str
    object: str
    type: str
    data: Dict[str, Any]
    created: int


# ── Health / Misc ─────────────────────────────────────────────────────────────

class HealthResponse(BaseModel):
    status: str
    version: str
    environment: str
    database: str
    redis: str
    timestamp: datetime


class ErrorResponse(BaseModel):
    error: str
    detail: Optional[str] = None
    code: Optional[str] = None
