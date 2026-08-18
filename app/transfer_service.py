"""
ALSHUMOOKH — USDT Outbound Transfer Engine
Supports: Ethereum (ERC-20) | TRON (TRC-20) | Base (ERC-20)
Full approval workflow + audit trail + outbound DB tracking.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from eth_account import Account
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tronpy.keys import PrivateKey
from web3 import Web3

from app.audit_service import log_event
from app.config import get_settings
from app.models import (
    AuditLog,
    Network,
    OrderStatus,
    OutboundTransfer,
    OutboundTransferStatus,
    PaymentOrder,
)
from app.alchemy_service import alchemy_rpc_url
from app.wallet_service import evm_client, tron_client

settings = get_settings()

ETHEREUM_MAINNET_CHAIN_ID = 1
ETHEREUM_EXPLORER_TX_BASE = "https://etherscan.io/tx/"
SUPPORTED_ETHEREUM_ERC20 = {
    "USDT": {"decimals": 6, "contract": lambda: settings.usdt_eth_contract},
    "SIG": {"decimals": 18, "contract": lambda: settings.sig_contract_address},
}

# ─── ABIs ─────────────────────────────────────────────────────────────────────

ERC20_ABI = [
    {
        "constant": False,
        "inputs": [
            {"name": "_to", "type": "address"},
            {"name": "_value", "type": "uint256"},
        ],
        "name": "transfer",
        "outputs": [{"name": "", "type": "bool"}],
        "payable": False,
        "stateMutability": "nonpayable",
        "type": "function",
    },
    # transferFrom: used when operator wallet spends tokens on behalf of treasury (Ledger)
    {
        "constant": False,
        "inputs": [
            {"name": "_from", "type": "address"},
            {"name": "_to", "type": "address"},
            {"name": "_value", "type": "uint256"},
        ],
        "name": "transferFrom",
        "outputs": [{"name": "", "type": "bool"}],
        "payable": False,
        "stateMutability": "nonpayable",
        "type": "function",
    },
]

TRC20_ABI = [
    {
        "name": "transfer",
        "type": "Function",
        "stateMutability": "Nonpayable",
        "inputs": [
            {"name": "_to", "type": "address"},
            {"name": "_value", "type": "uint256"},
        ],
        "outputs": [{"type": "bool"}],
    }
]

# ─── Helpers ──────────────────────────────────────────────────────────────────

def _to_decimal(value: Any) -> Decimal:
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _normalized_symbol(symbol: str | None) -> str:
    return (symbol or "").strip().upper()


def auto_payout_enabled() -> bool:
    return settings.auto_payout_enabled and bool(
        settings.eth_private_key
        or settings.eth_treasury_private_key
        or settings.tron_treasury_private_key
    )


def _ethereum_rpc_url() -> str:
    return (
        settings.alchemy_ethereum_rpc_url
        or settings.alchemy_eth_rpc_url
        or settings.ethereum_rpc_url
        or alchemy_rpc_url(Network.ETHEREUM)
    )


def ethereum_mainnet_client() -> Web3:
    return Web3(Web3.HTTPProvider(_ethereum_rpc_url()))


def _eth_broadcast_private_key() -> str:
    private_key = (settings.eth_private_key or settings.eth_treasury_private_key or "").strip()
    if not private_key:
        raise ValueError("ETH_PRIVATE_KEY is not configured")
    return private_key


def _sender_from_private_key(private_key: str) -> str:
    """
    Derive the operator wallet address from ETH_PRIVATE_KEY.
    The operator wallet (MetaMask software) signs and pays gas.
    It is DIFFERENT from ETH_TREASURY_ADDRESS (Ledger hardware wallet).
    """
    account = Account.from_key(private_key)
    operator = Web3.to_checksum_address(account.address)
    # Optionally verify against explicit ETH_OPERATOR_ADDRESS if configured
    configured = (settings.eth_operator_address or "").strip()
    if configured and configured != "0x0000000000000000000000000000000000000000":
        configured_checksum = Web3.to_checksum_address(configured)
        if configured_checksum != operator:
            raise ValueError(
                "ETH_OPERATOR_ADDRESS does not match the address derived from ETH_PRIVATE_KEY"
            )
    return operator


def _treasury_address() -> str:
    """
    Return the treasury (Ledger) wallet address that holds the tokens.
    Tokens are transferred FROM this address via transferFrom().
    """
    addr = (settings.eth_treasury_address or "").strip()
    if not addr or addr == "0x0000000000000000000000000000000000000000":
        raise ValueError(
            "ETH_TREASURY_ADDRESS is not configured. "
            "Set it to your Ledger wallet address: 0xBD682cfD8382a90adfDd6745780D3D7959c4d939"
        )
    return Web3.to_checksum_address(addr)


def _ethereum_token_config(asset: str) -> tuple[str, int, str]:
    symbol = _normalized_symbol(asset)
    token = SUPPORTED_ETHEREUM_ERC20.get(symbol)
    if not token:
        raise ValueError(f"Unsupported Ethereum ERC-20 asset: {asset}. Supported assets: USDT, SIG")
    contract_address = token["contract"]()
    if not contract_address:
        raise ValueError(f"{symbol} contract address is not configured")
    return symbol, int(token["decimals"]), Web3.to_checksum_address(str(contract_address))


def _base_rpc_url() -> str:
    """Return the Base network RPC URL (Alchemy or fallback public)."""
    return (
        getattr(settings, "alchemy_base_rpc_url", None)
        or getattr(settings, "base_rpc_url", None)
        or "https://mainnet.base.org"
    )


def base_client() -> Web3:
    """Return a Web3 instance connected to the Base network."""
    return Web3(Web3.HTTPProvider(_base_rpc_url()))


async def estimate_usdt_transfer_fee(
    network: str = "ethereum",
    to_address: str | None = None,
    amount: Decimal | str | int | float | None = None,
) -> dict[str, Any]:
    """
    Estimate the native network fee for a USDT/USDC transfer.
    This is a preflight estimate for dashboard invoicing; it does not sign or broadcast.
    """
    normalized = (network or "ethereum").strip().lower()
    amount_dec = _to_decimal(amount)

    if normalized in {"tron", "trx", "trc20"}:
        fee_limit_sun = 20_000_000
        return {
            "network": "tron",
            "asset": "USDT",
            "native_symbol": "TRX",
            "amount": str(amount_dec),
            "gas_limit": fee_limit_sun,
            "gas_price_wei": None,
            "estimated_native_fee": "20",
            "estimated_fee_label": "20 TRX fee limit",
            "source": "tron_fee_limit",
        }

    if normalized == "base":
        client = base_client()
        default_gas_limit = 65000
        native_symbol = "ETH"
    else:
        client = evm_client()
        default_gas_limit = 65000
        native_symbol = "ETH"

    gas_price = None
    gas_limit = default_gas_limit
    source = "default_erc20_transfer"
    try:
        gas_price = int(client.eth.gas_price)
        sender = settings.eth_treasury_address
        if normalized == "base":
            contract_address = (
                getattr(settings, "usdt_base_contract", None)
                or "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
            )
        else:
            contract_address = settings.usdt_eth_contract
        if sender and to_address and contract_address:
            contract = client.eth.contract(address=Web3.to_checksum_address(contract_address), abi=ERC20_ABI)
            recipient = Web3.to_checksum_address(to_address)
            value = int(amount_dec * Decimal(10**6)) if amount_dec > 0 else 1
            gas_limit = int(
                contract.functions.transfer(recipient, value).estimate_gas(
                    {"from": Web3.to_checksum_address(sender)}
                )
            )
            source = "rpc_estimate_gas"
        else:
            source = "rpc_gas_price_default_limit"
    except Exception as exc:
        if gas_price is None:
            gas_price = 1_500_000_000 if normalized == "base" else 25_000_000_000
        source = f"fallback_estimate: {exc}"

    total_wei = int(gas_price) * int(gas_limit)
    native_fee = Decimal(total_wei) / Decimal(10**18)
    return {
        "network": "base" if normalized == "base" else "ethereum",
        "asset": "USDT" if normalized != "base" else "USDC",
        "native_symbol": native_symbol,
        "amount": str(amount_dec),
        "gas_limit": gas_limit,
        "gas_price_wei": str(gas_price),
        "gas_price_gwei": str(Decimal(int(gas_price)) / Decimal(10**9)),
        "estimated_native_fee": format(native_fee, "f"),
        "estimated_fee_label": f"{native_fee:.8f} {native_symbol}",
        "source": source,
    }


# ─── Duplicate payout guard ────────────────────────────────────────────────────

async def payout_already_sent(db: AsyncSession, order_id: str) -> bool:
    result = await db.execute(
        select(AuditLog.id)
        .where(
            AuditLog.order_id == order_id,
            AuditLog.event_type == "CRYPTO_PAYOUT_SUCCESS",
        )
        .limit(1)
    )
    return result.scalar_one_or_none() is not None


# ─── Network-specific send functions ──────────────────────────────────────────

async def _send_ethereum_erc20(to_address: str, amount: Decimal, asset: str = "USDT") -> dict[str, Any]:
    """
    Sign and broadcast a USDT or SIG transferFrom on Ethereum Mainnet.

    Architecture:
    - Treasury (Ledger) 0xBD682... holds the tokens and has pre-approved the operator.
    - Operator (MetaMask) 0x620a850... signs the tx and pays ETH gas.
    - Uses transferFrom(treasury, recipient, amount) — NOT transfer().
    Prerequisite: Ledger wallet must call approve(operator, amount) once on Etherscan.
    """
    symbol, decimals, contract_address = _ethereum_token_config(asset)
    private_key = _eth_broadcast_private_key()
    client = ethereum_mainnet_client()
    chain_id = int(client.eth.chain_id)
    if chain_id != ETHEREUM_MAINNET_CHAIN_ID:
        raise ValueError(
            f"Invalid Ethereum chainId {chain_id}; "
            "production broadcast requires Ethereum Mainnet chainId 1"
        )

    # Operator: signs tx, pays gas (MetaMask software wallet)
    operator = _sender_from_private_key(private_key)
    # Treasury: holds tokens (Ledger hardware wallet — must have approved operator)
    treasury = _treasury_address()
    recipient = Web3.to_checksum_address(to_address)
    contract = client.eth.contract(address=contract_address, abi=ERC20_ABI)

    value = int(amount * Decimal(10**decimals))
    if value <= 0:
        raise ValueError("Transfer amount must be greater than zero")

    nonce = client.eth.get_transaction_count(operator, "pending")
    gas_price = int(client.eth.gas_price)

    # transferFrom: operator spends from treasury (Ledger) to recipient
    tx = contract.functions.transferFrom(treasury, recipient, value).build_transaction(
        {
            "from": operator,
            "nonce": nonce,
            "gasPrice": gas_price,
            "chainId": chain_id,
        }
    )
    tx["gas"] = int(client.eth.estimate_gas(tx))

    signed = Account.sign_transaction(tx, private_key)
    raw_transaction = getattr(signed, "raw_transaction", None) or getattr(signed, "rawTransaction")
    tx_hash = client.eth.send_raw_transaction(raw_transaction)
    tx_hash_hex = tx_hash.hex()

    return {
        "network": "ethereum",
        "asset": symbol,
        "tx_hash": tx_hash_hex,
        "from_address": treasury,       # tokens come FROM Ledger treasury
        "operator_address": operator,   # operator signs and pays gas
        "to_address": recipient,
        "amount": str(amount),
        "decimals": decimals,
        "contract": contract_address,
        "chain_id": chain_id,
        "explorer_url": f"{ETHEREUM_EXPLORER_TX_BASE}{tx_hash_hex}",
    }


async def _send_erc20_usdt(to_address: str, amount: Decimal, network: str = "ethereum") -> dict[str, Any]:
    """Send USDT via ERC-20 on Ethereum or Base."""
    if network != "base":
        return await _send_ethereum_erc20(to_address, amount, "USDT")

    if not settings.eth_treasury_private_key and not settings.eth_private_key:
        raise ValueError("ETH_PRIVATE_KEY is not configured")
    if not settings.eth_treasury_address:
        raise ValueError("ETH_TREASURY_ADDRESS is not configured")

    if network == "base":
        client = base_client()
        contract_address = Web3.to_checksum_address(
            getattr(settings, "usdt_base_contract", None)
            or "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"  # USDC on Base (USDT not native, use USDC)
        )
        explorer_base = "https://basescan.org/tx/"
    else:
        client = evm_client()
        contract_address = Web3.to_checksum_address(settings.usdt_eth_contract)
        explorer_base = "https://etherscan.io/tx/"

    sender = Web3.to_checksum_address(settings.eth_treasury_address)
    recipient = Web3.to_checksum_address(to_address)
    contract = client.eth.contract(address=contract_address, abi=ERC20_ABI)

    decimals = 6  # USDT/USDC standard decimals
    value = int(amount * Decimal(10**decimals))
    nonce = client.eth.get_transaction_count(sender)
    gas_price = client.eth.gas_price
    chain_id = client.eth.chain_id

    tx = contract.functions.transfer(recipient, value).build_transaction(
        {
            "from": sender,
            "nonce": nonce,
            "gasPrice": gas_price,
            "chainId": chain_id,
        }
    )
    if "gas" not in tx:
        tx["gas"] = client.eth.estimate_gas(tx)

    private_key = _eth_broadcast_private_key()
    signed = Account.sign_transaction(tx, private_key)
    raw_transaction = getattr(signed, "raw_transaction", None) or getattr(signed, "rawTransaction")
    tx_hash = client.eth.send_raw_transaction(raw_transaction)
    tx_hash_hex = tx_hash.hex()

    return {
        "network": network,
        "asset": "USDT",
        "tx_hash": tx_hash_hex,
        "from_address": sender,
        "to_address": recipient,
        "amount": str(amount),
        "contract": contract_address,
        "explorer_url": f"{explorer_base}{tx_hash_hex}",
    }


async def _send_trc20_usdt(to_address: str, amount: Decimal) -> dict[str, Any]:
    """Send USDT via TRC-20 on TRON."""
    if not settings.tron_treasury_private_key:
        raise ValueError("TRON_TREASURY_PRIVATE_KEY is not configured")
    if not settings.usdt_tron_contract:
        raise ValueError("USDT_TRON_CONTRACT is not configured")

    client = tron_client()
    private_key = PrivateKey(bytes.fromhex(settings.tron_treasury_private_key))
    owner = private_key.public_key.to_base58check_address()
    contract = client.get_contract(settings.usdt_tron_contract)

    decimals = 6
    value = int(amount * Decimal(10**decimals))
    txn = (
        contract.functions.transfer(to_address, value)
        .with_owner(owner)
        .fee_limit(20_000_000)
        .build()
        .sign(private_key)
    )
    receipt = txn.broadcast()

    txid = getattr(receipt, "txid", None)
    if txid is None and isinstance(receipt, dict):
        txid = receipt.get("txid") or receipt.get("transaction", {}).get("txID")

    return {
        "network": "tron",
        "asset": "USDT",
        "tx_hash": txid,
        "from_address": owner,
        "to_address": to_address,
        "amount": str(amount),
        "contract": settings.usdt_tron_contract,
        "explorer_url": f"https://tronscan.org/#/transaction/{txid}",
    }


# ─── Public send dispatcher ────────────────────────────────────────────────────

async def send_usdt_payout(order: PaymentOrder) -> dict[str, Any]:
    """Dispatch USDT payout based on order network."""
    amount = _to_decimal(order.crypto_amount)
    if amount <= 0:
        raise ValueError("Order crypto amount is missing or invalid for payout")

    if order.network == Network.ETHEREUM:
        return await _send_erc20_usdt(order.user_wallet_address, amount, "ethereum")
    if order.network == Network.BASE:
        return await _send_erc20_usdt(order.user_wallet_address, amount, "base")
    if order.network == Network.TRON:
        return await _send_trc20_usdt(order.user_wallet_address, amount)
    raise ValueError(f"Unsupported network {order.network}")


# ─── OutboundTransfer DB record management ────────────────────────────────────

async def create_outbound_transfer(
    db: AsyncSession,
    *,
    to_address: str,
    amount: Decimal,
    network: str,
    asset: str = "USDT",
    order_id: str | None = None,
    payload_id: str | None = None,
    tokenization_job_id: str | None = None,
    callback_url: str | None = None,
    initiated_by: str | None = "system",
    notes: str | None = None,
) -> OutboundTransfer:
    """Create a pending outbound transfer record (before broadcasting)."""
    # Guard: prevent self-transfers where the destination equals the treasury source wallet.
    # Such transfers result in From Address = To Address in reports and serve no purpose.
    try:
        treasury = _treasury_address()
        if to_address and treasury and to_address.strip().lower() == treasury.lower():
            raise ValueError(
                f"Self-transfer rejected: to_address ({to_address}) matches the treasury "
                f"source wallet. This would create a circular transaction."
            )
    except ValueError:
        raise
    except Exception:
        pass  # if treasury address is not configured, skip the check

    ot = OutboundTransfer(
        to_address=to_address,
        amount=amount,
        network=network,
        asset=asset,
        order_id=order_id,
        payload_id=payload_id,
        tokenization_job_id=tokenization_job_id,
        callback_url=callback_url,
        initiated_by=initiated_by,
        notes=notes,
        status=OutboundTransferStatus.PENDING.value,
    )
    db.add(ot)
    await db.commit()
    await db.refresh(ot)
    return ot


async def approve_outbound_transfer(
    db: AsyncSession,
    transfer_id: str,
    approved_by: str = "admin",
) -> OutboundTransfer:
    """Mark a pending transfer as approved and ready to broadcast."""
    result = await db.execute(
        select(OutboundTransfer).where(OutboundTransfer.id == transfer_id)
    )
    ot = result.scalar_one_or_none()
    if not ot:
        raise ValueError(f"OutboundTransfer {transfer_id} not found")
    if ot.status not in (
        OutboundTransferStatus.PENDING.value,
        OutboundTransferStatus.AWAITING_APPROVAL.value,
    ):
        raise ValueError(f"Transfer is in status {ot.status}, cannot approve")

    ot.status = OutboundTransferStatus.APPROVED.value
    ot.approved_by = approved_by
    ot.approved_at = datetime.now(tz=timezone.utc)
    await db.commit()
    await db.refresh(ot)
    return ot


async def cancel_outbound_transfer(
    db: AsyncSession,
    transfer_id: str,
    cancelled_by: str = "admin",
    reason: str | None = None,
) -> OutboundTransfer:
    """Cancel a pending/awaiting transfer."""
    result = await db.execute(
        select(OutboundTransfer).where(OutboundTransfer.id == transfer_id)
    )
    ot = result.scalar_one_or_none()
    if not ot:
        raise ValueError(f"OutboundTransfer {transfer_id} not found")
    if ot.status in (
        OutboundTransferStatus.COMPLETED.value,
        OutboundTransferStatus.BROADCASTING.value,
    ):
        raise ValueError(f"Cannot cancel transfer in status {ot.status}")

    ot.status = OutboundTransferStatus.CANCELLED.value
    ot.cancelled_by = cancelled_by
    ot.cancelled_at = datetime.now(tz=timezone.utc)
    ot.cancel_reason = reason
    await db.commit()
    await db.refresh(ot)
    return ot


async def broadcast_outbound_transfer(
    db: AsyncSession,
    transfer_id: str,
) -> OutboundTransfer:
    """
    Broadcast an approved OutboundTransfer to the blockchain.
    Updates status to BROADCASTING → PENDING_CONFIRMATION or FAILED.
    """
    result = await db.execute(
        select(OutboundTransfer).where(OutboundTransfer.id == transfer_id)
    )
    ot = result.scalar_one_or_none()
    if not ot:
        raise ValueError(f"OutboundTransfer {transfer_id} not found")
    if ot.status != OutboundTransferStatus.APPROVED.value:
        raise ValueError(f"Transfer must be APPROVED before broadcasting (current: {ot.status})")

    ot.status = OutboundTransferStatus.BROADCASTING.value
    ot.broadcasted_at = datetime.now(tz=timezone.utc)
    await db.commit()

    try:
        network = (ot.network or "ethereum").lower()
        amount = _to_decimal(ot.amount)
        asset = _normalized_symbol(ot.asset or "USDT")

        if network in ("ethereum", "eth"):
            result_data = await _send_ethereum_erc20(ot.to_address, amount, asset)
        elif network == "base":
            if asset != "USDT":
                raise ValueError("Base broadcast currently supports USDT/USDC-compatible payout only")
            result_data = await _send_erc20_usdt(ot.to_address, amount, "base")
        elif network in ("tron", "trx"):
            if asset != "USDT":
                raise ValueError("TRON broadcast currently supports USDT only")
            result_data = await _send_trc20_usdt(ot.to_address, amount)
        else:
            raise ValueError(f"Unsupported network: {network}")

        ot.tx_hash = result_data.get("tx_hash")
        ot.from_address = result_data.get("from_address")
        ot.contract_address = result_data.get("contract")
        ot.explorer_url = result_data.get("explorer_url")
        ot.raw_result = result_data
        ot.status = OutboundTransferStatus.PENDING_CONFIRMATION.value
        ot.completed_at = None
        await db.commit()
        await db.refresh(ot)

        await log_event(
            db,
            "OUTBOUND_TRANSFER_BROADCASTED",
            {"transfer_id": transfer_id, **result_data},
            ot.order_id,
        )

    except Exception as exc:
        ot.status = OutboundTransferStatus.FAILED.value
        ot.error_message = str(exc)
        ot.retry_count = (ot.retry_count or 0) + 1
        ot.last_retry_at = datetime.now(tz=timezone.utc)
        await db.commit()
        await db.refresh(ot)

        await log_event(
            db,
            "OUTBOUND_TRANSFER_FAILED",
            {"transfer_id": transfer_id, "error": str(exc)},
            ot.order_id,
        )
        raise

    return ot


# ─── Legacy: handle order completed (backwards compatible) ────────────────────

async def handle_order_completed(
    db: AsyncSession,
    order: PaymentOrder,
    webhook_decoded: dict[str, Any],
) -> dict[str, Any]:
    from app.models import Provider

    order.status = OrderStatus.COMPLETED
    order.webhook_payload = webhook_decoded
    await db.commit()
    await db.refresh(order)
    await log_event(
        db,
        "ORDER_MARKED_COMPLETED",
        {"external_id": order.external_id},
        order.id,
    )

    if await payout_already_sent(db, order.id):
        return {"status": "already_paid"}

    if order.provider in {Provider.COINBASE, Provider.MOONPAY}:
        await log_event(
            db,
            "CRYPTO_PAYOUT_SKIPPED",
            {
                "reason": "PROVIDER_DELIVERS_DIRECTLY_TO_TREASURY_WALLET",
                "external_id": order.external_id,
            },
            order.id,
        )
        return {"status": "skipped"}

    if not auto_payout_enabled():
        await log_event(
            db,
            "CRYPTO_PAYOUT_SKIPPED",
            {
                "reason": "AUTO_PAYOUT_DISABLED_OR_KEYS_MISSING",
                "external_id": order.external_id,
            },
            order.id,
        )
        return {"status": "skipped"}

    try:
        payout = await send_usdt_payout(order)
        await log_event(db, "CRYPTO_PAYOUT_SUCCESS", payout, order.id)
        return {"status": "paid", "payout": payout}
    except Exception as exc:
        await log_event(
            db,
            "CRYPTO_PAYOUT_FAILED",
            {"error": str(exc), "external_id": order.external_id},
            order.id,
        )
        raise
