"""
Treasury Service & Router — manages the hot wallet, fund sweeping,
balance monitoring, and treasury transaction history.
"""

from decimal import Decimal
from typing import Dict, List, Optional
import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from web3 import Web3
from eth_account import Account

from app.app.config import settings
from app.app.database import get_db
from app.app.deps import require_admin
from app.app.models import (
    TreasuryTransaction, TransactionDirection,
    DepositWallet, AuditLog, AuditAction, User
)
from app.app.schemas import (
    TreasuryBalanceResponse, SweepRequest, SweepResponse,
    TreasuryTransactionResponse
)
from app.app.alchemy_service import alchemy_service
from app.app.wallet_service import WalletRepository, WalletService
import structlog

logger = structlog.get_logger()
router = APIRouter(prefix="/api/v1/treasury", tags=["Treasury"])


class TreasuryService:
    """Core treasury operations."""

    SWEEP_THRESHOLD_ETH = Decimal("0.001")

    @staticmethod
    async def get_treasury_balances() -> Dict[str, Decimal]:
        if not settings.TREASURY_WALLET_ADDRESS:
            return {}
        return await alchemy_service.get_all_balances(settings.TREASURY_WALLET_ADDRESS)

    @staticmethod
    async def get_total_usd_value() -> Decimal:
        balances = await TreasuryService.get_treasury_balances()
        prices = await alchemy_service.get_token_prices()
        total = Decimal("0")
        for token, amount in balances.items():
            price = prices.get(token, Decimal("0"))
            total += amount * price
        return total

    @classmethod
    async def sweep_to_treasury(
        cls,
        from_address: str,
        token_symbol: str = "ETH",
    ) -> Optional[str]:
        if not settings.TREASURY_WALLET_ADDRESS:
            logger.error("sweep.no_treasury_address")
            return None

        w3 = alchemy_service.w3
        if not w3:
            logger.error("sweep.no_web3_connection")
            return None

        from app.app.database import AsyncSessionLocal
        async with AsyncSessionLocal() as db:
            wallet = await WalletRepository.get_wallet_by_address(db, from_address)
            if not wallet:
                logger.error("sweep.wallet_not_found", address=from_address)
                return None

            wallet_svc = WalletService()
            account = wallet_svc.get_account_from_encrypted_key(wallet.encrypted_private_key)

            balance = await alchemy_service.get_eth_balance(from_address)
            if balance < cls.SWEEP_THRESHOLD_ETH:
                logger.info("sweep.balance_too_low", address=from_address, balance=str(balance))
                return None

            try:
                gas_price = await w3.eth.gas_price
                gas_limit = 21000
                gas_cost = Decimal(str(gas_price * gas_limit)) / Decimal("1e18")
                send_amount = balance - gas_cost - Decimal("0.0001")

                if send_amount <= 0:
                    return None

                nonce = await w3.eth.get_transaction_count(account.address)
                tx = {
                    "nonce": nonce,
                    "to": Web3.to_checksum_address(settings.TREASURY_WALLET_ADDRESS),
                    "value": int(send_amount * Decimal("1e18")),
                    "gas": gas_limit,
                    "gasPrice": gas_price,
                    "chainId": await w3.eth.chain_id,
                }
                signed = account.sign_transaction(tx)
                tx_hash_bytes = await w3.eth.send_raw_transaction(signed.rawTransaction)
                tx_hash_hex = tx_hash_bytes.hex()

                sweep_record = TreasuryTransaction(
                    tx_hash=tx_hash_hex,
                    from_address=from_address,
                    to_address=settings.TREASURY_WALLET_ADDRESS,
                    amount=send_amount,
                    token_symbol=token_symbol,
                    network=settings.ALCHEMY_NETWORK,
                    direction=TransactionDirection.SWEEP,
                    notes="Auto-sweep from deposit wallet",
                )
                db.add(sweep_record)
                await WalletRepository.mark_swept(db, wallet.id, tx_hash_hex)
                await db.commit()

                logger.info("sweep.completed", tx_hash=tx_hash_hex[:12])
                return tx_hash_hex

            except Exception as e:
                logger.error("sweep.failed", address=from_address, error=str(e))
                return None

    @staticmethod
    async def check_and_sweep():
        from app.app.database import AsyncSessionLocal
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(DepositWallet).where(
                    DepositWallet.swept == False,
                    DepositWallet.is_active == True,
                )
            )
            wallets = result.scalars().all()

        for wallet in wallets:
            try:
                balance = await alchemy_service.get_eth_balance(wallet.address)
                if balance >= TreasuryService.SWEEP_THRESHOLD_ETH:
                    await TreasuryService.sweep_to_treasury(wallet.address)
            except Exception as e:
                logger.error("sweep.check_failed", address=wallet.address, error=str(e))


@router.get("/balance", response_model=TreasuryBalanceResponse)
async def get_treasury_balance(current_user: User = Depends(require_admin)):
    balances = await TreasuryService.get_treasury_balances()
    prices = await alchemy_service.get_token_prices()
    total_usd = sum(
        balances.get(t, Decimal("0")) * prices.get(t, Decimal("0")) for t in balances
    )
    return TreasuryBalanceResponse(
        address=settings.TREASURY_WALLET_ADDRESS or "not_configured",
        balances=balances,
        total_usd=total_usd,
        network=settings.ALCHEMY_NETWORK,
        updated_at=datetime.datetime.utcnow(),
    )


@router.post("/sweep", response_model=SweepResponse)
async def sweep_wallet(
    data: SweepRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    if not WalletService.is_valid_address(data.wallet_address):
        raise HTTPException(status_code=400, detail="Invalid wallet address")

    tx_hash = await TreasuryService.sweep_to_treasury(data.wallet_address, data.token_symbol)
    if not tx_hash:
        raise HTTPException(status_code=400, detail="Sweep failed or balance too low")

    db.add(AuditLog(
        user_id=current_user.id,
        action=AuditAction.SWEEP_EXECUTED,
        resource_type="wallet",
        resource_id=data.wallet_address,
        details={"tx_hash": tx_hash, "token": data.token_symbol},
    ))
    await db.commit()

    balance = await alchemy_service.get_eth_balance(data.wallet_address)
    return SweepResponse(
        tx_hash=tx_hash,
        from_address=data.wallet_address,
        to_address=settings.TREASURY_WALLET_ADDRESS,
        amount=balance,
        token_symbol=data.token_symbol,
        network=settings.ALCHEMY_NETWORK,
    )


@router.get("/transactions", response_model=List[TreasuryTransactionResponse])
async def list_treasury_transactions(
    page: int = 1,
    per_page: int = 50,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    offset = (page - 1) * per_page
    result = await db.execute(
        select(TreasuryTransaction)
        .order_by(TreasuryTransaction.created_at.desc())
        .offset(offset)
        .limit(per_page)
    )
    return result.scalars().all()
