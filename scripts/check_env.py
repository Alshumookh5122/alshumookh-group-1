from __future__ import annotations

from app.config import get_settings


def mask(value: str | None) -> str:
    if not value:
        return 'missing'
    if len(value) <= 8:
        return 'set'
    return f'{value[:4]}...{value[-4:]}'


settings = get_settings()

checks = {
    'DATABASE_URL': settings.database_url,
    'REDIS_URL': settings.redis_url,
    'MOONPAY_API_KEY': settings.moonpay_api_key,
    'MOONPAY_API_SECRET': settings.moonpay_api_secret,
    'MOONPAY_DEPOSIT_ID': settings.moonpay_deposit_id,
    'MOONPAY_WEBHOOK_SECRET': settings.moonpay_webhook_secret,
    'LEDGER_BASE_ADDRESS': settings.ledger_base_address,
    'ADMIN_API_KEY': settings.admin_api_key,
}

for key, value in checks.items():
    print(f'{key}: {mask(value)}')

missing = [key for key, value in checks.items() if not value]
if missing:
    raise SystemExit(f'Missing required environment values: {", ".join(missing)}')

print('Environment looks ready.')
