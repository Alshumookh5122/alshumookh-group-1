from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

try:
    from web3 import Web3
except ModuleNotFoundError:  # pragma: no cover - deployment requirements include web3
    Web3 = None  # type: ignore[assignment]

from app.config import settings

ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"
EVM_ADDRESS_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")
TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"

ERC20_VIEW_ABI: list[dict[str, Any]] = [
    {"constant": True, "inputs": [], "name": "name", "outputs": [{"name": "", "type": "string"}], "type": "function"},
    {"constant": True, "inputs": [], "name": "symbol", "outputs": [{"name": "", "type": "string"}], "type": "function"},
    {"constant": True, "inputs": [], "name": "decimals", "outputs": [{"name": "", "type": "uint8"}], "type": "function"},
    {"constant": True, "inputs": [], "name": "totalSupply", "outputs": [{"name": "", "type": "uint256"}], "type": "function"},
    {"constant": True, "inputs": [], "name": "maxSupply", "outputs": [{"name": "", "type": "uint256"}], "type": "function"},
    {
        "constant": True,
        "inputs": [{"name": "account", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "", "type": "uint256"}],
        "type": "function",
    },
]


@dataclass(frozen=True)
class BlockchainVerification:
    ok: bool
    status: str
    detail: str
    block_number: int | None = None
    contract_address: str | None = None
    amount: str | None = None


def _rpc_url() -> str | None:
    return settings.active_rpc_url


def _web3() -> Web3 | None:
    url = _rpc_url()
    if not url or Web3 is None:
        return None
    return Web3(Web3.HTTPProvider(url, request_kwargs={"timeout": 15}))


def _safe_checksum(address: str | None) -> str | None:
    if not address or not EVM_ADDRESS_RE.match(address):
        return None
    if Web3 is None:
        return address
    return Web3.to_checksum_address(address)


def normalize_token_amount(amount: str | int | Decimal, decimals: int = 18) -> int:
    try:
        value = Decimal(str(amount))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("Invalid token amount") from exc
    if value < 0:
        raise ValueError("Token amount cannot be negative")
    return int(value * (Decimal(10) ** decimals))


def format_token_amount(raw_amount: int | str | Decimal | None, decimals: int = 18) -> str | None:
    if raw_amount is None:
        return None
    value = Decimal(str(raw_amount)) / (Decimal(10) ** decimals)
    return format(value.normalize(), "f")


def _call_contract(address: str, fn_name: str, *args: Any) -> Any:
    w3 = _web3()
    checksum = _safe_checksum(address)
    if w3 is None:
        raise RuntimeError("Ethereum RPC URL is not configured or web3 is not installed.")
    if not checksum:
        raise RuntimeError("Invalid contract address.")
    contract = w3.eth.contract(address=checksum, abi=ERC20_VIEW_ABI)
    return getattr(contract.functions, fn_name)(*args).call()


def get_transaction_receipt(tx_hash: str) -> dict[str, Any] | None:
    w3 = _web3()
    if w3 is None:
        raise RuntimeError("Ethereum RPC URL is not configured or web3 is not installed.")
    receipt = w3.eth.get_transaction_receipt(tx_hash)
    return dict(receipt) if receipt else None


def verify_chain_id() -> dict[str, Any]:
    w3 = _web3()
    rpc = _rpc_url()
    if w3 is None:
        return {
            "rpc_configured": bool(rpc),
            "rpc_connected": False,
            "chain_id_expected": settings.active_chain_id,
            "chain_id_actual": None,
            "chain_id_is_expected": False,
            "error": "ALCHEMY_ETHEREUM_RPC_URL / ETHEREUM_RPC_URL is not configured." if not rpc else "web3 package is not installed in this runtime.",
        }
    try:
        actual = int(w3.eth.chain_id)
        expected = settings.active_chain_id
        return {
            "rpc_configured": True,
            "rpc_connected": True,
            "chain_id_expected": expected,
            "chain_id_actual": actual,
            "chain_id_is_expected": actual == expected,
            "error": None,
        }
    except Exception as exc:
        return {
            "rpc_configured": True,
            "rpc_connected": False,
            "chain_id_expected": settings.active_chain_id,
            "chain_id_actual": None,
            "chain_id_is_expected": False,
            "error": str(exc),
        }


