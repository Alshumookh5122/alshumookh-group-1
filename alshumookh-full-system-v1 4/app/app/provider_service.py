"""
Provider Service — unified interface over Stripe (fiat) and Alchemy (crypto).
"""

from decimal import Decimal
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.app.config import settings
from app.app.models import Payment, PaymentType, PaymentProvider, PaymentStatus
from app.app.schemas import CreatePaymentRequest
from app.app.utils import generate_payment_reference
from app.app.alchemy_service import alchemy_service
from app.app.wallet_service import WalletRepository
import structlog
import datetime

logger = structlog.get_logger()


class ProviderService:
    @classmethod
    async def create_payment(
        cls, db: AsyncSession, user_id: str, data: CreatePaymentRequest, ip_address: Optional[str] = None,
    ) -> Payment:
        if data.payment_type == PaymentType.CRYPTO:
            return await cls._create_crypto_payment(db, user_id, data, ip_address)
        elif data.payment_type == PaymentType.FIAT:
            return await cls._create_fiat_payment(db, user_id, data, ip_address)
        else:
            raise ValueError(f"Unsupported payment type: {data.payment_type}")

    @classmethod
    async def _create_crypto_payment(
        cls, db: AsyncSession, user_id: str, data: CreatePaymentRequest, ip_address: Optional[str],
    ) -> Payment:
        token = data.token_symbol.upper()
        network = settings.ALCHEMY_NETWORK
        token_contract = settings.TOKEN_CONTRACTS.get(token)

        prices = await alchemy_service.get_token_prices()
        price_usd = prices.get(token, Decimal("1"))
        amount_usd = data.amount * price_usd

        index = await WalletRepository.get_next_index(db)

        payment = Payment(
            reference=generate_payment_reference("CRYPTO"),
            user_id=user_id,
            amount=data.amount,
            currency=token,
            amount_usd=amount_usd,
            payment_type=PaymentType.CRYPTO,
            provider=PaymentProvider.ALCHEMY,
            status=PaymentStatus.AWAITING_PAYMENT,
            token_symbol=token,
            token_contract=token_contract,
            network=network,
            description=data.description,
            metadata_=data.metadata,
            callback_url=data.callback_url,
            ip_address=ip_address,
            expires_at=datetime.datetime.utcnow() + datetime.timedelta(
                minutes=settings.CRYPTO_PAYMENT_EXPIRY_MINUTES
            ),
        )
        db.add(payment)
        await db.flush()

        wallet = await WalletRepository.create_deposit_wallet(
            db, user_id, payment.id, index, network
        )
        payment.deposit_address = wallet.address

        await db.commit()
        await db.refresh(payment)

        logger.info(
            "payment.crypto.created",
            payment_id=payment.id, token=token,
            amount=str(data.amount), address=wallet.address[:10] + "...",
        )
        return payment

    @classmethod
    async def _create_fiat_payment(
        cls, db: AsyncSession, user_id: str, data: CreatePaymentRequest, ip_address: Optional[str],
    ) -> Payment:
        import stripe
        stripe.api_key = settings.STRIPE_SECRET_KEY

        currency = data.currency.lower()
        amount_cents = int(data.amount * 100)

        intent = stripe.PaymentIntent.create(
            amount=amount_cents,
            currency=currency,
            automatic_payment_methods={"enabled": True},
            description=data.description,
            metadata={"user_id": user_id, **(data.metadata or {})},
        )

        payment = Payment(
            reference=generate_payment_reference("FIAT"),
            user_id=user_id,
            amount=data.amount,
            currency=currency.upper(),
            amount_usd=data.amount if currency == "usd" else None,
            payment_type=PaymentType.FIAT,
            provider=PaymentProvider.STRIPE,
            status=PaymentStatus.AWAITING_PAYMENT,
            provider_payment_id=intent.id,
            provider_client_secret=intent.client_secret,
            description=data.description,
            metadata_=data.metadata,
            callback_url=data.callback_url,
            ip_address=ip_address,
        )
        db.add(payment)
        await db.commit()
        await db.refresh(payment)

        logger.info(
            "payment.fiat.created",
            payment_id=payment.id, stripe_id=intent.id,
            amount=str(data.amount), currency=currency,
        )
        return payment
