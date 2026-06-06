from __future__ import annotations

import hashlib
import hmac
import json
import re
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from eth_account import Account
from eth_account.messages import encode_defunct
from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit_service import log_event
from app.config import settings
from app.database import get_db
from app.deps import AdminKey, DbSession
from app.models import (
    ApiSignature,
    M1AuditLog,
    M1BlockchainConfirmation,
    M1FundReserve,
    M1MintRequest,
    M1OracleRead,
    M1RedeemRequest,
    M1ReserveSnapshot,
    WalletVerification,
    WebhookEvent,
)
from app.request_utils import get_client_ip

router = APIRouter(tags=["m1-funds"])

DEFAULT_FUND_ID = "M1-ALSHUMOOKH-001"
WALLET_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")
TX_RE = re.compile(r"^0x[a-fA-F0-9]{64}$")


class ReserveUpdateIn(BaseModel):
    fund_id: str = DEFAULT_FUND_ID
    total_reserve_value: str
    tokenized_value: str
    currency: str = "USD"
    valuation_date: str
    proof_document_hash: str
    approved_by: str | None = "admin"


class MintRequestIn(BaseModel):
    fund_id: str = DEFAULT_FUND_ID
    wallet: str
    amount: str
    reason: str | None = None
    network: str = "ERC20"


class MintConfirmationIn(BaseModel):
    mint_id: str
    tx_hash: str
    contract_address: str
    wallet: str
    amount: str
    network: str = "ERC20"
    block_number: str | None = None


class RedeemRequestIn(BaseModel):
    fund_id: str = DEFAULT_FUND_ID
    wallet: str
    amount: str
    reason: str | None = None
    network: str = "ERC20"


class BurnConfirmationIn(BaseModel):
    redeem_id: str
    tx_hash: str
    contract_address: str
    wallet: str
    amount: str
    network: str = "ERC20"
    block_number: str | None = None


class WalletVerifyIn(BaseModel):
    wallet: str
    message: str
    signature: str


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _dec(value: str | int | float | Decimal, code: str = "invalid_amount") -> Decimal:
    try:
        d = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise HTTPException(400, {"code": code, "message": "Invalid decimal value."}) from exc
    if d < 0:
        raise HTTPException(400, {"code": "invalid_amount", "message": "Amount cannot be negative."})
    return d


def _money(value: Decimal | None) -> str:
    return f"{(value or Decimal('0')).quantize(Decimal('0.01'))}"


def _parse_dt(value: str) -> datetime:
    if not value:
        raise HTTPException(400, {"code": "valuation_date_required", "message": "valuation_date is required."})
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(400, {"code": "valuation_date_required", "message": "valuation_date must be ISO-8601."}) from exc


def _calculate(total: Decimal, tokenized: Decimal, issued: Decimal) -> tuple[Decimal, str]:
    available = tokenized - issued
    backing = "N/A" if issued == 0 else str((total / issued).quantize(Decimal("0.0001")))
    return available, backing


def _sign(body: dict[str, Any]) -> str:
    raw = json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)
    secret = (settings.admin_api_key or "m1-reserve-local-secret").encode()
    return "0x" + hmac.new(secret, raw.encode(), hashlib.sha256).hexdigest()


def _hash(body: dict[str, Any]) -> str:
    raw = json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


async def _record_signature(
    db: AsyncSession,
    scope: str,
    body: dict[str, Any],
    *,
    client_id: str | None = None,
) -> None:
    signature = str(body.get("api_signature") or body.get("signature") or _sign(body))
    db.add(ApiSignature(
        scope=scope,
        client_id=client_id,
        signature=signature,
        response_hash=_hash(body),
        metadata_json={"keys": sorted(body.keys())},
    ))
    await db.commit()


async def _record_webhook_event(
    db: AsyncSession,
    event: str,
    fund_id: str | None,
    body: dict[str, Any],
    *,
    status: str = "recorded",
) -> None:
    db.add(WebhookEvent(
        event=event,
        fund_id=fund_id,
        signature=_sign(body),
        status=status,
        request_body=body,
    ))
    await db.commit()


def _event_id() -> str:
    return "AUD-" + uuid.uuid4().hex[:12].upper()


