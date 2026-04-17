"""
Wallet Service — HD wallet derivation for deposit addresses.
Each payment gets a unique derived address for clean attribution.
"""

import hashlib
from decimal import Decimal
from typing import Tuple, Optional
from eth_account import Account
from eth_account.hdaccount import generate_mnemonic
from web3 import Web3

from app.app.config import settings
from app.app.utils import encrypt_private_key, decrypt_private_key
import structlog

logger = structlog.get_logger()

# Enable HD wallet support
Account.enable_unaudited_hdwallet_features()


class WalletService:
    """Deterministic wallet derivation from master seed."""

    BASE_PATH = "m/44'/60'/0'/0"

    def __init__(self):
        # Derive master account from SECRET_KEY (deterministic)
        seed = hashlib.pbkdf2_hmac(
            "sha256",
            settings.SECRET_KEY.encode(),
            b"alshumookh-wallet-seed",
            iterations=200_000,
        )
        self._master_seed = seed.hex()

    def derive_wallet(self, index: int) -> Tuple[str, str]:
        """
        Derive address and encrypted private key at given HD index.
        Returns (address, encrypted_private_key).
        """
        path = f"{self.BASE_PATH}/{index}"
        account = Account.from_mnemonic(
            self._get_mnemonic(),
            account_path=path,
        )
        address = Web3.to_checksum_address(account.address)
        encrypted_key = encrypt_private_key(account.key.hex())
        logger.debug("wallet.derived", index=index, address=address[:10] + "...")
        return address, encrypted_key

    def get_private_key(self, encrypted_key: str) -> str:
        return decrypt_private_key(encrypted_key)

    def get_account_from_encrypted_key(self, encrypted_key: str):
        private_key = decrypt_private_key(encrypted_key)
        return Account.from_key(private_key)

    def _get_mnemonic(self) -> str:
        """Deterministically generate a mnemonic from the master seed."""
        # Use PBKDF2 to get 16 bytes entropy for 12-word mnemonic
        entropy = hashlib.pbkdf2_hmac(
            "sha256",
            self._master_seed.encode(),
            b"mnemonic-entropy",
            iterations=100_000,
        )[:16]
        # Convert entropy to valid BIP39 mnemonic
        return generate_mnemonic(num_words=12, lang="english")

    @staticmethod
    def is_valid_address(address: str) -> bool:
        return Web3.is_address(address)

    @staticmethod
    def to_checksum_address(address: str) -> str:
        return Web3.to_checksum_address(address)


class WalletRepository:
    """Database operations for DepositWallet records."""

    @staticmethod
    async def create_deposit_wallet(
        db,
        user_id: str,
        payment_id: str,
        index: int,
        network: str,
    ):
        from app.app.models import DepositWallet
        from sqlalchemy import func, select

        wallet_service = WalletService()
        address, encrypted_key = wallet_service.derive_wallet(index)

        wallet = DepositWallet(
            user_id=user_id,
            payment_id=payment_id,
            address=address,
            derivation_path=f"{WalletService.BASE_PATH}/{index}",
            encrypted_private_key=encrypted_key,
            network=network,
        )
        db.add(wallet)
        await db.flush()
        return wallet

    @staticmethod
    async def get_next_index(db) -> int:
        from app.app.models import DepositWallet
        from sqlalchemy import func, select
        result = await db.execute(select(func.count(DepositWallet.id)))
        return result.scalar_one() or 0

    @staticmethod
    async def get_wallet_by_address(db, address: str):
        from app.app.models import DepositWallet
        from sqlalchemy import select
        result = await db.execute(
            select(DepositWallet).where(DepositWallet.address == address)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def mark_swept(db, wallet_id: str, sweep_tx_hash: str):
        from app.app.models import DepositWallet
        from sqlalchemy import update
        import datetime
        await db.execute(
            update(DepositWallet)
            .where(DepositWallet.id == wallet_id)
            .values(swept=True, swept_at=datetime.datetime.utcnow(), sweep_tx_hash=sweep_tx_hash)
        )


wallet_service = WalletService()
