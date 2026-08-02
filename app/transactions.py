from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy import String, cast, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit_service import log_event
from app.config import settings
from app.database import get_db
from app.deps import ClientApiKey
from app.models import Network, OrderSide, OrderStatus, PaymentOrder, Provider
from app.provider_service import get_provider
from app.request_utils import get_client_ip
from app.schemas import TransactionCreate, TransactionResponse

router = APIRouter(prefix="/transactions", tags=["transactions"])

ETHEREUM_LEDGER_WALLET = "0xBD682cfD8382a90adfDd6745780D3D7959c4d939"


def public_base_url() -> str:
    value = (
        getattr(settings, "public_base_url", None)
        or getattr(settings, "public_app_url", None)
        or "https://api.alshumookh-pay.com"
    )
    return str(value).rstrip("/")


def _client_ip(request: Request) -> str | None:
    return get_client_ip(request)


def _ledger_address(network: Network) -> str:
    try:
        return settings.get_treasury_address(network.value)
    except ValueError:
        if network == Network.ETHEREUM:
            return ETHEREUM_LEDGER_WALLET

        raise HTTPException(
            status_code=400,
            detail=f"Treasury wallet address is not configured for {network.value}",
        )


def _order_public_payment_url(order: PaymentOrder) -> str:
    return f"{public_base_url()}/pay/direct/{order.id}"


def _transaction_response(order: PaymentOrder) -> TransactionResponse:
    checkout_url = getattr(order, "checkout_url", None) or getattr(
        order,
        "coinbase_session_url",
        None,
    )

    quote = order.quote_json or {}

    if isinstance(quote, dict):
        quote = {
            **quote,
            "payment_url": _order_public_payment_url(order),
            "checkout_url": checkout_url,
        }

    return TransactionResponse(
        transaction_id=str(order.id),
        external_id=order.external_id,
        status=order.status,
        provider=order.provider,
        network=order.network,
        fiat_currency=order.fiat_currency,
        crypto_currency=order.crypto_currency,
        fiat_amount=order.fiat_amount,
        crypto_amount=order.crypto_amount,
        destination_address=getattr(order, "treasury_wallet_address", None)
        or order.user_wallet_address,
        checkout_url=checkout_url,
        provider_order_id=getattr(order, "provider_order_id", None),
        quote=quote,
        created_at=order.created_at,
    )


async def _find_existing_by_idempotency(
    db: AsyncSession,
    client_id,
    idempotency_key: str,
) -> PaymentOrder | None:
    result = await db.execute(
        select(PaymentOrder)
        .where(
            PaymentOrder.provider == Provider.MOONPAY,
            PaymentOrder.client_id == client_id,
            PaymentOrder.idempotency_key == idempotency_key,
        )
        .order_by(PaymentOrder.created_at.desc())
        .limit(1)
    )

    return result.scalar_one_or_none()


async def _find_existing_by_external_id(
    db: AsyncSession,
    client_id,
    external_id: str | None,
) -> PaymentOrder | None:
    if not external_id:
        return None

    result = await db.execute(
        select(PaymentOrder)
        .where(
            PaymentOrder.provider == Provider.MOONPAY,
            PaymentOrder.client_id == client_id,
            PaymentOrder.external_id == external_id,
        )
        .order_by(PaymentOrder.created_at.desc())
        .limit(1)
    )

    return result.scalar_one_or_none()


@router.post("", response_model=TransactionResponse)
async def create_transaction(
    payload: TransactionCreate,
    client: ClientApiKey,
    request: Request,
    db: AsyncSession = Depends(get_db),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    if not idempotency_key:
        raise HTTPException(
            status_code=400,
            detail="Idempotency-Key header is required",
        )

    external_id = payload.external_id or idempotency_key or f"txn-{uuid.uuid4()}"

    existing = await _find_existing_by_idempotency(
        db,
        client.id,
        idempotency_key,
    )

    if existing:
        request.state.transaction_id = str(existing.id)
        request.state.order_id = existing.id

        await log_event(
            db,
            "TRANSACTION_IDEMPOTENT_REPLAY",
            {
                "external_id": external_id,
                "idempotency_key": idempotency_key,
            },
            existing.id,
            client_id=client.id,
        )

        return _transaction_response(existing)

    if payload.fiat_amount is not None and payload.crypto_amount is not None:
        raise HTTPException(
            status_code=400,
            detail="Use fiat_amount or crypto_amount, not both",
        )

    destination_address = _ledger_address(payload.network)
    provider = await get_provider(Provider.MOONPAY)

    provider_payload = {
        "walletAddress": destination_address,
        "cryptoCurrency": payload.crypto_currency,
        "network": payload.network.value,
        "fiatCurrency": payload.fiat_currency,
        "fiatAmount": payload.fiat_amount,
        "cryptoAmount": payload.crypto_amount,
        "paymentMethod": payload.payment_method,
        "country": payload.country,
        "subdivision": payload.subdivision,
        "redirectURL": payload.redirect_url,
        "partnerUserRef": external_id,
        "clientIp": _client_ip(request),
    }

    provider_payload = {
        key: value for key, value in provider_payload.items() if value is not None
    }

    checkout_url, quote = await provider.create_widget_url(provider_payload)

    order = PaymentOrder(
        client_id=client.id,
        idempotency_key=idempotency_key,
        external_id=external_id,
        provider=Provider.MOONPAY,
        side=OrderSide.BUY,
        status=OrderStatus.CREATED,
        network=payload.network,
        fiat_currency=payload.fiat_currency.upper(),
        fiat_amount=payload.fiat_amount,
        crypto_currency=payload.crypto_currency.upper(),
        crypto_amount=payload.crypto_amount,
        user_wallet_address=destination_address,
        treasury_wallet_address=destination_address,
        payer_email=str(payload.customer_email) if payload.customer_email else None,
        payment_reference=external_id,
        checkout_url=checkout_url,
        quote_json={"quote": quote, "metadata": payload.metadata}
        if payload.metadata
        else quote,
    )

    db.add(order)
    await db.commit()
    await db.refresh(order)

    request.state.transaction_id = str(order.id)
    request.state.order_id = order.id

    await log_event(
        db,
        "API_TRANSACTION_CREATED",
        {
            "external_id": external_id,
            "idempotency_key": idempotency_key,
            "destination_address": destination_address,
            "checkout_url": checkout_url,
            "payment_url": _order_public_payment_url(order),
            "quote": quote,
            "metadata": payload.metadata,
        },
        order.id,
        client_id=client.id,
    )

    return _transaction_response(order)


@router.get("/{transaction_id}", response_model=TransactionResponse)
async def get_transaction(
    transaction_id: str,
    client: ClientApiKey,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(PaymentOrder).where(
            cast(PaymentOrder.id, String) == str(transaction_id),
            PaymentOrder.client_id == client.id,
        )
    )
    order = result.scalar_one_or_none()

    if not order:
        raise HTTPException(status_code=404, detail="Transaction not found")

    request.state.transaction_id = str(order.id)
    request.state.order_id = order.id

    return _transaction_response(order)


@router.get("/external/{external_id}", response_model=TransactionResponse)
async def get_transaction_by_external_id(
    external_id: str,
    client: ClientApiKey,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    order = await _find_existing_by_external_id(db, client.id, external_id)

    if not order:
        raise HTTPException(status_code=404, detail="Transaction not found")

    request.state.transaction_id = str(order.id)
    request.state.order_id = order.id

    return _transaction_response(order)
