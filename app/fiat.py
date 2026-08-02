from fastapi import APIRouter

router = APIRouter(prefix="/fiat", tags=["fiat"])


@router.get("/providers")
async def list_fiat_providers():
    return {
        "providers": [
            {
                "id": "moonpay",
                "name": "MoonPay Commerce",
                "enabled": True,
                "methods": ["card", "bank_transfer"],
                "supported_networks": ["ethereum", "base"],
                "supported_crypto": ["USDC", "ETH"],
                "note": "Payment method availability depends on MoonPay and payer eligibility.",
            }
        ],
        "default_provider": "moonpay",
        "disabled_providers": [],
        "note": "MoonPay Commerce is the enabled payment provider.",
    }
