"""Crypto Router — address generation, balance checks, token rates."""

from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.app.config import settings
from app.app.database import get_db
from app.app.deps import get_current_active_user
from app.app.models import User
from app.app.schemas import GenerateAddressRequest, AddressResponse, CryptoRateResponse, WalletBalanceResponse
from app.app.alchemy_service import alchemy_service
from app.app.wallet_service import WalletRepository, WalletService
from app.app.utils import generate_qr_code_base64, generate_crypto_payment_uri
import structlog

logger = structlog.get_logger()
router = APIRouter(prefix="/api/v1/crypto", tags=["Crypto"])


@router.post("/address", response_model=AddressResponse)
async def generate_deposit_address(
    data: GenerateAddressRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    if data.token_symbol not in settings.SUPPORTED_TOKEN_LIST:
        raise HTTPException(400, f"Unsupported token: {data.token_symbol}")

    index = await WalletRepository.get_next_index(db)
    wallet = await WalletRepository.create_deposit_wallet(
        db, current_user.id, None, index, data.network or settings.ALCHEMY_NETWORK
    )
    await db.commit()

    uri = generate_crypto_payment_uri(wallet.address, data.token_symbol)
    qr_b64 = generate_qr_code_base64(uri)

    return AddressResponse(
        address=wallet.address,
        token_symbol=data.token_symbol,
        network=data.network or settings.ALCHEMY_NETWORK,
        qr_code_url=f"data:image/png;base64,{qr_b64}",
    )


@router.get("/rates", response_model=List[CryptoRateResponse])
async def get_token_rates():
    prices = await alchemy_service.get_token_prices()
    return [
        CryptoRateResponse(token=token, price_usd=price, updated_at=datetime.utcnow())
        for token, price in prices.items()
    ]


@router.get("/balance/{address}", response_model=WalletBalanceResponse)
async def get_wallet_balance(
    address: str,
    current_user: User = Depends(get_current_active_user),
):
    if not WalletService.is_valid_address(address):
        raise HTTPException(400, "Invalid Ethereum address")

    balances = await alchemy_service.get_all_balances(address)
    return WalletBalanceResponse(
        address=address,
        balances=balances,
        network=settings.ALCHEMY_NETWORK,
    )
