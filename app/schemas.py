from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, EmailStr, Field, model_validator

from app.models import Network, OrderSide, OrderStatus, Provider


class HealthResponse(BaseModel):
    status: str = "ok"


class CoinbaseOnrampCreate(BaseModel):
    fiat_amount: Decimal = Field(gt=0)
    fiat_currency: str = "USD"
    crypto_currency: str = "USDC"
    network: Network = Network.ETHEREUM
    payer_email: EmailStr | None = None
    customer_email: EmailStr | None = None
    external_id: str | None = None
    redirect_url: str | None = None
    payment_method: str | None = None
    country: str | None = None
    subdivision: str | None = None

    @model_validator(mode="after")
    def normalize(self):
        self.fiat_currency = self.fiat_currency.upper()
        self.crypto_currency = self.crypto_currency.upper()

        if self.customer_email and not self.payer_email:
            self.payer_email = self.customer_email

        return self


class CoinbaseOnrampResponse(BaseModel):
    id: str
    status: OrderStatus
    provider: Provider
    fiat_amount: Decimal | None
    fiat_currency: str
    crypto_currency: str
    network: Network
    treasury_wallet_address: str
    payment_reference: str
    onramp_url: str
    payment_url: str | None = None
    invoice_url: str | None = None
    receipt_url: str | None = None


class WidgetUrlRequest(BaseModel):
    walletAddress: str | None = Field(default=None, min_length=8)
    cryptoCurrency: str = "USDC"
    network: Network = Network.ETHEREUM
    fiatCurrency: str = "USD"
    fiatAmount: Decimal | None = None
    cryptoAmount: Decimal | None = None
    isBuyOrSell: OrderSide = OrderSide.BUY
    redirectURL: str | None = None
    userEmail: EmailStr | None = None
    paymentMethod: str | None = None
    country: str | None = None
    subdivision: str | None = None
    partnerUserRef: str | None = None

    @model_validator(mode="after")
    def normalize(self):
        self.fiatCurrency = self.fiatCurrency.upper()
        self.cryptoCurrency = self.cryptoCurrency.upper()
        return self


class WidgetUrlResponse(BaseModel):
    widget_url: str
    provider: Provider = Provider.MOONPAY
    quote: dict | None = None


class OrderCreate(BaseModel):
    external_id: str | None = None
    provider: Provider = Provider.MANUAL
    side: OrderSide = OrderSide.BUY
    network: Network = Network.ETHEREUM

    fiat_currency: str = "USD"
    fiat_amount: Decimal | None = None

    crypto_currency: str = "USDC"
    crypto_amount: Decimal | None = None

    amount: Decimal | None = Field(default=None, gt=0)
    currency: str | None = None

    user_wallet_address: str | None = None
    customer_wallet_address: str | None = None
    treasury_wallet_address: str | None = None

    payer_email: EmailStr | None = None
    customer_email: EmailStr | None = None

    description: str | None = None

    @model_validator(mode="after")
    def normalize_fields(self):
        if self.amount is not None and self.crypto_amount is None:
            self.crypto_amount = self.amount

        if self.currency:
            self.crypto_currency = self.currency.upper()

        if self.customer_email and not self.payer_email:
            self.payer_email = self.customer_email

        if not self.user_wallet_address:
            self.user_wallet_address = self.customer_wallet_address

        if self.crypto_amount is None and self.fiat_amount is None:
            raise ValueError("amount, crypto_amount, or fiat_amount is required")

        self.crypto_currency = self.crypto_currency.upper()
        self.fiat_currency = self.fiat_currency.upper()

        return self


class OrderRead(BaseModel):
    id: str
    external_id: str | None
    provider: Provider
    side: OrderSide
    status: OrderStatus
    network: Network

    fiat_currency: str
    fiat_amount: Decimal | None

    crypto_currency: str
    crypto_amount: Decimal | None

    user_wallet_address: str | None = None
    customer_wallet_address: str | None = None
    treasury_wallet_address: str | None = None

    payer_email: str | None = None
    payment_reference: str | None = None

    coinbase_session_url: str | None = None
    checkout_url: str | None = None
    provider_order_id: str | None = None
    tx_hash: str | None = None
    failure_reason: str | None = None

    created_at: datetime

    class Config:
        from_attributes = True


