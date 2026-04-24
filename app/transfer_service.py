from __future__ import annotations

from decimal import Decimal
from typing import Any

from eth_account import Account
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tronpy.keys import PrivateKey
from web3 import Web3

from app.audit_service import log_event
from app.config import get_settings
from app.models import AuditLog, Network, OrderStatus, PaymentOrder
from app.wallet_service import evm_client, tron_client

settings = get_settings()

ERC20_ABI = [
    {
        'constant': False,
        'inputs': [
            {'name': '_to', 'type': 'address'},
            {'name': '_value', 'type': 'uint256'},
        ],
        'name': 'transfer',
        'outputs': [{'name': '', 'type': 'bool'}],
        'payable': False,
        'stateMutability': 'nonpayable',
        'type': 'function',
    }
]

TRC20_ABI = [
    {
        'name': 'transfer',
        'type': 'Function',
        'stateMutability': 'Nonpayable',
        'inputs': [
            {'name': '_to', 'type': 'address'},
            {'name': '_value', 'type': 'uint256'},
        ],
        'outputs': [{'type': 'bool'}],
    }
]


def _to_decimal(value: Any) -> Decimal:
    if value is None:
        return Decimal('0')
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _normalized_symbol(symbol: str | None) -> str:
    return (symbol or '').strip().upper()


def auto_payout_enabled() -> bool:
    return settings.auto_payout_enabled and bool(settings.eth_treasury_private_key or settings.tron_treasury_private_key)


async def payout_already_sent(db: AsyncSession, order_id) -> bool:
    result = await db.execute(
        select(AuditLog.id).where(AuditLog.order_id == order_id, AuditLog.event_type == 'CRYPTO_PAYOUT_SUCCESS').limit(1)
    )
    return result.scalar_one_or_none() is not None


async def send_usdt_payout(order: PaymentOrder) -> dict[str, Any]:
    amount = _to_decimal(order.crypto_amount)
    if amount <= 0:
        raise ValueError('Order crypto amount is missing or invalid for payout')

    if order.network == Network.ETHEREUM:
        return await _send_erc20_usdt(order.user_wallet_address, amount)
    if order.network == Network.TRON:
        return await _send_trc20_usdt(order.user_wallet_address, amount)
    raise ValueError(f'Unsupported network {order.network}')


async def _send_erc20_usdt(to_address: str, amount: Decimal) -> dict[str, Any]:
    if not settings.eth_treasury_private_key:
        raise ValueError('ETH_TREASURY_PRIVATE_KEY is not configured')

    client = evm_client()
    sender = Web3.to_checksum_address(settings.eth_treasury_address)
    recipient = Web3.to_checksum_address(to_address)
    contract_address = Web3.to_checksum_address(settings.usdt_eth_contract)
    contract = client.eth.contract(address=contract_address, abi=ERC20_ABI)

    decimals = 6  # USDT on Ethereum
    value = int(amount * Decimal(10**decimals))
    nonce = client.eth.get_transaction_count(sender)
    gas_price = client.eth.gas_price
    chain_id = client.eth.chain_id

    tx = contract.functions.transfer(recipient, value).build_transaction(
        {
            'from': sender,
            'nonce': nonce,
            'gasPrice': gas_price,
            'chainId': chain_id,
        }
    )
    if 'gas' not in tx:
        tx['gas'] = client.eth.estimate_gas(tx)

    signed = Account.sign_transaction(tx, settings.eth_treasury_private_key)
    tx_hash = client.eth.send_raw_transaction(signed.raw_transaction)
    return {
        'network': 'ethereum',
        'asset': 'USDT',
        'tx_hash': tx_hash.hex(),
        'from_address': sender,
        'to_address': recipient,
        'amount': str(amount),
        'contract': contract_address,
    }


async def _send_trc20_usdt(to_address: str, amount: Decimal) -> dict[str, Any]:
    if not settings.tron_treasury_private_key:
        raise ValueError('TRON_TREASURY_PRIVATE_KEY is not configured')

    client = tron_client()
    private_key = PrivateKey(bytes.fromhex(settings.tron_treasury_private_key))
    owner = private_key.public_key.to_base58check_address()
    contract = client.get_contract(settings.usdt_tron_contract)

    decimals = 6  # USDT on Tron
    value = int(amount * Decimal(10**decimals))
    txn = (
        contract.functions.transfer(to_address, value)
        .with_owner(owner)
        .fee_limit(20_000_000)
        .build()
        .sign(private_key)
    )
    receipt = txn.broadcast()

    txid = getattr(receipt, 'txid', None)
    if txid is None and isinstance(receipt, dict):
        txid = receipt.get('txid') or receipt.get('transaction', {}).get('txID')

    return {
        'network': 'tron',
        'asset': 'USDT',
        'tx_hash': txid,
        'from_address': owner,
        'to_address': to_address,
        'amount': str(amount),
        'contract': settings.usdt_tron_contract,
    }


async def handle_order_completed(db: AsyncSession, order: PaymentOrder, webhook_decoded: dict[str, Any]) -> dict[str, Any]:
    order.status = OrderStatus.COMPLETED
    order.webhook_payload = webhook_decoded
    await db.commit()
    await db.refresh(order)
    await log_event(db, 'ORDER_MARKED_COMPLETED', {'external_id': order.external_id}, order.id)

    if await payout_already_sent(db, order.id):
        return {'status': 'already_paid'}

    if not auto_payout_enabled():
        await log_event(
            db,
            'CRYPTO_PAYOUT_SKIPPED',
            {'reason': 'AUTO_PAYOUT_DISABLED_OR_KEYS_MISSING', 'external_id': order.external_id},
            order.id,
        )
        return {'status': 'skipped'}

    try:
        payout = await send_usdt_payout(order)
        await log_event(db, 'CRYPTO_PAYOUT_SUCCESS', payout, order.id)
        return {'status': 'paid', 'payout': payout}
    except Exception as exc:
        await log_event(
            db,
            'CRYPTO_PAYOUT_FAILED',
            {'error': str(exc), 'external_id': order.external_id},
            order.id,
        )
        raise
