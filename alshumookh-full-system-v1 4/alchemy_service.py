"""
Alchemy Service — Web3 interaction, address monitoring, transaction confirmation.
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

        # Only init Web3 if API key is set
        if self.api_key:
            self.w3 = AsyncWeb3(AsyncWeb3.AsyncHTTPProvider(self.rpc_url))
            if "MATIC" in self.network:
                self.w3.middleware_onion.inject(async_geth_poa_middleware, layer=0)
        else:
            self.w3 = None

    async def is_connected(self) -> bool:
        if not self.w3:
            return False
        try:
            return await self.w3.is_connected()
        except Exception:
            return False

    async def get_block_number(self) -> int:
        if not self.w3:
            return 0
        return await self.w3.eth.block_number

    async def get_eth_balance(self, address: str) -> Decimal:
        if not self.w3:
            return Decimal("0")
        checksum = Web3.to_checksum_address(address)
        balance_wei = await self.w3.eth.get_balance(checksum)
        return Decimal(str(balance_wei)) / Decimal("1e18")

    async def get_token_balance(self, address: str, token_symbol: str) -> Decimal:
        if token_symbol in ("ETH", "MATIC"):
            return await self.get_eth_balance(address)

        if not self.w3:
            return Decimal("0")

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

    async def get_transaction(self, tx_hash: str) -> Optional[Dict[str, Any]]:
        if not self.w3:
            return None
        try:
            tx = await self.w3.eth.get_transaction(tx_hash)
            return dict(tx) if tx else None
        except Exception as e:
            logger.error("tx.fetch_failed", tx_hash=tx_hash, error=str(e))
            return None

    async def get_transaction_receipt(self, tx_hash: str) -> Optional[Dict[str, Any]]:
        if not self.w3:
            return None
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

    async def get_asset_transfers(
        self, address: str, from_block: str = "0x0", direction: str = "to",
    ) -> List[Dict[str, Any]]:
        payload = {
            "id": 1, "jsonrpc": "2.0",
            "method": "alchemy_getAssetTransfers",
            "params": [{
                "fromBlock": from_block, "toBlock": "latest",
                f"{direction}Address": address,
                "category": ["external", "erc20", "internal"],
                "withMetadata": True, "excludeZeroValue": True,
                "maxCount": "0x64",
            }],
        }
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(self.rpc_url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            return data.get("result", {}).get("transfers", [])

    async def get_token_metadata(self, contract_address: str) -> Dict[str, Any]:
        payload = {
            "id": 1, "jsonrpc": "2.0",
            "method": "alchemy_getTokenMetadata",
            "params": [contract_address],
        }
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(self.rpc_url, json=payload)
            resp.raise_for_status()
            return resp.json().get("result", {})

    async def create_address_activity_webhook(
        self, address: str, webhook_url: str,
    ) -> Optional[str]:
        url = "https://dashboard.alchemy.com/api/create-webhook"
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
        url = "https://dashboard.alchemy.com/api/update-webhook-addresses"
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

    async def get_token_prices(self) -> Dict[str, Decimal]:
        if not self.api_key:
            return self._fallback_prices()

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
            return self._fallback_prices()

    @staticmethod
    def _fallback_prices() -> Dict[str, Decimal]:
        return {
            "ETH": Decimal("3500"),
            "USDT": Decimal("1"),
            "USDC": Decimal("1"),
            "DAI": Decimal("1"),
            "MATIC": Decimal("0.85"),
        }

    @staticmethod
    async def confirm_transaction(payment_id: str, tx_hash: str):
        from app.app.database import AsyncSessionLocal
        from app.app.models import Payment, PaymentStatus
        from sqlalchemy import update
        import datetime

        service = AlchemyService()
        async with AsyncSessionLocal() as db:
            try:
                count = await service.get_confirmation_count(tx_hash)
                logger.info("tx.confirming", tx_hash=tx_hash, count=count, payment_id=payment_id)

                if count >= settings.MIN_CRYPTO_CONFIRMATION_BLOCKS:
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
                    await db.execute(
                        update(Payment)
                        .where(Payment.id == payment_id)
                        .values(confirmation_count=count, status=PaymentStatus.CONFIRMING)
                    )
                    await db.commit()
                    if count < settings.MIN_CRYPTO_CONFIRMATION_BLOCKS:
                        raise Exception(f"Only {count} confirmations, need {settings.MIN_CRYPTO_CONFIRMATION_BLOCKS}")
            except Exception as e:
                logger.error("tx.confirmation_error", error=str(e))
                raise


# Singleton
alchemy_service = AlchemyService()