def _public(fund: M1FundReserve) -> dict[str, Any]:
    return {
        "asset": fund.asset_name,
        "symbol": fund.symbol,
        "currency": fund.currency,
        "tokenized_value": _money(fund.tokenized_value),
        "issued_tokens": _money(fund.issued_tokens),
        "available_to_mint": _money(fund.available_to_mint),
        "backing_ratio": fund.backing_ratio,
        "last_updated": fund.last_updated.isoformat() if fund.last_updated else None,
        "status": fund.status,
        "proof_document_hash": fund.proof_document_hash,
    }


def _private(fund: M1FundReserve) -> dict[str, Any]:
    body = {
        "fund_id": fund.fund_id,
        "asset": fund.asset_name,
        "symbol": fund.symbol,
        "currency": fund.currency,
        "total_reserve_value": _money(fund.total_reserve_value),
        "tokenized_value": _money(fund.tokenized_value),
        "issued_tokens": _money(fund.issued_tokens),
        "available_to_mint": _money(fund.available_to_mint),
        "backing_ratio": fund.backing_ratio,
        "valuation_date": fund.valuation_date.isoformat() if fund.valuation_date else None,
        "last_updated": fund.last_updated.isoformat() if fund.last_updated else None,
        "status": fund.status,
        "proof_document_hash": fund.proof_document_hash,
    }
    body["api_signature"] = _sign(body)
    return body


async def _fund(db: AsyncSession, fund_id: str = DEFAULT_FUND_ID) -> M1FundReserve:
    result = await db.execute(select(M1FundReserve).where(M1FundReserve.fund_id == fund_id))
    fund = result.scalar_one_or_none()
    if fund:
        return fund
    fund = M1FundReserve(fund_id=fund_id)
    db.add(fund)
    await db.commit()
    await db.refresh(fund)
    return fund