def get_contract_total_supply(contract_address: str, decimals: int = 18) -> str:
    return format_token_amount(_call_contract(contract_address, "totalSupply"), decimals) or "0"


def get_contract_balance(contract_address: str, wallet_address: str, decimals: int = 18) -> str:
    wallet = _safe_checksum(wallet_address)
    if not wallet:
        raise RuntimeError("Invalid wallet address.")
    return format_token_amount(_call_contract(contract_address, "balanceOf", wallet), decimals) or "0"


def get_m1_max_supply(contract_address: str, decimals: int = 18) -> str | None:
    try:
        return format_token_amount(_call_contract(contract_address, "maxSupply"), decimals)
    except Exception:
        return None


def _token_snapshot(label: str, address: str, decimals: int, treasury_wallet: str) -> dict[str, Any]:
    checksum = _safe_checksum(address)
    item: dict[str, Any] = {
        "label": label,
        "address": address,
        "configured": bool(checksum),
        "reachable": False,
        "name": None,
        "symbol": None,
        "decimals": decimals,
        "total_supply": None,
        "max_supply": None,
        "treasury_balance": None,
        "error": None,
    }
    if not checksum:
        item["error"] = "Contract address is not configured or invalid."
        return item
    try:
        item["name"] = _call_contract(checksum, "name")
        item["symbol"] = _call_contract(checksum, "symbol")
        item["decimals"] = int(_call_contract(checksum, "decimals"))
        item["total_supply"] = get_contract_total_supply(checksum, item["decimals"])
        item["treasury_balance"] = get_contract_balance(checksum, treasury_wallet, item["decimals"])
        item["max_supply"] = get_m1_max_supply(checksum, item["decimals"]) if label == "M1" else None
        item["reachable"] = True
    except Exception as exc:
        item["error"] = str(exc)
    return item


def sync_token_contracts() -> dict[str, Any]:
    chain = verify_chain_id()
    treasury = settings.treasury_wallet
    body: dict[str, Any] = {
        "network": settings.token_network,
        "chain_id": settings.chain_id,
        "chain": chain,
        "treasury_wallet": treasury,
        "m1": {
            "official_name": settings.m1_token_name,
            "official_symbol": settings.m1_token_symbol,
            **_token_snapshot("M1", settings.m1_token_contract_address, settings.m1_token_decimals, treasury),
        },
        "sig": {
            "official_name": settings.sig_token_name,
            "official_symbol": settings.sig_token_symbol,
            **_token_snapshot("SIG", settings.sig_token_contract_address, settings.sig_token_decimals, treasury),
        },
    }
    body["rpc_status"] = "connected" if chain.get("rpc_connected") else "not_connected"
    body["contract_reachable"] = bool(body["m1"]["reachable"] and body["sig"]["reachable"])
    body["readiness_status"] = "ready" if chain.get("chain_id_is_expected") and body["contract_reachable"] else "not_ready"
    return body


async def async_sync_token_contracts() -> dict[str, Any]:
    return await asyncio.to_thread(sync_token_contracts)


def _topic_address(topic: Any) -> str:
    raw = topic.hex() if hasattr(topic, "hex") else str(topic)
    raw = raw[2:] if raw.startswith("0x") else raw
    if Web3 is None:
        return "0x" + raw[-40:]
    return Web3.to_checksum_address("0x" + raw[-40:])


def _log_contract(log: Any) -> str | None:
    address = getattr(log, "address", None)
    if address is None and isinstance(log, dict):
        address = log.get("address")
    if not address:
        return None
    return Web3.to_checksum_address(address) if Web3 is not None else address


def _log_topics(log: Any) -> list[Any]:
    topics = getattr(log, "topics", None)
    if topics is None and isinstance(log, dict):
        topics = log.get("topics")
    return list(topics or [])