class CoinbaseOrderCreate(BaseModel):
    external_id: str | None = None
    network: Network = Network.ETHEREUM
    fiat_currency: str = "USD"
    crypto_currency: str = "USDC"
    fiat_amount: Decimal | None = Field(default=None, gt=0)
    crypto_amount: Decimal | None = Field(default=None, gt=0)
    redirect_url: str | None = None
    payment_method: str | None = None
    country: str | None = None
    subdivision: str | None = None
    customer_email: EmailStr | None = None
    metadata: dict | None = None

    @model_validator(mode="after")
    def normalize(self):
        if self.fiat_amount is not None and self.crypto_amount is not None:
            raise ValueError("Use fiat_amount or crypto_amount, not both")

        if self.fiat_amount is None and self.crypto_amount is None:
            raise ValueError("fiat_amount or crypto_amount is required")

        self.fiat_currency = self.fiat_currency.upper()
        self.crypto_currency = self.crypto_currency.upper()

        return self


class CoinbaseOrderResponse(BaseModel):
    order: OrderRead
    widget_url: str
    quote: dict | None = None


class MoonPayOrderResponse(BaseModel):
    order: OrderRead
    widget_url: str
    quote: dict | None = None


class TransactionCreate(BaseModel):
    external_id: str | None = None
    network: Network = Network.ETHEREUM
    fiat_currency: str = "USD"
    crypto_currency: str = "USDC"
    fiat_amount: Decimal | None = Field(default=None, gt=0)
    crypto_amount: Decimal | None = Field(default=None, gt=0)
    payment_method: str | None = None
    country: str | None = None
    subdivision: str | None = None
    redirect_url: str | None = None
    customer_email: EmailStr | None = None
    metadata: dict | None = None

    @model_validator(mode="after")
    def normalize(self):
        if self.fiat_amount is not None and self.crypto_amount is not None:
            raise ValueError("Use fiat_amount or crypto_amount, not both")

        if self.fiat_amount is None and self.crypto_amount is None:
            raise ValueError("fiat_amount or crypto_amount is required")

        self.fiat_currency = self.fiat_currency.upper()
        self.crypto_currency = self.crypto_currency.upper()

        return self


class TransactionResponse(BaseModel):
    transaction_id: str
    external_id: str | None
    status: OrderStatus
    provider: Provider
    network: Network
    fiat_currency: str
    crypto_currency: str
    fiat_amount: Decimal | None
    crypto_amount: Decimal | None
    destination_address: str | None
    checkout_url: str | None = None
    provider_order_id: str | None = None
    quote: dict | None = None
    created_at: datetime


class LedgerOrderCreate(BaseModel):
    amount: Decimal | None = Field(default=None, gt=0)
    crypto_amount: Decimal | None = Field(default=None, gt=0)

    network: Network = Network.ETHEREUM
    crypto_currency: str = "USDC"

    fiat_currency: str = "USD"
    fiat_amount: Decimal | None = None

    payer_email: EmailStr | None = None
    customer_email: EmailStr | None = None
    customer_wallet_address: str | None = None
    external_id: str | None = None
    description: str | None = None

    @model_validator(mode="after")
    def normalize_amount(self):
        if self.crypto_amount is None and self.amount is not None:
            self.crypto_amount = self.amount

        if self.customer_email and not self.payer_email:
            self.payer_email = self.customer_email

        if self.crypto_amount is None:
            raise ValueError("Either amount or crypto_amount is required")

        self.crypto_currency = self.crypto_currency.upper()
        self.fiat_currency = self.fiat_currency.upper()

        return self


class LedgerOrderResponse(BaseModel):
    id: str
    status: OrderStatus
    network: Network
    crypto_currency: str
    crypto_amount: Decimal | None
    treasury_wallet_address: str
    payment_reference: str
    payment_url: str
    qr_url: str
    invoice_url: str | None = None
    receipt_url: str | None = None
    warning: str


class LedgerPaymentStatus(BaseModel):
    id: str
    status: OrderStatus
    network: Network
    expected_amount: Decimal | None
    treasury_wallet_address: str | None
    tx_hash: str | None = None
    payment_reference: str | None = None
    confirmations_note: str = (
        "Payment is confirmed automatically by webhook or manually by admin."
    )


class LedgerManualConfirm(BaseModel):
    order_id: str
    tx_hash: str = Field(min_length=8)
    note: str | None = None


class PaymentStatusResponse(BaseModel):
    id: str
    status: OrderStatus
    provider: Provider
    fiat_amount: Decimal | None
    fiat_currency: str
    crypto_currency: str
    crypto_amount: Decimal | None = None
    network: Network
    treasury_wallet_address: str | None
    payment_reference: str | None = None
    tx_hash: str | None = None
    created_at: datetime
    note: str = "Order remains PENDING until Coinbase or blockchain confirmation is received."