async def _audit(
    db: AsyncSession,
    request: Request | None,
    event_type: str,
    fund_id: str | None = None,
    *,
    old_value: str | None = None,
    new_value: str | None = None,
    actor: str | None = None,
    tx_hash: str | None = None,
    proof_document_hash: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    row = M1AuditLog(
        event_id=_event_id(),
        fund_id=fund_id,
        event_type=event_type,
        old_value=old_value,
        new_value=new_value,
        actor=actor,
        ip_address=get_client_ip(request) if request else None,
        user_agent=request.headers.get("user-agent") if request else None,
        tx_hash=tx_hash,
        proof_document_hash=proof_document_hash,
        metadata_json=metadata or {},
    )
    db.add(row)
    await db.commit()
    await log_event(
        db,
        "m1." + event_type,
        {"fund_id": fund_id, **(metadata or {})},
        endpoint=str(request.url.path) if request else None,
        method=request.method if request else None,
        ip=get_client_ip(request) if request else None,
        user_agent=request.headers.get("user-agent") if request else None,
    )


def _require_idempotency(value: str | None) -> str:
    if not value:
        raise HTTPException(400, {"code": "idempotency_key_required", "message": "X-Idempotency-Key is required."})
    return value


def _validate_wallet(wallet: str) -> str:
    if not WALLET_RE.match(wallet or ""):
        raise HTTPException(400, {"code": "invalid_wallet", "message": "Wallet must be a valid EVM address."})
    return wallet


def _validate_tx(tx_hash: str) -> str:
    if not TX_RE.match(tx_hash or ""):
        raise HTTPException(400, {"code": "invalid_tx_hash", "message": "tx_hash must be a valid EVM transaction hash."})
    return tx_hash


@router.get("/m1-funds/reserve")
async def get_private_reserve(db: DbSession, _: AdminKey):
    body = _private(await _fund(db))
    await _record_signature(db, "m1.reserve.private", body)
    return body


@router.get("/public/m1-funds/reserve")
async def get_public_reserve(db: DbSession):
    return _public(await _fund(db))


@router.get("/oracle/m1-funds/reserve")
async def get_oracle_reserve(request: Request, db: DbSession, x_client_id: str | None = Header(default=None)):
    fund = await _fund(db)
    body = {
        "fund_id": fund.fund_id,
        "available_to_mint": _money(fund.available_to_mint),
        "issued_tokens": _money(fund.issued_tokens),
        "tokenized_value": _money(fund.tokenized_value),
        "backing_ratio": fund.backing_ratio,
        "status": fund.status,
        "last_updated": fund.last_updated.isoformat() if fund.last_updated else None,
        "proof_document_hash": fund.proof_document_hash,
    }
    body["signature"] = _sign(body)
    await _record_signature(db, "m1.reserve.oracle", body, client_id=x_client_id)
    db.add(M1OracleRead(
        fund_id=fund.fund_id,
        client_id=x_client_id,
        ip_address=get_client_ip(request),
        user_agent=request.headers.get("user-agent"),
        response_hash=_hash(body),
        status="ok",
    ))
    await db.commit()
    await _audit(db, request, "oracle_read", fund.fund_id, actor=x_client_id, metadata={"response_hash": _hash(body)})
    return body


@router.post("/m1-funds/reserve-update")
async def reserve_update(payload: ReserveUpdateIn, request: Request, db: DbSession, _: AdminKey):
    fund = await _fund(db, payload.fund_id)
    total = _dec(payload.total_reserve_value)
    tokenized = _dec(payload.tokenized_value)
    issued = Decimal(fund.issued_tokens or 0)
    if payload.currency.upper() != "USD":
        raise HTTPException(400, {"code": "invalid_currency", "message": "Only USD reserve currency is enabled."})
    if not payload.proof_document_hash:
        raise HTTPException(400, {"code": "proof_hash_required", "message": "proof_document_hash is required."})
    if tokenized > total:
        raise HTTPException(400, {"code": "tokenized_value_exceeded", "message": "tokenized_value cannot exceed total_reserve_value."})
    if tokenized < issued:
        raise HTTPException(400, {"code": "issued_tokens_exceeded", "message": "tokenized_value cannot be lower than issued_tokens."})
    available, backing = _calculate(total, tokenized, issued)
    old = _private(fund)
    fund.total_reserve_value = total
    fund.tokenized_value = tokenized
    fund.available_to_mint = available
    fund.backing_ratio = backing
    fund.currency = payload.currency.upper()
    fund.proof_document_hash = payload.proof_document_hash
    fund.valuation_date = _parse_dt(payload.valuation_date)
    fund.last_updated = _now()
    db.add(M1ReserveSnapshot(
        fund_id=fund.fund_id,
        total_reserve_value=total,
        tokenized_value=tokenized,
        issued_tokens=issued,
        available_to_mint=available,
        backing_ratio=backing,
        proof_document_hash=payload.proof_document_hash,
        valuation_date=fund.valuation_date,
        approved_by=payload.approved_by,
    ))
    await db.commit()
    await db.refresh(fund)
    body = _private(fund)
    await _audit(db, request, "reserve_updated", fund.fund_id, old_value=json.dumps(old), new_value=json.dumps(body), actor=payload.approved_by, proof_document_hash=payload.proof_document_hash)
    await _record_signature(db, "m1.reserve.updated", body)
    await _record_webhook_event(db, "m1.reserve.updated", fund.fund_id, body)
    return body


@router.post("/m1-funds/mint-request")
async def mint_request(payload: MintRequestIn, request: Request, db: DbSession, _: AdminKey, x_idempotency_key: str | None = Header(default=None)):
    idem = _require_idempotency(x_idempotency_key)
    existing = (await db.execute(select(M1MintRequest).where(M1MintRequest.idempotency_key == idem))).scalar_one_or_none()
    if existing:
        return {"approved": True, "mint_id": existing.mint_id, "wallet": existing.wallet, "amount": _money(existing.amount), "expires_at": existing.expires_at.isoformat(), "nonce": existing.nonce, "signature": existing.signature, "idempotent": True}
    fund = await _fund(db, payload.fund_id)
    if fund.status != "active":
        raise HTTPException(400, {"code": "fund_inactive", "message": "Fund is not active."})
    amount = _dec(payload.amount)
    if amount <= 0:
        raise HTTPException(400, {"code": "invalid_amount", "message": "Amount must be greater than zero."})
    if amount > Decimal(fund.available_to_mint or 0):
        raise HTTPException(400, {"code": "insufficient_reserve", "message": "Amount exceeds available_to_mint."})
    wallet = _validate_wallet(payload.wallet)
    mint_id = "MINT-" + uuid.uuid4().hex[:10].upper()
    nonce = mint_id
    expires = _now() + timedelta(hours=1)
    body = {"mint_id": mint_id, "fund_id": fund.fund_id, "wallet": wallet, "amount": _money(amount), "nonce": nonce, "expires_at": expires.isoformat()}
    sig = _sign(body)
    row = M1MintRequest(mint_id=mint_id, fund_id=fund.fund_id, wallet=wallet, amount=amount, network=payload.network, nonce=nonce, signature=sig, idempotency_key=idem, reason=payload.reason, expires_at=expires)
    db.add(row)
    await db.commit()
    await _audit(db, request, "mint_requested", fund.fund_id, actor="admin", metadata=body)
    response = {"approved": True, **body, "signature": sig}
    await _record_signature(db, "m1.mint.requested", response)
    await _record_webhook_event(db, "m1.mint.requested", fund.fund_id, response)
    return response


@router.post("/m1-funds/mint-confirmation")
async def mint_confirmation(payload: MintConfirmationIn, request: Request, db: DbSession, _: AdminKey):
    req = (await db.execute(select(M1MintRequest).where(M1MintRequest.mint_id == payload.mint_id))).scalar_one_or_none()
    if not req:
        raise HTTPException(404, {"code": "invalid_mint_id", "message": "Mint request not found."})
    _validate_tx(payload.tx_hash)
    wallet = _validate_wallet(payload.wallet)
    amount = _dec(payload.amount)
    if wallet.lower() != req.wallet.lower() or amount != Decimal(req.amount):
        raise HTTPException(400, {"code": "mint_confirmation_mismatch", "message": "Confirmation does not match the mint request."})
    fund = await _fund(db, req.fund_id)
    fund.issued_tokens = Decimal(fund.issued_tokens or 0) + amount
    fund.available_to_mint, fund.backing_ratio = _calculate(Decimal(fund.total_reserve_value or 0), Decimal(fund.tokenized_value or 0), Decimal(fund.issued_tokens or 0))
    fund.last_updated = _now()
    req.status = "confirmed"
    req.tx_hash = payload.tx_hash
    req.contract_address = payload.contract_address
    req.block_number = payload.block_number
    req.confirmed_at = _now()
    db.add(M1BlockchainConfirmation(fund_id=fund.fund_id, request_type="mint", request_id=req.mint_id, tx_hash=payload.tx_hash, contract_address=payload.contract_address, wallet=wallet, amount=amount, network=payload.network, block_number=payload.block_number))
    await db.commit()
    await _audit(db, request, "mint_confirmed", fund.fund_id, actor="admin", tx_hash=payload.tx_hash, metadata={"mint_id": req.mint_id, "verification_level": "recorded_not_chain_verified"})
    response = {"status": "confirmed", "mint_id": req.mint_id, "issued_tokens": _money(fund.issued_tokens), "available_to_mint": _money(fund.available_to_mint), "verification_level": "recorded_not_chain_verified"}
    await _record_signature(db, "m1.mint.confirmed", response)
    await _record_webhook_event(db, "m1.mint.confirmed", fund.fund_id, {"event": "m1.mint.confirmed", "fund_id": fund.fund_id, "mint_id": req.mint_id, "amount": _money(amount), "tx_hash": payload.tx_hash, "status": "confirmed", "timestamp": _now().isoformat()})
    return response


@router.post("/m1-funds/redeem-request")
async def redeem_request(payload: RedeemRequestIn, request: Request, db: DbSession, _: AdminKey, x_idempotency_key: str | None = Header(default=None)):
    idem = _require_idempotency(x_idempotency_key)
    existing = (await db.execute(select(M1RedeemRequest).where(M1RedeemRequest.idempotency_key == idem))).scalar_one_or_none()
    if existing:
        return {"approved": True, "redeem_id": existing.redeem_id, "wallet": existing.wallet, "amount": _money(existing.amount), "burn_required": True, "expires_at": existing.expires_at.isoformat(), "nonce": existing.nonce, "signature": existing.signature, "idempotent": True}
    fund = await _fund(db, payload.fund_id)
    if fund.status != "active":
        raise HTTPException(400, {"code": "fund_inactive", "message": "Fund is not active."})
    amount = _dec(payload.amount)
    if amount <= 0:
        raise HTTPException(400, {"code": "invalid_amount", "message": "Amount must be greater than zero."})
    wallet = _validate_wallet(payload.wallet)
    redeem_id = "RED-" + uuid.uuid4().hex[:10].upper()
    nonce = redeem_id
    expires = _now() + timedelta(hours=1)
    body = {"redeem_id": redeem_id, "fund_id": fund.fund_id, "wallet": wallet, "amount": _money(amount), "burn_required": True, "nonce": nonce, "expires_at": expires.isoformat()}
    sig = _sign(body)
    db.add(M1RedeemRequest(redeem_id=redeem_id, fund_id=fund.fund_id, wallet=wallet, amount=amount, network=payload.network, nonce=nonce, signature=sig, idempotency_key=idem, reason=payload.reason, expires_at=expires))
    await db.commit()
    await _audit(db, request, "redeem_requested", fund.fund_id, actor="admin", metadata=body)
    response = {"approved": True, **body, "signature": sig}
    await _record_signature(db, "m1.redeem.requested", response)
    await _record_webhook_event(db, "m1.redeem.requested", fund.fund_id, response)
    return response


@router.post("/m1-funds/burn-confirmation")
async def burn_confirmation(payload: BurnConfirmationIn, request: Request, db: DbSession, _: AdminKey):
    req = (await db.execute(select(M1RedeemRequest).where(M1RedeemRequest.redeem_id == payload.redeem_id))).scalar_one_or_none()
    if not req:
        raise HTTPException(404, {"code": "invalid_redeem_id", "message": "Redeem request not found."})
    _validate_tx(payload.tx_hash)
    wallet = _validate_wallet(payload.wallet)
    amount = _dec(payload.amount)
    if wallet.lower() != req.wallet.lower() or amount != Decimal(req.amount):
        raise HTTPException(400, {"code": "burn_confirmation_mismatch", "message": "Confirmation does not match the redeem request."})
    fund = await _fund(db, req.fund_id)
    fund.issued_tokens = max(Decimal("0"), Decimal(fund.issued_tokens or 0) - amount)
    fund.available_to_mint, fund.backing_ratio = _calculate(Decimal(fund.total_reserve_value or 0), Decimal(fund.tokenized_value or 0), Decimal(fund.issued_tokens or 0))
    fund.last_updated = _now()
    req.status = "completed"
    req.tx_hash = payload.tx_hash
    req.contract_address = payload.contract_address
    req.block_number = payload.block_number
    req.confirmed_at = _now()
    db.add(M1BlockchainConfirmation(fund_id=fund.fund_id, request_type="burn", request_id=req.redeem_id, tx_hash=payload.tx_hash, contract_address=payload.contract_address, wallet=wallet, amount=amount, network=payload.network, block_number=payload.block_number))
    await db.commit()
    await _audit(db, request, "burn_confirmed", fund.fund_id, actor="admin", tx_hash=payload.tx_hash, metadata={"redeem_id": req.redeem_id, "verification_level": "recorded_not_chain_verified"})
    response = {"status": "completed", "redeem_id": req.redeem_id, "issued_tokens": _money(fund.issued_tokens), "available_to_mint": _money(fund.available_to_mint), "verification_level": "recorded_not_chain_verified"}
    await _record_signature(db, "m1.burn.confirmed", response)
    await _record_webhook_event(db, "m1.burn.confirmed", fund.fund_id, {"event": "m1.burn.confirmed", "fund_id": fund.fund_id, "redeem_id": req.redeem_id, "amount": _money(amount), "tx_hash": payload.tx_hash, "status": "completed", "timestamp": _now().isoformat()})
    return response


@router.get("/m1-funds/audit")
async def audit_logs(db: DbSession, _: AdminKey, limit: int = 100):
    rows = (await db.execute(select(M1AuditLog).order_by(desc(M1AuditLog.timestamp)).limit(min(limit, 500)))).scalars().all()
    return {"events": [
        {
            "event_id": r.event_id,
            "fund_id": r.fund_id,
            "type": r.event_type,
            "old_value": r.old_value,
            "new_value": r.new_value,
            "approved_by": r.actor,
            "proof_document_hash": r.proof_document_hash,
            "tx_hash": r.tx_hash,
            "timestamp": r.timestamp.isoformat() if r.timestamp else None,
            "metadata": r.metadata_json or {},
        }
        for r in rows
    ]}


@router.get("/m1-funds/mint-requests")
async def mint_requests(db: DbSession, _: AdminKey, limit: int = 100):
    rows = (await db.execute(select(M1MintRequest).order_by(desc(M1MintRequest.created_at)).limit(min(limit, 500)))).scalars().all()
    return {"items": [
        {
            "mint_id": r.mint_id,
            "fund_id": r.fund_id,
            "wallet": r.wallet,
            "amount": _money(r.amount),
            "network": r.network,
            "status": r.status,
            "nonce": r.nonce,
            "expires_at": r.expires_at.isoformat() if r.expires_at else None,
            "tx_hash": r.tx_hash,
            "contract_address": r.contract_address,
            "block_number": r.block_number,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "confirmed_at": r.confirmed_at.isoformat() if r.confirmed_at else None,
        }
        for r in rows
    ]}


@router.get("/m1-funds/redeem-requests")
async def redeem_requests(db: DbSession, _: AdminKey, limit: int = 100):
    rows = (await db.execute(select(M1RedeemRequest).order_by(desc(M1RedeemRequest.created_at)).limit(min(limit, 500)))).scalars().all()
    return {"items": [
        {
            "redeem_id": r.redeem_id,
            "fund_id": r.fund_id,
            "wallet": r.wallet,
            "amount": _money(r.amount),
            "network": r.network,
            "status": r.status,
            "nonce": r.nonce,
            "expires_at": r.expires_at.isoformat() if r.expires_at else None,
            "tx_hash": r.tx_hash,
            "contract_address": r.contract_address,
            "block_number": r.block_number,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "confirmed_at": r.confirmed_at.isoformat() if r.confirmed_at else None,
        }
        for r in rows
    ]}


@router.get("/m1-funds/oracle-reads")
async def oracle_reads(db: DbSession, _: AdminKey, limit: int = 100):
    rows = (await db.execute(select(M1OracleRead).order_by(desc(M1OracleRead.timestamp)).limit(min(limit, 500)))).scalars().all()
    return {"items": [
        {
            "fund_id": r.fund_id,
            "client_id": r.client_id,
            "ip_address": r.ip_address,
            "user_agent": r.user_agent,
            "response_hash": r.response_hash,
            "status": r.status,
            "timestamp": r.timestamp.isoformat() if r.timestamp else None,
        }
        for r in rows
    ]}


@router.get("/m1-funds/webhook-events")
async def webhook_events(db: DbSession, _: AdminKey, limit: int = 100):
    rows = (await db.execute(select(WebhookEvent).where(WebhookEvent.event.like("m1.%")).order_by(desc(WebhookEvent.created_at)).limit(min(limit, 500)))).scalars().all()
    return {"items": [
        {
            "event": r.event,
            "fund_id": r.fund_id,
            "status": r.status,
            "status_code": r.status_code,
            "target_url": r.target_url,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "sent_at": r.sent_at.isoformat() if r.sent_at else None,
            "error_message": r.error_message,
        }
        for r in rows
    ]}


@router.post("/wallets/verify-signature")
async def verify_signature(payload: WalletVerifyIn, request: Request, db: DbSession, _: AdminKey):
    wallet = _validate_wallet(payload.wallet)
    nonce = payload.message.split("nonce:", 1)[-1].strip() if "nonce:" in payload.message else hashlib.sha256(payload.message.encode()).hexdigest()[:24]
    reused = (await db.execute(select(WalletVerification).where(WalletVerification.nonce == nonce))).scalar_one_or_none()
    if reused:
        raise HTTPException(400, {"code": "nonce_reused", "message": "This verification nonce has already been used."})
    try:
        recovered = Account.recover_message(encode_defunct(text=payload.message), signature=payload.signature)
        verified = recovered.lower() == wallet.lower()
    except Exception as exc:
        raise HTTPException(400, {"code": "invalid_signature", "message": "Wallet signature could not be verified."}) from exc
    row = WalletVerification(
        wallet=wallet,
        message=payload.message,
        signature=payload.signature,
        nonce=nonce,
        verified=verified,
        verified_at=_now() if verified else None,
        ip_address=get_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    db.add(row)
    await db.commit()
    await _audit(db, request, "wallet_signature_verified" if verified else "wallet_signature_failed", None, actor="admin", metadata={"wallet": wallet, "nonce": nonce})
    return {"verified": verified, "wallet": wallet, "verified_at": row.verified_at.isoformat() if row.verified_at else None}
