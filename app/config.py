from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8', extra='ignore')

    app_name: str = Field(default='Alshumookh Payment Gateway', alias='APP_NAME')
    app_env: str = Field(default='production', alias='APP_ENV')
    app_debug: bool = Field(default=False, alias='APP_DEBUG')
    app_host: str = Field(default='0.0.0.0', alias='APP_HOST')
    app_port: int = Field(default=8000, alias='APP_PORT')
    api_prefix: str = Field(default='/api/v1', alias='API_PREFIX')
    admin_api_key: str = Field(default='change-this-admin-key', alias='ADMIN_API_KEY')
    public_base_url: str | None = Field(default=None, alias='PUBLIC_BASE_URL')

    database_url: str = Field(default='sqlite+aiosqlite:///./alshumookh.db', alias='DATABASE_URL')
    sync_database_url: str = Field(default='sqlite:///./alshumookh.db', alias='SYNC_DATABASE_URL')
    redis_url: str = Field(default='redis://localhost:6379/0', alias='REDIS_URL')
    celery_broker_url: str = Field(default='redis://localhost:6379/0', alias='CELERY_BROKER_URL')
    celery_result_backend: str = Field(default='redis://localhost:6379/0', alias='CELERY_RESULT_BACKEND')

    transak_base_url: str = Field(default='https://api.transak.com/api/v2', alias='TRANSAK_BASE_URL')
    transak_staging_base_url: str = Field(default='https://api-stg.transak.com/api/v2', alias='TRANSAK_STAGING_BASE_URL')
    transak_api_key: str = Field(default='test', alias='TRANSAK_API_KEY')
    transak_api_secret: str = Field(default='test', alias='TRANSAK_API_SECRET')
    transak_webhook_secret: str | None = Field(default=None, alias='TRANSAK_WEBHOOK_SECRET')
    transak_env: str = Field(default='production', alias='TRANSAK_ENV')
    transak_default_fiat: str = Field(default='USD', alias='TRANSAK_DEFAULT_FIAT')
    transak_default_crypto: str = Field(default='USDT', alias='TRANSAK_DEFAULT_CRYPTO')
    transak_default_network: str = Field(default='ethereum', alias='TRANSAK_DEFAULT_NETWORK')
    transak_mock_enabled: bool = Field(default=True, alias='TRANSAK_MOCK_ENABLED')

    alchemy_api_key: str = Field(default='test', alias='ALCHEMY_API_KEY')
    alchemy_network: str = Field(default='eth-mainnet', alias='ALCHEMY_NETWORK')
    alchemy_webhook_signing_key: str = Field(default='test', alias='ALCHEMY_WEBHOOK_SIGNING_KEY')
    eth_treasury_address: str = Field(default='0x0000000000000000000000000000000000000000', alias='ETH_TREASURY_ADDRESS')
    eth_treasury_private_key: str | None = Field(default=None, alias='ETH_TREASURY_PRIVATE_KEY')
    usdt_eth_contract: str = Field(default='0xdAC17F958D2ee523a2206206994597C13D831ec7', alias='USDT_ETH_CONTRACT')

    tron_api_url: str = Field(default='https://api.trongrid.io', alias='TRON_API_URL')
    tron_api_key: str = Field(default='test', alias='TRON_API_KEY')
    tron_treasury_address: str = Field(default='TXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX', alias='TRON_TREASURY_ADDRESS')
    tron_treasury_private_key: str | None = Field(default=None, alias='TRON_TREASURY_PRIVATE_KEY')
    usdt_tron_contract: str = Field(default='TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t', alias='USDT_TRON_CONTRACT')

    auto_payout_enabled: bool = Field(default=False, alias='AUTO_PAYOUT_ENABLED')

    notify_from_email: str = Field(default='no-reply@alshumookhgroup.com', alias='NOTIFY_FROM_EMAIL')
    notify_to_email: str = Field(default='info@alshumookhgroup.com', alias='NOTIFY_TO_EMAIL')
    smtp_host: str | None = Field(default=None, alias='SMTP_HOST')
    smtp_port: int = Field(default=587, alias='SMTP_PORT')
    smtp_user: str | None = Field(default=None, alias='SMTP_USER')
    smtp_password: str | None = Field(default=None, alias='SMTP_PASSWORD')
    smtp_tls: bool = Field(default=True, alias='SMTP_TLS')
    sentry_dsn: str | None = Field(default=None, alias='SENTRY_DSN')


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[arg-type]


settings = get_settings()
