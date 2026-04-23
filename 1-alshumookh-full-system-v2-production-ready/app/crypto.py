from fastapi import APIRouter
from app.deps import AdminKey
from app.models import Network
from app.wallet_service import get_treasury_balance

router = APIRouter(prefix='/crypto', tags=['crypto'])


@router.get('/wallets/{network}')
async def crypto_wallet_status(network: Network, _: AdminKey):
    return await get_treasury_balance(network)
