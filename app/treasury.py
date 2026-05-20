from fastapi import APIRouter
from app.deps import AdminKey
from app.models import Network
from app.schemas import TreasuryBalanceResponse
from app.wallet_service import get_treasury_balance

router = APIRouter(prefix='/treasury', tags=['treasury'])


@router.get('/balances/{network}', response_model=TreasuryBalanceResponse)
async def treasury_balance(network: Network, _: AdminKey):
    return await get_treasury_balance(network)
