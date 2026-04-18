"""
Application configuration — loaded from environment variables via pydantic-settings.
"""

from functools import lru_cache
from typing import List, Optional
from pydantic_settings import BaseSettings
from pydantic import field_validator


class Settings(BaseSettings):
    # ── App ─────────────────────────────────────────────────────────────────
    APP_NAME: str = "Alshumookh Payment System"
    APP_VERSION: str = "1.0.0"
    ENVIRONMENT: str = "development"
    DEBUG: bool = False
    SECRET_KEY: str = "change-me-in-production-min-32-chars!!"
    ALLOWED_ORIGINS: str = "http://localhost:3000,http://localhost:8000"

    @property
    def CORS_ORIGINS(self) -> List[str]:
        origins = [o.strip() for o in self.ALLOWED_ORIGINS.split(",") if o.strip()]
        if self.ENVIRONMENT == "production" and "*" not in origins:
            origins.append("*")
        return origins

    # ── Database ─────────────────────────────────────────────────────────────
    DATABASE_URL: str = "postgresql+asyncpg://user:password@localhost:5432/alshumookh"

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def fix_database_url(cls, v: str) -> str:
        """Convert Render's postgres:// URL to asyncpg format."""
        if v.startswith("postgres://"):
            v = v.replace("postgres://", "postgresql+asyncpg://", 1)
        elif v.startswith("postgresql://") and "+asyncpg" not in v:
            v = v.replace("postgresql://", "postgresql+asyncpg://", 1)
        return v

    @property
    def SYNC_DATABASE_URL(self) -> str:
        """Generate sync URL from async URL for Alembic."""
        return self.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")

    DB_POOL_SIZE: int = 5
    DB_MAX_OVERFLOW: int = 10
    DB_POOL_TIMEOUT: int = 30

    # ── Redis ────────────────────────────────────────────────────────────────
    REDIS_URL: str = "redis://localhost:6379/0"

    # ── JWT ──────────────────────────────────────────────────────────────────
    JWT_SECRET_KEY: str = "jwt-secret-change-me"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # ── Alchemy ──────────────────────────────────────────────────────────────
    ALCHEMY_API_KEY: str = ""
    ALCHEMY_WEBHOOK_SECRET: str = ""
    ALCHEMY_NETWORK: str = "ETH_MAINNET"

    @property
    def ALCHEMY_RPC_URL(self) -> str:
        network_map = {
            "ETH_MAINNET": f"https://eth-mainnet.g.alchemy.com/v2/{self.ALCHEMY_API_KEY}",
            "ETH_SEPOLIA": f"https://eth-sepolia.g.alchemy.com/v2/{self.ALCHEMY_API_KEY}",
            "MATIC_MAINNET": f"https://polygon-mainnet.g.alchemy.com/v2/{self.ALCHEMY_API_KEY}",
            "MATIC_MUMBAI": f"https://polygon-mumbai.g.alchemy.com/v2/{self.ALCHEMY_API_KEY}",
            "ARBITRUM_MAINNET": f"https://arb-mainnet.g.alchemy.com/v2/{self.ALCHEMY_API_KEY}",
            "BASE_MAINNET": f"https://base-mainnet.g.alchemy.com/v2/{self.ALCHEMY_API_KEY}",
        }
        return network_map.get(self.ALCHEMY_NETWORK, network_map["ETH_MAINNET"])

    @property
    def ALCHEMY_WS_URL(self) -> str:
        return self.ALCHEMY_RPC_URL.replace("https://", "wss://")

    # ── Treasury ─────────────────────────────────────────────────────────────
    TREASURY_WALLET_ADDRESS: str = ""
    TREASURY_PRIVATE_KEY: str = ""

    # ── Stripe ───────────────────────────────────────────────────────────────
    STRIPE_SECRET_KEY: str = ""
    STRIPE_PUBLISHABLE_KEY: str = ""
    STRIPE_WEBHOOK_SECRET: str = ""

    # ── Notifications ────────────────────────────────────────────────────────
    SENDGRID_API_KEY: str = ""
    EMAIL_FROM: str = "noreply@alshumookh.com"
    EMAIL_FROM_NAME: str = "Alshumookh Payments"
    TWILIO_ACCOUNT_SID: str = ""
    TWILIO_AUTH_TOKEN: str = ""
    TWILIO_PHONE_NUMBER: str = ""

    # ── AWS ──────────────────────────────────────────────────────────────────
    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: str = ""
    AWS_REGION: str = "us-east-1"
    S3_BUCKET_NAME: str = "alshumookh-docs"

    # ── Sentry ───────────────────────────────────────────────────────────────
    SENTRY_DSN: Optional[str] = None

    # ── Rate Limiting ────────────────────────────────────────────────────────
    RATE_LIMIT_PER_MINUTE: int = 60
    RATE_LIMIT_PER_HOUR: int = 1000

    # ── Crypto ───────────────────────────────────────────────────────────────
    MIN_CRYPTO_CONFIRMATION_BLOCKS: int = 6
    CRYPTO_PAYMENT_EXPIRY_MINUTES: int = 30
    SUPPORTED_TOKENS: str = "ETH,USDT,USDC,DAI,MATIC"

    @property
    def SUPPORTED_TOKEN_LIST(self) -> List[str]:
        return [t.strip() for t in self.SUPPORTED_TOKENS.split(",")]

    TOKEN_CONTRACTS: dict = {
        "USDT": "0xdAC17F958D2ee523a2206206994597C13D831ec7",
        "USDC": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
        "DAI": "0x6B175474E89094C44Da98b954EedeAC495271d0F",
        "MATIC": "0x7D1AfA7B718fb893dB30A3aBc0Cfc608AaCfeBB0",
    }

    # ── Fiat ─────────────────────────────────────────────────────────────────
    MIN_FIAT_AMOUNT_USD: float = 1.0
    MAX_FIAT_AMOUNT_USD: float = 50000.0
    DEFAULT_CURRENCY: str = "USD"

    # ── Admin ────────────────────────────────────────────────────────────────
    ADMIN_EMAIL: str = "admin@alshumookh.com"
    ADMIN_PASSWORD: str = "change-me"

    model_config = {
        "env_file": ".env",
        "case_sensitive": True,
        "extra": "ignore",
    }


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
