from __future__ import annotations

import base64
import hashlib
import hmac as hmac_mod
import json
import secrets
import time
from typing import Any
from urllib.parse import quote, urlencode

import httpx
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519
from fastapi import HTTPException

from app.config import settings
from app.models import Provider


class CoinbaseProvider:
    def __init__(self) -> None:
        self.host = settings.coinbase_api_host
        self.base_url = settings.coinbase_onramp_base_url.rstrip("/")

    def _api_key_id(self) -> str:
        key_id = settings.resolved_coinbase_api_key_id

        if not key_id:
            raise HTTPException(
                status_code=500,
                detail="Coinbase API key id is not configured",
            )

        return key_id

    def _api_key_secret(self) -> str:
        key_secret = settings.resolved_coinbase_api_key_secret

        if not key_secret:
            raise HTTPException(
                status_code=500,
                detail="Coinbase API key secret is not configured",
            )

        return key_secret

    def _load_private_key(self):
        key_secret = self._api_key_secret().strip()

        if "\\n" in key_secret:
            key_secret = key_secret.replace("\\n", "\n")

        if "BEGIN" in key_secret:
            return serialization.load_pem_private_key(
                key_secret.encode("utf-8"),
                password=None,
            )

        try:
            decoded_text = base64.b64decode(key_secret).decode("utf-8")

            if "BEGIN" in decoded_text:
                return serialization.load_pem_private_key(
                    decoded_text.encode("utf-8"),
                    password=None,
                )
        except Exception:
            pass

        try:
            decoded = base64.b64decode(key_secret)
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail="Coinbase API key secret must be PEM or base64",
            ) from exc

        if len(decoded) == 64:
            return ed25519.Ed25519PrivateKey.from_private_bytes(decoded[:32])

        if len(decoded) == 32:
            return ed25519.Ed25519PrivateKey.from_private_bytes(decoded)

        raise HTTPException(
            status_code=500,
            detail="Unsupported Coinbase API key secret format",
        )

    def _build_jwt(self, method: str, path: str) -> str:
        key_id = self._api_key_id()
        private_key = self._load_private_key()
        now = int(time.time())

        headers = {
            "kid": key_id,
            "nonce": secrets.token_hex(16),
            "typ": "JWT",
        }

        payload = {
            "sub": key_id,
            "iss": "cdp",
            "aud": ["cdp_service"],
            "nbf": now,
            "exp": now + 120,
            "uri": f"{method.upper()} {self.host}{path}",
        }

        if isinstance(private_key, ed25519.Ed25519PrivateKey):
            return jwt.encode(
                payload,
                private_key,
                algorithm="EdDSA",
                headers=headers,
            )

        if isinstance(private_key, ec.EllipticCurvePrivateKey):
            return jwt.encode(
                payload,
                private_key,
                algorithm="ES256",
                headers=headers,
            )

        raise HTTPException(
            status_code=500,
            detail="Unsupported Coinbase private key type",
        )

    async def create_widget_url(self, payload: dict[str, Any]) -> tuple[str, dict | None]:
        return await self.create_onramp_session(payload)

    async def create_onramp_session(self, payload: dict[str, Any]) -> tuple[str, dict | None]:
        path = "/platform/v2/onramp/sessions"

        destination_address = (
            payload.get("walletAddress")
            or payload.get("destinationAddress")
            or payload.get("treasury_wallet_address")
        )

        if not destination_address:
            raise HTTPException(
                status_code=400,
                detail="Coinbase destination wallet address is required",
            )

        payment_amount = payload.get("fiatAmount") or payload.get("paymentAmount")
        purchase_amount = payload.get("cryptoAmount") or payload.get("purchaseAmount")

        if payment_amount is not None and purchase_amount is not None:
            raise HTTPException(
                status_code=400,
                detail="Use fiatAmount/paymentAmount or cryptoAmount/purchaseAmount, not both",
            )

        destination_network = (
            payload.get("network")
            or payload.get("destinationNetwork")
            or settings.coinbase_default_network
        )

        destination_network = str(destination_network).lower()

        if destination_network in {"eth", "erc20"}:
            destination_network = "ethereum"

        request_body = {
            "destinationAddress": destination_address,
            "purchaseCurrency": (
                payload.get("cryptoCurrency")
                or payload.get("purchaseCurrency")
                or settings.coinbase_default_purchase_currency
            ),
            "destinationNetwork": destination_network,
            "paymentCurrency": (
                payload.get("fiatCurrency")
                or payload.get("paymentCurrency")
                or settings.coinbase_default_payment_currency
            ),
            "paymentAmount": str(payment_amount) if payment_amount is not None else None,
            "purchaseAmount": str(purchase_amount) if purchase_amount is not None else None,
            "paymentMethod": payload.get("paymentMethod") or payload.get("payment_method"),
            "country": payload.get("country"),
            "subdivision": payload.get("subdivision"),
            "redirectUrl": (
                payload.get("redirectURL")
                or payload.get("redirectUrl")
                or payload.get("redirect_url")
                or settings.onramp_redirect_url
            ),
            "clientIp": payload.get("clientIp") or payload.get("client_ip"),
            "partnerUserRef": (
                payload.get("partnerUserRef")
                or payload.get("partner_user_ref")
                or payload.get("external_id")
            ),
        }

        request_body = {
            key: value
            for key, value in request_body.items()
            if value is not None and value != ""
        }

        token = self._build_jwt("POST", path)

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"https://{self.host}{path}",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                json=request_body,
            )

        if response.status_code >= 400:
            raise HTTPException(
                status_code=response.status_code,
                detail={
                    "message": "Coinbase onramp session failed",
                    "coinbase_status": response.status_code,
                    "coinbase_response": response.text,
                },
            )

        body = response.json()
        session = body.get("session") or {}

        onramp_url = (
            session.get("onrampUrl")
            or session.get("onramp_url")
            or body.get("onrampUrl")
            or body.get("onramp_url")
            or body.get("url")
        )

        if not onramp_url:
            raise HTTPException(
                status_code=502,
                detail={
                    "message": "Coinbase did not return onrampUrl",
                    "coinbase_response": body,
                },
            )

        return onramp_url, body.get("quote") or body