def _log_data_int(log: Any) -> int:
    data = getattr(log, "data", None)
    if data is None and isinstance(log, dict):
        data = log.get("data")
    raw = data.hex() if hasattr(data, "hex") else str(data)
    return int(raw, 16)


def _find_transfer_event(
    receipt: dict[str, Any],
    *,
    contract_address: str,
    from_wallet: str,
    to_wallet: str,
    amount: str,
    decimals: int,
) -> bool:
    expected_contract = _safe_checksum(contract_address)
    expected_from = _safe_checksum(from_wallet)
    expected_to = _safe_checksum(to_wallet)
    expected_amount = normalize_token_amount(amount, decimals)
    for log in receipt.get("logs", []):
        topics = _log_topics(log)
        if len(topics) < 3:
            continue
        topic0 = topics[0].hex() if hasattr(topics[0], "hex") else str(topics[0])
        topic0_norm = topic0 if topic0.startswith("0x") else "0x" + topic0
        if topic0_norm.lower() != TRANSFER_TOPIC.lower():
            continue
        if _log_contract(log) != expected_contract:
            continue
        if _topic_address(topics[1]).lower() != (expected_from or "").lower():
            continue
        if _topic_address(topics[2]).lower() != (expected_to or "").lower():
            continue
        if _log_data_int(log) == expected_amount:
            return True
    return False


def verify_contract_address(tx_hash: str, expected_contract: str) -> BlockchainVerification:
    receipt = get_transaction_receipt(tx_hash)
    checksum = _safe_checksum(expected_contract)
    if not receipt:
        return BlockchainVerification(False, "not_found", "Transaction receipt was not found.")
    if int(receipt.get("status") or 0) != 1:
        return BlockchainVerification(False, "failed", "Transaction status is not successful.", receipt.get("blockNumber"))
    for log in receipt.get("logs", []):
        if _log_contract(log) == checksum:
            return BlockchainVerification(True, "verified", "Expected contract emitted an event.", receipt.get("blockNumber"), checksum)
    return BlockchainVerification(False, "wrong_contract", "Expected contract was not found in transaction logs.", receipt.get("blockNumber"), checksum)


def verify_m1_mint_event(tx_hash: str, to_wallet: str, amount: str) -> BlockchainVerification:
    receipt = get_transaction_receipt(tx_hash)
    contract = settings.m1_token_contract_address
    if not receipt:
        return BlockchainVerification(False, "not_found", "Transaction receipt was not found.")
    if int(receipt.get("status") or 0) != 1:
        return BlockchainVerification(False, "failed", "Transaction status is not successful.", receipt.get("blockNumber"), contract)
    ok = _find_transfer_event(
        receipt,
        contract_address=contract,
        from_wallet=ZERO_ADDRESS,
        to_wallet=to_wallet,
        amount=amount,
        decimals=settings.m1_token_decimals,
    )
    return BlockchainVerification(
        ok,
        "verified" if ok else "event_mismatch",
        "Mint Transfer event verified." if ok else "Mint Transfer event from zero address was not found or amount/wallet mismatched.",
        receipt.get("blockNumber"),
        contract,
        amount,
    )


def verify_m1_burn_event(tx_hash: str, from_wallet: str, amount: str) -> BlockchainVerification:
    receipt = get_transaction_receipt(tx_hash)
    contract = settings.m1_token_contract_address
    if not receipt:
        return BlockchainVerification(False, "not_found", "Transaction receipt was not found.")
    if int(receipt.get("status") or 0) != 1:
        return BlockchainVerification(False, "failed", "Transaction status is not successful.", receipt.get("blockNumber"), contract)
    ok = _find_transfer_event(
        receipt,
        contract_address=contract,
        from_wallet=from_wallet,
        to_wallet=ZERO_ADDRESS,
        amount=amount,
        decimals=settings.m1_token_decimals,
    )
    return BlockchainVerification(
        ok,
        "verified" if ok else "event_mismatch",
        "Burn Transfer event verified." if ok else "Burn Transfer event to zero address was not found or amount/wallet mismatched.",
        receipt.get("blockNumber"),
        contract,
        amount,
    )