class ApiClientCreate(BaseModel):
    name: str = Field(min_length=2, max_length=128)
    allowed_ips: list[str] | None = None
    hmac_required: bool = False
    oauth_required: bool = False
    mtls_required: bool = False
    mtls_cert_fingerprint: str | None = None
    jws_required: bool = False
    jws_public_key_pem: str | None = None
    jwe_required: bool = False

    @model_validator(mode="after")
    def validate_security_requirements(self):
        if self.mtls_required and not self.mtls_cert_fingerprint:
            raise ValueError("mtls_cert_fingerprint is required when mtls_required is true")

        if self.jws_required and not self.jws_public_key_pem:
            raise ValueError("jws_public_key_pem is required when jws_required is true")

        return self


class ApiClientUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=128)
    allowed_ips: list[str] | None = None
    is_active: bool | None = None
    hmac_required: bool | None = None
    oauth_required: bool | None = None
    mtls_required: bool | None = None
    mtls_cert_fingerprint: str | None = None
    jws_required: bool | None = None
    jws_public_key_pem: str | None = None
    jwe_required: bool | None = None

    @model_validator(mode="after")
    def validate_security_requirements(self):
        if self.mtls_required is True and not self.mtls_cert_fingerprint:
            raise ValueError("mtls_cert_fingerprint is required when mtls_required is true")

        if self.jws_required is True and not self.jws_public_key_pem:
            raise ValueError("jws_public_key_pem is required when jws_required is true")

        return self


class ApiClientRead(BaseModel):
    id: str
    name: str
    allowed_ips: list[str] | None
    is_active: bool
    hmac_required: bool = False
    oauth_required: bool = False
    mtls_required: bool = False
    mtls_cert_fingerprint: str | None = None
    jws_required: bool = False
    jwe_required: bool = False
    created_at: datetime

    class Config:
        from_attributes = True


class ApiClientCreated(ApiClientRead):
    api_key: str
    hmac_secret: str
    oauth_client_id: str
    oauth_client_secret: str


class PayloadReviewAction(BaseModel):
    action: str = Field(min_length=4, max_length=32)
    note: str | None = Field(default=None, max_length=4000)
    priority: str | None = Field(default=None, max_length=16)
    hold_reason: str | None = Field(default=None, max_length=4000)

    @model_validator(mode="after")
    def normalize(self):
        self.action = self.action.upper().strip()
        if self.priority:
            self.priority = self.priority.upper().strip()
        if self.note:
            self.note = self.note.strip()
        if self.hold_reason:
            self.hold_reason = self.hold_reason.strip()

        allowed_actions = {"APPROVE", "HOLD", "REJECT", "RECONCILE", "NOTE"}
        if self.action not in allowed_actions:
            raise ValueError(f"action must be one of: {', '.join(sorted(allowed_actions))}")

        allowed_priorities = {None, "LOW", "NORMAL", "HIGH", "CRITICAL"}
        if self.priority not in allowed_priorities:
            raise ValueError("priority must be LOW, NORMAL, HIGH, or CRITICAL")

        if self.action == "HOLD" and not self.hold_reason:
            raise ValueError("hold_reason is required when action is HOLD")

        return self


class TreasuryWalletRead(BaseModel):
    id: str
    network: Network
    address: str
    label: str
    is_active: bool

    class Config:
        from_attributes = True


class TreasuryBalanceResponse(BaseModel):
    network: Network
    address: str
    native_balance: str
    token_symbol: str | None = None
    token_balance: str | None = None


class InvoiceResponse(BaseModel):
    order_id: str
    invoice_number: str
    status: OrderStatus
    provider: Provider
    amount: Decimal | None
    currency: str
    payment_url: str
    invoice_url: str
    issued_at: datetime


class ReceiptResponse(BaseModel):
    order_id: str
    receipt_number: str
    status: OrderStatus
    provider: Provider
    amount: Decimal | None
    currency: str
    tx_hash: str | None = None
    receipt_url: str
    issued_at: datetime


class DashboardOrderRead(BaseModel):
    id: str
    provider: Provider
    status: OrderStatus
    network: Network
    fiat_amount: Decimal | None
    fiat_currency: str
    crypto_amount: Decimal | None
    crypto_currency: str
    payer_email: str | None = None
    payment_reference: str | None = None
    checkout_url: str | None = None
    provider_order_id: str | None = None
    tx_hash: str | None = None
    created_at: datetime

    class Config:
        from_attributes = True


class DashboardSummary(BaseModel):
    total_orders: int
    pending_orders: int
    completed_orders: int
    failed_orders: int
    total_fiat_amount: Decimal | None = None
    total_crypto_amount: Decimal | None = None


class WebhookAck(BaseModel):
    received: bool = True
