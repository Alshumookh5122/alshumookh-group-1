"""
Alchemy Service — Web3 interaction, address monitoring, transaction confirmation.
Uses Alchemy's Enhanced APIs for reliable blockchain data.
"""

import asyncio
from decimal import Decimal
from typing import Optional, Dict, Any, List
import httpx
from web3 import AsyncWeb3, Web3
from web3.middleware import async_geth_poa_middleware

from app.app.config import settings
import structlog

logger = structlog.get_logger()

# ERC-20 Transfer event ABI (minimal)
ERC20_TRANSFER_ABI = [
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "name": "from", "type": "address"},
            {"indexed": True, "name": "to", "type": "address"},
            {"indexed": False, "name": "value", "type": "uint256"},
        ],
        "name": "Transfer",
        "type": "event",
    }
]

ERC20_BALANCE_ABI = [
    {
        "constant": True,
        "inputs": [{"name": "_owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "balance", "type": "uint256"}],
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [],
        "name": "decimals",
        "outputs": [{"name": "", "type": "uint8"}],
        "type": "function",
    },
]


class AlchemyService:
    """Wrapper around Alchemy's RPC and enhanced APIs."""

    def __init__(self):
        self.rpc_url = settings.ALCHEMY_RPC_URL
        self.api_key = settings.ALCHEMY_API_KEY
        self.network = settings.ALCHEMY_NETWORK
        self.w3 = AsyncWeb3(AsyncWeb3.AsyncHTTPProvider(self.rpc_url))

        # Add POA middleware for Polygon/BSC
        if "MATIC" in self.network:
            self.w3.middleware_onion.inject(async_geth_poa_middleware, layer=0)

    # ── Connection ───────────────────────────────────────────────────────────

    async def is_connected(self) -> bool:
        try:
            return await self.w3.is_connected()
        except Exception:
            return False

    async def get_block_number(self) -> int:
        return await self.w3.eth.block_number

    # ── Balances ─────────────────────────────────────────────────────────────

    async def get_eth_balance(self, address: str) -> Decimal:
        """Get native ETH/MATIC balance."""
        checksum = Web3.to_checksum_address(address)
        balance_wei = await self.w3.eth.get_balance(checksum)
        return Decimal(str(balance_wei)) / Decimal("1e18")

    async def get_token_balance(self, address: str, token_symbol: str) -> Decimal:
        """Get ERC-20 token balance."""
        if token_symbol == "ETH" or token_symbol == "MATIC":
            return await self.get_eth_balance(address)

        contract_address = settings.TOKEN_CONTRACTS.get(token_symbol)
        if not contract_address:
            raise ValueError(f"Unknown token: {token_symbol}")

        checksum_addr = Web3.to_checksum_address(address)
        contract = self.w3.eth.contract(
            address=Web3.to_checksum_address(contract_address),
            abi=ERC20_BALANCE_ABI,
        )
        decimals = await contract.functions.decimals().call()
        balance = await contract.functions.balanceOf(checksum_addr).call()
        return Decimal(str(balance)) / Decimal(f"1e{decimals}")

    async def get_all_balances(self, address: str) -> Dict[str, Decimal]:
        """Get ETH + all supported token balances."""
        balances: Dict[str, Decimal] = {}
        tasks = [
            ("ETH", self.get_eth_balance(address)),
        ] + [
            (token, self.get_token_balance(address, token))
            for token in settings.SUPPORTED_TOKEN_LIST
            if token != "ETH"
        ]
        results = await asyncio.gather(*[t[1] for t in tasks], return_exceptions=True)
        for (symbol, _), result in zip(tasks, results):
            if isinstance(result, Exception):
                logger.warning("balance.fetch_failed", token=symbol, error=str(result))
                balances[symbol] = Decimal("0")
            else:
                balances[symbol] = result
        return balances

    # ── Transaction Info ──────────────────────────────────────────────────────

    async def get_transaction(self, tx_hash: str) -> Optional[Dict[str, Any]]:
        try:
            tx = await self.w3.eth.get_transaction(tx_hash)
            return dict(tx) if tx else None
        except Exception as e:
            logger.error("tx.fetch_failed", tx_hash=tx_hash, error=str(e))
            return None

    async def get_transaction_receipt(self, tx_hash: str) -> Optional[Dict[str, Any]]:
        try:
            receipt = await self.w3.eth.get_transaction_receipt(tx_hash)
            return dict(receipt) if receipt else None
        except Exception:
            return None

    async def get_confirmation_count(self, tx_hash: str) -> int:
        receipt = await self.get_transaction_receipt(tx_hash)
        if not receipt or not receipt.get("blockNumber"):
            return 0
        current_block = await self.get_block_number()
        return max(0, current_block - receipt["blockNumber"])

    async def is_confirmed(self, tx_hash: str) -> bool:
        count = await self.get_confirmation_count(tx_hash)
        return count >= settings.MIN_CRYPTO_CONFIRMATION_BLOCKS

    # ── Alchemy Enhanced APIs ─────────────────────────────────────────────────

    async def get_asset_transfers(
        self,
        address: str,
        from_block: str = "0x0",
        direction: str = "to",  # "to" or "from"
    ) -> List[Dict[str, Any]]:
        """Use Alchemy's alchemy_getAssetTransfers for rich transfer history."""
        payload = {
            "id": 1,
            "jsonrpc": "2.0",
            "method": "alchemy_getAssetTransfers",
            "params": [{
                "fromBlock": from_block,
                "toBlock": "latest",
                f"{direction}Address": address,
                "category": ["external", "erc20", "internal"],
                "withMetadata": True,
                "excludeZeroValue": True,
                "maxCount": "0x64",  # 100 results
            }],
        }
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(self.rpc_url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            return data.get("result", {}).get("transfers", [])

    async def get_token_metadata(self, contract_address: str) -> Dict[str, Any]:
        """Get token metadata via Alchemy."""
        payload = {
            "id": 1,
            "jsonrpc": "2.0",
            "method": "alchemy_getTokenMetadata",
            "params": [contract_address],
        }
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(self.rpc_url, json=payload)
            resp.raise_for_status()
            return resp.json().get("result", {})

    # ── Webhook Management ────────────────────────────────────────────────────

    async def create_address_activity_webhook(
        self, address: str, webhook_url: str
    ) -> Optional[str]:
        """Register an address for activity monitoring via Alchemy Notify."""
        url = f"https://dashboard.alchemy.com/api/create-webhook"
        headers = {"X-Alchemy-Token": self.api_key, "Content-Type": "application/json"}
        payload = {
            "network": self.network,
            "webhook_type": "ADDRESS_ACTIVITY",
            "webhook_url": webhook_url,
            "addresses": [address],
        }
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(url, json=payload, headers=headers)
                if resp.status_code == 200:
                    data = resp.json()
                    return data.get("data", {}).get("id")
        except Exception as e:
            logger.error("alchemy.webhook_create_failed", address=address, error=str(e))
        return None

    async def add_address_to_webhook(self, webhook_id: str, address: str) -> bool:
        """Add address to existing webhook (more efficient than creating new ones)."""
        url = f"https://dashboard.alchemy.com/api/update-webhook-addresses"
        headers = {"X-Alchemy-Token": self.api_key, "Content-Type": "application/json"}
        payload = {
            "webhook_id": webhook_id,
            "addresses_to_add": [address],
            "addresses_to_remove": [],
        }
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.patch(url, json=payload, headers=headers)
                return resp.status_code == 200
        except Exception:
            return False

    # ── Token Prices (via Alchemy Prices API) ────────────────────────────────

    async def get_token_prices(self) -> Dict[str, Decimal]:
        """Get current token prices in USD via Alchemy Prices API."""
        url = f"https://api.g.alchemy.com/prices/v1/{self.api_key}/tokens/by-symbol"
        symbols = settings.SUPPORTED_TOKEN_LIST
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(url, params={"symbols": ",".join(symbols)})
                resp.raise_for_status()
                data = resp.json()
                prices: Dict[str, Decimal] = {}
                for item in data.get("data", []):
                    symbol = item.get("symbol", "").upper()
                    price = item.get("prices", [{}])[0].get("value", "0")
                    prices[symbol] = Decimal(str(price))
                return prices
        except Exception as e:
            logger.warning("alchemy.price_fetch_failed", error=str(e))
            # Fallback prices for dev/testing
            return {
                "ETH": Decimal("3500"),
                "USDT": Decimal("1"),
                "USDC": Decimal("1"),
                "DAI": Decimal("1"),
                "MATIC": Decimal("0.85"),
            }

    # ── Confirm Transaction (for Celery task) ────────────────────────────────

    @staticmethod
    async def confirm_transaction(payment_id: str, tx_hash: str):
        """Confirm a transaction and update payment status. Called by Celery."""
        from app.app.database import AsyncSessionLocal
        from app.app.models import Payment, PaymentStatus, BlockchainTransaction
        from sqlalchemy import select, update
        import datetime

        service = AlchemyService()
        async with AsyncSessionLocal() as db:
            try:
                count = await service.get_confirmation_count(tx_hash)
                logger.info("tx.confirming", tx_hash=tx_hash, count=count, payment_id=payment_id)

                if count >= settings.MIN_CRYPTO_CONFIRMATION_BLOCKS:
                    # Mark payment complete
                    await db.execute(
                        update(Payment)
                        .where(Payment.id == payment_id)
                        .values(
                            status=PaymentStatus.COMPLETED,
                            confirmation_count=count,
                            completed_at=datetime.datetime.utcnow(),
                        )
                    )
                    await db.commit()
                    logger.info("payment.confirmed", payment_id=payment_id, tx_hash=tx_hash)
                else:
                    # Update count, keep confirming
                    await db.execute(
                        update(Payment)
                        .where(Payment.id == payment_id)
                        .values(confirmation_count=count, status=PaymentStatus.CONFIRMING)
                    )
                    await db.commit()
                    # Re-queue if not yet confirmed
                    if count < settings.MIN_CRYPTO_CONFIRMATION_BLOCKS:
                        raise Exception(f"Only {count} confirmations, need {settings.MIN_CRYPTO_CONFIRMATION_BLOCKS}")
            except Exception as e:
                logger.error("tx.confirmation_error", error=str(e))
                raise


# Singleton
alchemy_service = AlchemyService()
