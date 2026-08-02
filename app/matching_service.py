from app.models import OrderStatus, PaymentOrder


def should_mark_complete(order: PaymentOrder, provider_status: str | None) -> bool:
    return provider_status in {'COMPLETED', 'SUCCESS'} and order.status != OrderStatus.COMPLETED