class MoonPayProvider:
    """
    Builds a signed MoonPay Buy Widget URL directly — no API call needed.
    Works with pk_test_* keys (sandbox) immediately and pk_live_* when approved.
    """

    def _widget_base(self) -> str:
        key = settings.moonpay_api_key or ""
        if key.startswith("pk_test_"):
            return "https://buy-sandbox.moonpay.com"
        return "https://buy.moonpay.com"

    async def create_widget_url(self, payload: dict[str, Any]) -> tuple[str, dict | None]:
        if not settings.moonpay_api_key:
            raise HTTPException(
                status_code=500,
                detail="MoonPay API key (MOONPAY_API_KEY) is not configured",
            )

        destination_address = (
            payload.get("walletAddress")
            or payload.get("destinationAddress")
            or payload.get("treasury_wallet_address")
        )

        if not destination_address:
            raise HTTPException(
                status_code=400,
                detail="MoonPay destination wallet address is required",
            )

        api_key = settings.moonpay_api_key
        widget_base = self._widget_base()

        crypto_currency = str(
            payload.get("cryptoCurrency")
            or payload.get("purchaseCurrency")
            or "USDC"
        ).lower()

        network = str(
            payload.get("network")
            or payload.get("destinationNetwork")
            or "ethereum"
        ).lower()

        network_suffix_map = {
            "ethereum": "eth", "eth": "eth", "erc20": "eth",
            "base": "base",
            "tron": "trx", "trx": "trx", "trc20": "trx",
            "polygon": "polygon", "matic": "polygon",
        }
        net_suffix = network_suffix_map.get(network, network[:3])
        currency_code = f"{crypto_currency}_{net_suffix}"

        fiat_currency = str(
            payload.get("fiatCurrency")
            or payload.get("paymentCurrency")
            or "USD"
        ).upper()

        external_id = str(
            payload.get("partnerUserRef")
            or payload.get("partner_user_ref")
            or payload.get("external_id")
            or secrets.token_hex(8)
        )

        redirect_url = (
            payload.get("redirectURL")
            or payload.get("redirectUrl")
            or payload.get("redirect_url")
            or settings.onramp_redirect_url
        )

        params: dict[str, str] = {
            "apiKey": api_key,
            "currencyCode": currency_code,
            "walletAddress": destination_address,
            "baseCurrencyCode": fiat_currency,
            "externalTransactionId": external_id,
        }

        amount = payload.get("fiatAmount") or payload.get("cryptoAmount")
        if amount is not None:
            try:
                params["baseCurrencyAmount"] = str(round(float(str(amount)), 2))
            except (ValueError, TypeError):
                pass

        if redirect_url:
            params["redirectURL"] = str(redirect_url)

        query_string = urlencode(params, quote_via=quote)
        widget_url = f"{widget_base}?{query_string}"

        if settings.moonpay_api_secret:
            raw = f"?{query_string}"
            sig_bytes = hmac_mod.new(
                settings.moonpay_api_secret.encode("utf-8"),
                raw.encode("utf-8"),
                hashlib.sha256,
            ).digest()
            signature = base64.b64encode(sig_bytes).decode("utf-8")
            widget_url = f"{widget_url}&signature={quote(signature)}"

        mode = "sandbox" if api_key.startswith("pk_test_") else "live"

        return widget_url, {
            "external_transaction_id": external_id,
            "currency_code": currency_code,
            "wallet_address": destination_address,
            "mode": mode,
        }


