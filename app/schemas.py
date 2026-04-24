from datetime import datetime
from decimal import Decimal
from pydantic import BaseModel, EmailStr, Field

from app.models import Network, OrderSide, OrderStatus, Provider


class HealthResponse(BaseModel):
    status: str = "ok"


class WidgetUrlRequest(BaseModel):
    walletAddress: str = Field(min_length=8)
    cryptoCurrency: str = "USDT"
    network: Network = Network.ETHEREUM
    fiatCurrency: str = "AED"
    fiatAmount: Decimal | None = None
    cryptoAmount: Decimal | None = None
    isBuyOrSell: OrderSide = OrderSide.BUY
    redirectURL: str | None = None
    userEmail: EmailStr | None = None


class WidgetUrlResponse(BaseModel):
    widget_url: str
    provider: Provider = Provider.TRANSAK


class OrderCreate(BaseModel):
    external_id: str | None = None
    provider: Provider = Provider.TRANSAK
    side: OrderSide
    network: Network
    fiat_currency: str = "USD"
    crypto_currency: str = "USDT"
    fiat_amount: Decimal | None = None
    crypto_amount: Decimal | None = None
    user_wallet_address: str
    payer_email: EmailStr | None = None


class LedgerOrderCreate(BaseModel):
    network: Network = Network.TRON
    crypto_currency: str = "USDT"
    crypto_amount: Decimal = Field(gt=0)
    fiat_currency: str = "USD"
    fiat_amount: Decimal | None = None
    payer_email: EmailStr | None = None
    customer_wallet_address: str | None = None
    external_id: str | None = None


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
    warning: str


class LedgerPaymentStatus(BaseModel):
    id: str
    status: OrderStatus
    network: Network
    expected_amount: Decimal | None
    treasury_wallet_address: str | None
    tx_hash: str | None = None
    confirmations_note: str = "Manual confirmation or blockchain webhook confirmation required."


class LedgerManualConfirm(BaseModel):
    order_id: str
    tx_hash: str = Field(min_length=8)
    note: str | None = None


class OrderRead(BaseModel):
    id: str
    external_id: str | None
    provider: Provider
    side: OrderSide
    status: OrderStatus
    network: Network
    fiat_currency: str
    crypto_currency: str
    fiat_amount: Decimal | None
    crypto_amount: Decimal | None
    user_wallet_address: str
    treasury_wallet_address: str | None = None
    payment_reference: str | None = None
    tx_hash: str | None = None
    created_at: datetime


class TreasuryWalletRead(BaseModel):
    id: str
    network: Network
    address: str
    label: str
    is_active: bool


class TreasuryBalanceResponse(BaseModel):
    network: Network
    address: str
    native_balance: str
    token_symbol: str | None = None
    token_balance: str | None = None


class WebhookAck(BaseModel):
    received: bool = True
