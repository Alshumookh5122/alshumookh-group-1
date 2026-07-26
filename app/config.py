from decimal import Decimal
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = Field(
        default="ALSHUMOOKH GLOBAL BANKING FINANCE & CREDIT",
        alias="APP_NAME",
    )
    app_env: str = Field(default="production", alias="APP_ENV")
    app_debug: bool = Field(default=False, alias="APP_DEBUG")
    app_host: str = Field(default="0.0.0.0", alias="APP_HOST")
    app_port: int = Field(default=8000, alias="APP_PORT")
    api_prefix: str = Field(default="/api/v1", alias="API_PREFIX")

    admin_api_key: str = Field(default="change-this-admin-key", alias="ADMIN_API_KEY")
    admin_allowed_ips: str | None = Field(default=None, alias="ADMIN_ALLOWED_IPS")

    public_base_url: str = Field(
        default="https://api.alshumookh-pay.com",
        alias="PUBLIC_BASE_URL",
    )
    public_app_url: str | None = Field(default=None, alias="PUBLIC_APP_URL")
    company_logo_url: str | None = Field(default=None, alias="COMPANY_LOGO_URL")
    cors_allowed_origins_raw: str | None = Field(default=None, alias="CORS_ALLOWED_ORIGINS")
    trusted_proxy_ips_raw: str | None = Field(default=None, alias="TRUSTED_PROXY_IPS")
    health_allowed_ips_raw: str | None = Field(default=None, alias="HEALTH_ALLOWED_IPS")
    healthcheck_token: str | None = Field(default=None, alias="HEALTHCHECK_TOKEN")
    allowed_countries_raw: str | None = Field(default=None, alias="ALLOWED_COUNTRIES")
    blocked_countries_raw: str | None = Field(default=None, alias="BLOCKED_COUNTRIES")
    security_probe_threshold: int = Field(default=5, alias="SECURITY_PROBE_THRESHOLD")
    security_probe_window_seconds: int = Field(default=600, alias="SECURITY_PROBE_WINDOW_SECONDS")
    security_ban_seconds: int = Field(default=900, alias="SECURITY_BAN_SECONDS")
    security_silent_probe_blocks: bool = Field(default=True, alias="SECURITY_SILENT_PROBE_BLOCKS")
    global_rate_limit_window_seconds: int = Field(default=60, alias="GLOBAL_RATE_LIMIT_WINDOW_SECONDS")
    global_rate_limit_max_requests: int = Field(default=240, alias="GLOBAL_RATE_LIMIT_MAX_REQUESTS")
    enable_testnet: bool = Field(default=False, alias="ENABLE_TESTNET")
    hipercapital_webhook_url: str | None = Field(
        default=None,
        alias="HIPERCAPITAL_WEBHOOK_URL",
    )

    database_url: str = Field(
        default="sqlite+aiosqlite:///./alshumookh.db",
        alias="DATABASE_URL",
    )
    sync_database_url: str = Field(
        default="sqlite:///./alshumookh.db",
        alias="SYNC_DATABASE_URL",
    )

    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")
    celery_broker_url: str = Field(default="redis://localhost:6379/0", alias="CELERY_BROKER_URL")
    celery_result_backend: str = Field(default="redis://localhost:6379/0", alias="CELERY_RESULT_BACKEND")

    coinbase_api_host: str = Field(default="api.cdp.coinbase.com", alias="COINBASE_API_HOST")
    coinbase_api_key_id: str | None = Field(default=None, alias="COINBASE_API_KEY_ID")
    coinbase_api_key_secret: str | None = Field(default=None, alias="COINBASE_API_KEY_SECRET")
    coinbase_webhook_secret: str | None = Field(default=None, alias="COINBASE_WEBHOOK_SECRET")

    cdp_api_key_id: str | None = Field(default=None, alias="CDP_API_KEY_ID")
    cdp_api_key_secret: str | None = Field(default=None, alias="CDP_API_KEY_SECRET")
    cdp_project_id: str | None = Field(default=None, alias="CDP_PROJECT_ID")

    coinbase_default_payment_currency: str = Field(default="USD", alias="COINBASE_DEFAULT_PAYMENT_CURRENCY")
    coinbase_default_purchase_currency: str = Field(default="USDC", alias="COINBASE_DEFAULT_PURCHASE_CURRENCY")
    coinbase_default_network: str = Field(default="ethereum", alias="COINBASE_DEFAULT_NETWORK")
    coinbase_onramp_base_url: str = Field(default="https://api.cdp.coinbase.com", alias="COINBASE_ONRAMP_BASE_URL")
    onramp_redirect_url: str = Field(
        default="https://api.alshumookh-pay.com/pay/success",
        alias="ONRAMP_REDIRECT_URL",
    )
    moonpay_api_base_url: str = Field(default="https://api.moonpay.com", alias="MOONPAY_API_BASE_URL")
    moonpay_api_key: str | None = Field(default=None, alias="MOONPAY_API_KEY")
    moonpay_api_secret: str | None = Field(default=None, alias="MOONPAY_API_SECRET")
    moonpay_deposit_id: str | None = Field(default=None, alias="MOONPAY_DEPOSIT_ID")
    moonpay_webhook_secret: str | None = Field(default=None, alias="MOONPAY_WEBHOOK_SECRET")
    moonpay_widget_base_url: str = Field(default="https://buy.moonpay.com", alias="MOONPAY_WIDGET_BASE_URL")
    moonpay_create_customer_path: str = Field(default="/v1/deposit-customers/api-key", alias="MOONPAY_CREATE_CUSTOMER_PATH")

    onramper_api_key: str | None = Field(default=None, alias="ONRAMPER_API_KEY")
    onramper_widget_base_url: str = Field(default="https://buy.onramper.com", alias="ONRAMPER_WIDGET_BASE_URL")
    onramper_default_crypto: str = Field(default="USDC", alias="ONRAMPER_DEFAULT_CRYPTO")
    onramper_default_fiat: str = Field(default="USD", alias="ONRAMPER_DEFAULT_FIAT")

    circle_api_key: str | None = Field(default=None, alias="CIRCLE_API_KEY")
    circle_entity_secret: str | None = Field(default=None, alias="CIRCLE_ENTITY_SECRET")
    circle_wallet_set_id: str | None = Field(default=None, alias="CIRCLE_WALLET_SET_ID")
    circle_wallet_id: str | None = Field(default=None, alias="CIRCLE_WALLET_ID")
    circle_wallet_address: str | None = Field(default=None, alias="CIRCLE_WALLET_ADDRESS")

    stripe_secret_key: str | None = Field(default=None, alias="STRIPE_SECRET_KEY")
    stripe_publishable_key: str | None = Field(default=None, alias="STRIPE_PUBLISHABLE_KEY")
    stripe_webhook_secret: str | None = Field(default=None, alias="STRIPE_WEBHOOK_SECRET")
    stripe_api_base_url: str = Field(default="https://api.stripe.com/v1", alias="STRIPE_API_BASE_URL")
    stripe_success_url: str | None = Field(default=None, alias="STRIPE_SUCCESS_URL")
    stripe_cancel_url: str | None = Field(default=None, alias="STRIPE_CANCEL_URL")

    ledger_base_address: str | None = Field(default=None, alias="LEDGER_BASE_ADDRESS")
    ledger_ethereum_address: str | None = Field(default=None, alias="LEDGER_ETHEREUM_ADDRESS")
    ledger_tron_address: str | None = Field(default=None, alias="LEDGER_TRON_ADDRESS")

    treasury_wallet_address: str | None = Field(default=None, alias="TREASURY_WALLET_ADDRESS")
    default_wallet_address: str | None = Field(default=None, alias="DEFAULT_WALLET_ADDRESS")

    alchemy_api_key: str = Field(default="test", alias="ALCHEMY_API_KEY")
    alchemy_network: str = Field(default="eth-mainnet", alias="ALCHEMY_NETWORK")
    alchemy_webhook_signing_key: str = Field(default="test", alias="ALCHEMY_WEBHOOK_SIGNING_KEY")
    alchemy_rpc_url: str | None = Field(default=None, alias="ALCHEMY_RPC_URL")
    alchemy_eth_rpc_url: str | None = Field(default=None, alias="ALCHEMY_ETH_RPC_URL")
    alchemy_base_rpc_url: str | None = Field(default=None, alias="ALCHEMY_BASE_RPC_URL")
    # Explicit full RPC URLs for the settlement pipeline (preferred over API key)
    alchemy_ethereum_rpc_url: str | None = Field(default=None, alias="ALCHEMY_ETHEREUM_RPC_URL")
    ethereum_rpc_url: str | None = Field(default=None, alias="ETHEREUM_RPC_URL")
    base_rpc_url: str | None = Field(default=None, alias="BASE_RPC_URL")

    # Master wallets — the approved destination addresses for settlement funds
    master_wallet_ethereum: str | None = Field(default=None, alias="MASTER_WALLET_ETHEREUM")
    master_wallet_base: str | None = Field(default=None, alias="MASTER_WALLET_BASE")
    master_wallet_tron: str | None = Field(default=None, alias="MASTER_WALLET_TRON")

    # Enterprise settlement security controls.
    # JWE private key accepts PEM text or a base64-encoded PEM value.
    settlement_oauth_issuer: str = Field(default="alshumookh-settlement-api", alias="SETTLEMENT_OAUTH_ISSUER")
    settlement_oauth_audience: str = Field(default="alshumookh-settlement", alias="SETTLEMENT_OAUTH_AUDIENCE")
    settlement_oauth_token_ttl_seconds: int = Field(default=900, alias="SETTLEMENT_OAUTH_TOKEN_TTL_SECONDS")
    settlement_jwe_private_key_pem: str | None = Field(default=None, alias="SETTLEMENT_JWE_PRIVATE_KEY_PEM")
    settlement_jwe_private_key_passphrase: str | None = Field(default=None, alias="SETTLEMENT_JWE_PRIVATE_KEY_PASSPHRASE")
    fnfcu_auth_token: str | None = Field(default=None, alias="FNFCU_AUTH_TOKEN")

    # ── Wallet roles ────────────────────────────────────────────────────────
    # ETH_TREASURY_ADDRESS  : Ledger hardware wallet — RECEIVES funds, never exposed
    # ETH_PRIVATE_KEY       : MetaMask operator software wallet — SIGNS & BROADCASTS txs
    # ETH_OPERATOR_ADDRESS  : Optional explicit address of the operator wallet (derived
    #                         automatically from ETH_PRIVATE_KEY if not set)
    eth_treasury_address: str | None = Field(default=None, alias="ETH_TREASURY_ADDRESS")
    eth_private_key: str | None = Field(default=None, alias="ETH_PRIVATE_KEY")
    # Operator wallet = MetaMask software wallet used for signing/broadcasting
    # Address: 0x620a850efe2c97A02560d9bce9978639Ed232BE2
    eth_operator_address: str = Field(
        default="0x620a850efe2c97A02560d9bce9978639Ed232BE2",
        alias="ETH_OPERATOR_ADDRESS",
    )
    eth_treasury_private_key: str | None = Field(default=None, alias="ETH_TREASURY_PRIVATE_KEY")
    # ── Token contracts — Ethereum Mainnet only ──────────────────────────────
    usdt_eth_contract: str = Field(
        default="0xdAC17F958D2ee523a2206206994597C13D831ec7",
        alias="USDT_ETH_CONTRACT",
    )
    # SIG — Al Shumookh International Group Token (Mainnet)
    sig_contract_address: str = Field(
        default="0xc2ac880e474c3576cc3afb7c560e402ce24d5b37",
        alias="SIG_CONTRACT_ADDRESS",
    )

    tron_api_url: str = Field(default="https://api.trongrid.io", alias="TRON_API_URL")
    tron_api_key: str = Field(default="test", alias="TRON_API_KEY")
    tron_treasury_address: str | None = Field(default=None, alias="TRON_TREASURY_ADDRESS")
    tron_treasury_private_key: str | None = Field(default=None, alias="TRON_TREASURY_PRIVATE_KEY")
    usdt_tron_contract: str = Field(default="TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t", alias="USDT_TRON_CONTRACT")

    default_network: str = Field(default="ethereum", alias="DEFAULT_NETWORK")
    default_token_symbol: str = Field(default="USDC", alias="DEFAULT_TOKEN_SYMBOL")
    supported_crypto_assets_raw: str = Field(default="USDT,USDC,ETH,SIG", alias="SUPPORTED_CRYPTO_ASSETS")
    tokenization_target_assets_raw: str = Field(default="USDT,SIG", alias="TOKENIZATION_TARGET_ASSETS")
    auto_payout_enabled: bool = Field(default=False, alias="AUTO_PAYOUT_ENABLED")
    transfer_confirmation_monitor_enabled: bool = Field(
        default=True,
        alias="TRANSFER_CONFIRMATION_MONITOR_ENABLED",
    )
    transfer_confirmation_interval_seconds: int = Field(
        default=60,
        alias="TRANSFER_CONFIRMATION_INTERVAL_SECONDS",
    )
    transfer_confirmations_required: int = Field(
        default=12,
        alias="TRANSFER_CONFIRMATIONS_REQUIRED",
    )

    sepolia_rpc_url: str | None = Field(default=None, alias="SEPOLIA_RPC_URL")
    # Production network = Ethereum Mainnet (chain_id=1).
    # Testnet (Sepolia, chain_id=11155111) is enabled only when ENABLE_TESTNET=true.
    token_network: str = Field(default="ethereum", alias="TOKEN_NETWORK")
    chain_id: int = Field(default=1, alias="CHAIN_ID")
    # M1 Fund Token — Ethereum Mainnet
    m1_token_contract_address: str = Field(
        default="0xD999DB972BBDc2C13a9595A1474A04F5e59169a5",
        alias="M1_TOKEN_CONTRACT_ADDRESS",
    )
    # SIG Token — must match sig_contract_address (Ethereum Mainnet)
    sig_token_contract_address: str = Field(
        default="0xc2ac880e474c3576cc3afb7c560e402ce24d5b37",
        alias="SIG_TOKEN_CONTRACT_ADDRESS",
    )
    m1_token_decimals: int = Field(default=18, alias="M1_TOKEN_DECIMALS")
    sig_token_decimals: int = Field(default=18, alias="SIG_TOKEN_DECIMALS")
    # SIG M1 issuance price in USD — used for EUR→SIG tokenization conversion
    # 23,085,000 EUR × 1.1537 ÷ 0.053266 = 500,000,000 SIG
    sig_m1_price_usd: Decimal = Field(default=Decimal("0.053266"), alias="SIG_M1_PRICE_USD")
    m1_token_name: str = Field(default="Al Shumookh M1 Fund Token", alias="M1_TOKEN_NAME")
    m1_token_symbol: str = Field(default="M1", alias="M1_TOKEN_SYMBOL")
    sig_token_name: str = Field(
        default="Al Shumookh International Group Token",
        alias="SIG_TOKEN_NAME",
    )
    sig_token_symbol: str = Field(default="SIG", alias="SIG_TOKEN_SYMBOL")
    treasury_wallet: str = Field(
        default="0xBD682cfD8382a90adfDd6745780D3D7959c4d939",
        alias="TREASURY_WALLET",
    )
    webhook_enabled: bool = Field(default=False, alias="WEBHOOK_ENABLED")
    webhook_callback_url: str | None = Field(default=None, alias="WEBHOOK_CALLBACK_URL")
    webhook_secret: str | None = Field(default=None, alias="WEBHOOK_SECRET")
    testnet_allow_supply_mismatch: bool = Field(default=True, alias="TESTNET_ALLOW_SUPPLY_MISMATCH")

    notify_from_email: str = Field(default="no-reply@alshumookhgroup.com", alias="NOTIFY_FROM_EMAIL")
    notify_to_email: str = Field(default="info@alshumookhgroup.com", alias="NOTIFY_TO_EMAIL")

    smtp_host: str | None = Field(default=None, alias="SMTP_HOST")
    smtp_port: int = Field(default=587, alias="SMTP_PORT")
    smtp_user: str | None = Field(default=None, alias="SMTP_USER")
    smtp_password: str | None = Field(default=None, alias="SMTP_PASSWORD")
    smtp_tls: bool = Field(default=True, alias="SMTP_TLS")
    sentry_dsn: str | None = Field(default=None, alias="SENTRY_DSN")

    @property
    def active_chain_id(self) -> int:
        """Returns 11155111 (Sepolia) when ENABLE_TESTNET=true, else 1 (Mainnet)."""
        return 11155111 if self.enable_testnet else 1

    @property
    def active_rpc_url(self) -> str | None:
        """Returns the correct RPC URL based on testnet flag."""
        if self.enable_testnet:
            return self.sepolia_rpc_url
        return (
            self.alchemy_ethereum_rpc_url
            or self.alchemy_eth_rpc_url
            or self.alchemy_rpc_url
            or self.ethereum_rpc_url
        )

    @property
    def sig_mainnet_contract(self) -> str:
        """Always returns the real SIG contract on Ethereum Mainnet."""
        return "0xc2ac880e474c3576cc3afb7c560e402ce24d5b37"

    @property
    def usdt_mainnet_contract(self) -> str:
        """Always returns the real USDT contract on Ethereum Mainnet."""
        return "0xdAC17F958D2ee523a2206206994597C13D831ec7"

    @property
    def resolved_coinbase_api_key_id(self) -> str | None:
        return self.coinbase_api_key_id or self.cdp_api_key_id

    @property
    def resolved_coinbase_api_key_secret(self) -> str | None:
        return self.coinbase_api_key_secret or self.cdp_api_key_secret

    def get_treasury_address(self, network: str | None = None) -> str:
        selected_network = (network or self.default_network or "ethereum").lower()

        if selected_network in {"ethereum", "eth", "erc20"}:
            address = (
                self.ledger_ethereum_address
                or self.eth_treasury_address
                or self.treasury_wallet_address
                or self.default_wallet_address
            )
        elif selected_network in {"base", "base-mainnet"}:
            address = (
                self.ledger_base_address
                or self.eth_treasury_address
                or self.treasury_wallet_address
                or self.default_wallet_address
            )
        elif selected_network in {"tron", "trx", "trc20"}:
            address = (
                self.ledger_tron_address
                or self.tron_treasury_address
                or self.treasury_wallet_address
                or self.default_wallet_address
            )
        else:
            address = self.treasury_wallet_address or self.default_wallet_address

        if not address:
            raise ValueError(f"Treasury wallet address is not configured for {selected_network}")

        return address

    def cors_allowed_origins(self) -> list[str]:
        configured = [
            item.strip().rstrip("/")
            for item in str(self.cors_allowed_origins_raw or "").split(",")
            if item.strip()
        ]
        derived = [
            str(self.public_base_url or "").strip().rstrip("/"),
            str(self.public_app_url or "").strip().rstrip("/"),
        ]
        combined: list[str] = []
        for item in [*configured, *derived]:
            if item and item not in combined:
                combined.append(item)
        # If no origins configured, allow all — prevents blank-list blocking all preflight requests
        return combined or ["*"]

    def supported_crypto_assets(self) -> list[str]:
        return [
            item.strip().upper()
            for item in str(self.supported_crypto_assets_raw or "").split(",")
            if item.strip()
        ]

    def tokenization_target_assets(self) -> list[str]:
        return [
            item.strip().upper()
            for item in str(self.tokenization_target_assets_raw or "").split(",")
            if item.strip()
        ]

    def trusted_proxy_ips(self) -> list[str]:
        configured = [
            item.strip()
            for item in str(self.trusted_proxy_ips_raw or "").split(",")
            if item.strip()
        ]
        defaults = ["127.0.0.1", "::1"]
        combined: list[str] = []
        for item in [*configured, *defaults]:
            if item and item not in combined:
                combined.append(item)
        return combined

    def health_allowed_ips(self) -> list[str]:
        return [
            item.strip()
            for item in str(self.health_allowed_ips_raw or "").split(",")
            if item.strip()
        ]

    def allowed_countries(self) -> list[str]:
        return [
            item.strip().upper()
            for item in str(self.allowed_countries_raw or "").split(",")
            if item.strip()
        ]

    def blocked_countries(self) -> list[str]:
        return [
            item.strip().upper()
            for item in str(self.blocked_countries_raw or "").split(",")
            if item.strip()
        ]

    def readiness_warnings(self) -> list[str]:
        warnings: list[str] = []

        if not self.public_base_url.startswith("https://"):
            warnings.append("PUBLIC_BASE_URL is not using HTTPS.")

        if not self.cors_allowed_origins():
            warnings.append("CORS allowlist is empty.")

        if str(self.admin_api_key or "") == "change-this-admin-key":
            warnings.append("ADMIN_API_KEY is still using the default placeholder value.")

        if self.app_debug:
            warnings.append("APP_DEBUG is enabled.")

        if not (
            self.master_wallet_ethereum
            or self.ledger_ethereum_address
            or self.eth_treasury_address
            or self.treasury_wallet_address
            or self.default_wallet_address
        ):
            warnings.append("MASTER_WALLET_ETHEREUM is not configured.")

        if not (
            self.master_wallet_base
            or self.ledger_base_address
            or self.eth_treasury_address
            or self.treasury_wallet_address
            or self.default_wallet_address
        ):
            warnings.append("MASTER_WALLET_BASE is not configured.")

        if not self.alchemy_webhook_signing_key or self.alchemy_webhook_signing_key == "test":
            warnings.append("ALCHEMY_WEBHOOK_SIGNING_KEY is missing or still set to a test value.")

        if not (
            self.alchemy_eth_rpc_url
            or self.alchemy_rpc_url
            or self.ethereum_rpc_url
        ):
            warnings.append("Ethereum RPC is not configured for settlement verification.")

        if not (
            self.alchemy_base_rpc_url
            or self.base_rpc_url
        ):
            warnings.append("Base RPC is not configured for settlement verification.")

        if not self.trusted_proxy_ips():
            warnings.append("TRUSTED_PROXY_IPS is not configured.")

        if not self.health_allowed_ips() and not self.healthcheck_token:
            warnings.append("Health endpoint isolation is not configured via HEALTH_ALLOWED_IPS or HEALTHCHECK_TOKEN.")

        return warnings


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