class CircleProvider:
    """
    Circle Programmable Wallets + Payment Intents.
    Creates a USDC payment intent and returns a hosted payment page URL.
    """

    BASE_URL = "https://api.circle.com"

    def _headers(self) -> dict:
        if not settings.circle_api_key:
            raise HTTPException(
                status_code=500,
                detail="Circle API key (CIRCLE_API_KEY) is not configured",
            )
        return {
            "Authorization": f"Bearer {settings.circle_api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def create_widget_url(self, payload: dict[str, Any]) -> tuple[str, dict | None]:
        amount = payload.get("fiatAmount") or payload.get("cryptoAmount") or 100
        try:
            amount_float = round(float(str(amount)), 2)
        except (ValueError, TypeError):
            amount_float = 100.0

        external_id = str(
            payload.get("partnerUserRef")
            or payload.get("partner_user_ref")
            or payload.get("external_id")
            or secrets.token_hex(8)
        )

        network = str(payload.get("network") or "ethereum").lower()
        chain_map = {
            "ethereum": "ETH", "eth": "ETH", "erc20": "ETH",
            "base": "BASE",
            "polygon": "MATIC", "matic": "MATIC",
        }
        chain = chain_map.get(network, "ETH")

        destination_address = (
            payload.get("walletAddress")
            or payload.get("destinationAddress")
            or payload.get("treasury_wallet_address")
        )

        # Try Circle Payment Intents API — falls back to treasury address if not enabled
        intent_id: str | None = None
        blockchain_address = destination_address
        usdc_amount = amount_float
        payment_methods: list = []
        circle_api_used = False

        if settings.circle_api_key:
            try:
                request_body: dict[str, Any] = {
                    "idempotencyKey": f"circle-{external_id}-{secrets.token_hex(8)}",
                    "amount": {
                        "amount": f"{amount_float:.2f}",
                        "currency": "USD",
                    },
                    "settlementCurrency": "USD",
                    "paymentMethods": [
                        {"type": "blockchain", "chain": chain},
                    ],
                }

                async with httpx.AsyncClient(timeout=30) as client:
                    response = await client.post(
                        f"{self.BASE_URL}/v1/paymentIntents",
                        headers=self._headers(),
                        json=request_body,
                    )

                if response.status_code < 400:
                    body = response.json()
                    data = body.get("data", body)
                    intent_id = data.get("id")
                    payment_methods = data.get("paymentMethods", [])
                    circle_api_used = True

                    for method in payment_methods:
                        if method.get("type") == "blockchain":
                            addr = method.get("address")
                            if addr:
                                blockchain_address = addr
                            amt = method.get("amount", {})
                            if isinstance(amt, dict) and amt.get("amount"):
                                try:
                                    usdc_amount = float(amt["amount"])
                                except (ValueError, TypeError):
                                    pass
                            break
            except Exception:
                # Circle API unavailable — continue with treasury address fallback
                pass

        if not blockchain_address:
            raise HTTPException(
                status_code=500,
                detail="No USDC destination address configured. Set TREASURY_WALLET_ADDRESS.",
            )

        # Build our hosted USDC payment info page
        public_base = str(
            getattr(settings, "public_base_url", None) or "https://api.alshumookh-pay.com"
        ).rstrip("/")

        intent_ref = intent_id or f"PAY-{external_id}"
        addr_param = quote(str(blockchain_address), safe="")
        checkout_url = (
            f"{public_base}/pay/circle/{intent_ref}"
            f"?addr={addr_param}"
            f"&amount={usdc_amount:.2f}"
            f"&chain={chain}"
            f"&ref={quote(external_id, safe='')}"
        )

        return checkout_url, {
            "circle_payment_intent_id": intent_id,
            "blockchain_address": blockchain_address,
            "chain": chain,
            "usdc_amount": usdc_amount,
            "circle_api_used": circle_api_used,
            "payment_methods": payment_methods,
        }


class OnramperProvider:
    """
    Onramper — aggregator of 30+ fiat-to-crypto onramps (Simplex, Guardarian, etc.)
    Supports credit card, debit card, bank transfer, Apple Pay, Google Pay.
    No API call needed — builds a hosted widget URL that the client opens.
    Requires ONRAMPER_API_KEY from https://onramper.com
    """

    def _widget_base(self) -> str:
        return str(settings.onramper_widget_base_url or "https://buy.onramper.com").rstrip("/")

    async def create_widget_url(self, payload: dict[str, Any]) -> tuple[str, dict | None]:
        api_key = settings.onramper_api_key
        if not api_key:
            raise HTTPException(
                status_code=500,
                detail="Onramper API key (ONRAMPER_API_KEY) is not configured. Sign up at https://onramper.com",
            )

        # Amount
        try:
            fiat_amount = round(float(str(payload.get("fiatAmount") or payload.get("fiat_amount") or 100)), 2)
        except (ValueError, TypeError):
            fiat_amount = 100.0

        fiat_currency = str(
            payload.get("fiatCurrency") or payload.get("fiat_currency") or settings.onramper_default_fiat or "USD"
        ).upper()

        crypto = str(
            payload.get("cryptoCurrency") or payload.get("crypto") or settings.onramper_default_crypto or "USDC"
        ).upper()

        network = str(payload.get("network") or "ethereum").lower()
        # Onramper network identifiers
        network_map = {
            "ethereum": "ethereum", "eth": "ethereum", "erc20": "ethereum",
            "base": "base", "base-mainnet": "base",
            "polygon": "polygon", "matic": "polygon",
            "tron": "tron", "trx": "tron", "trc20": "tron",
            "bsc": "bsc", "bnb": "bsc",
        }
        onramper_network = network_map.get(network, "ethereum")

        wallet_address = (
            payload.get("walletAddress")
            or payload.get("wallet_address")
            or payload.get("treasury_wallet_address")
            or payload.get("destinationAddress")
        )

        external_ref = str(
            payload.get("partnerUserRef")
            or payload.get("partner_user_ref")
            or payload.get("external_id")
            or secrets.token_hex(8)
        )

        # Build Onramper widget URL
        params: dict[str, str] = {
            "apiKey": api_key,
            "defaultCrypto": crypto,
            "defaultFiat": fiat_currency,
            "defaultAmount": str(fiat_amount),
            "onlyCryptos": crypto,
            "onlyNetworks": onramper_network,
            "partnerContext": external_ref,
            "isAddressEditable": "false",
        }
        if wallet_address:
            params["walletAddress"] = wallet_address
            params["isAddressEditable"] = "false"

        query_string = "&".join(f"{k}={quote(str(v), safe='')}" for k, v in params.items())
        widget_url = f"{self._widget_base()}?{query_string}"

        return widget_url, {
            "onramper_network": onramper_network,
            "fiat_currency": fiat_currency,
            "fiat_amount": fiat_amount,
            "crypto": crypto,
            "wallet_address": wallet_address,
            "external_ref": external_ref,
        }


async def get_provider(provider: Provider | str):
    if isinstance(provider, str):
        provider = Provider(provider.lower())

    if provider == Provider.COINBASE:
        return CoinbaseProvider()

    if provider == Provider.MOONPAY:
        return MoonPayProvider()

    if provider == Provider.CIRCLE:
        return CircleProvider()

    raise NotImplementedError(f"Provider {provider} is not enabled")
