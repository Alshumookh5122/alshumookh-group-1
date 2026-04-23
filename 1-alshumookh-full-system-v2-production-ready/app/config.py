from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8', extra='ignore')

    app_name: str = Field(alias='APP_NAME')
    app_env: str = Field(alias='APP_ENV')
    app_debug: bool = Field(alias='APP_DEBUG')
    app_host: str = Field(alias='APP_HOST')
    app_port: int = Field(alias='APP_PORT')
    api_prefix: str = Field(alias='API_PREFIX')
    admin_api_key: str = Field(alias='ADMIN_API_KEY')

    database_url: str = Field(alias='DATABASE_URL')
    sync_database_url: str = Field(alias='SYNC_DATABASE_URL')
    redis_url: str = Field(alias='REDIS_URL')
    celery_broker_url: str = Field(alias='CELERY_BROKER_URL')
    celery_result_backend: str = Field(alias='CELERY_RESULT_BACKEND')

    transak_base_url: str = Field(alias='TRANSAK_BASE_URL')
    transak_staging_base_url: str = Field(alias='TRANSAK_STAGING_BASE_URL')
    transak_api_key: str = Field(alias='TRANSAK_API_KEY')
    transak_api_secret: str = Field(alias='TRANSAK_API_SECRET')
    transak_webhook_secret: str | None = Field(default=None, alias='TRANSAK_WEBHOOK_SECRET')
    transak_env: str = Field(alias='TRANSAK_ENV')
    transak_default_fiat: str = Field(alias='TRANSAK_DEFAULT_FIAT')
    transak_default_crypto: str = Field(alias='TRANSAK_DEFAULT_CRYPTO')
    transak_default_network: str = Field(alias='TRANSAK_DEFAULT_NETWORK')

    alchemy_api_key: str = Field(alias='ALCHEMY_API_KEY')
    alchemy_network: str = Field(alias='ALCHEMY_NETWORK')
    alchemy_webhook_signing_key: str = Field(alias='ALCHEMY_WEBHOOK_SIGNING_KEY')
    eth_treasury_address: str = Field(alias='ETH_TREASURY_ADDRESS')
    eth_treasury_private_key: str | None = Field(default=None, alias='ETH_TREASURY_PRIVATE_KEY')
    usdt_eth_contract: str = Field(alias='USDT_ETH_CONTRACT')

    tron_api_url: str = Field(alias='TRON_API_URL')
    tron_api_key: str = Field(alias='TRON_API_KEY')
    tron_treasury_address: str = Field(alias='TRON_TREASURY_ADDRESS')
    tron_treasury_private_key: str | None = Field(default=None, alias='TRON_TREASURY_PRIVATE_KEY')
    usdt_tron_contract: str = Field(alias='USDT_TRON_CONTRACT')

    auto_payout_enabled: bool = Field(default=False, alias='AUTO_PAYOUT_ENABLED')

    notify_from_email: str = Field(alias='NOTIFY_FROM_EMAIL')
    notify_to_email: str = Field(alias='NOTIFY_TO_EMAIL')
    smtp_host: str | None = Field(default=None, alias='SMTP_HOST')
    smtp_port: int = Field(default=587, alias='SMTP_PORT')
    smtp_user: str | None = Field(default=None, alias='SMTP_USER')
    smtp_password: str | None = Field(default=None, alias='SMTP_PASSWORD')
    smtp_tls: bool = Field(default=True, alias='SMTP_TLS')
    sentry_dsn: str | None = Field(default=None, alias='SENTRY_DSN')


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[arg-type]
