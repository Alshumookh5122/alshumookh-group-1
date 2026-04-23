from datetime import datetime
from decimal import Decimal
from pydantic import BaseModel, EmailStr, Field

from app.models import Network, OrderSide, OrderStatus, Provider


class HealthResponse(BaseModel):
    status: str = 'ok'


class WidgetUrlRequest(BaseModel):
    walletAddress: str = Field(min_length=8)
    cryptoCurrency: str = 'USDT'
    network: Network = Network.ETHEREUM
    fiatCurrency: str = 'AED'
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
    fiat_currency: str
    crypto_currency: str = 'USDT'
    fiat_amount: Decimal | None = None
    crypto_amount: Decimal | None = None
    user_wallet_address: str


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
