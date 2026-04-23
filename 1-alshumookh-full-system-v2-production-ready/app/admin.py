from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.deps import AdminKey
from app.models import PaymentOrder, TreasuryWallet
from app.reconciliation_service import reconcile

router = APIRouter(prefix='/admin', tags=['admin'])


@router.get('/orders')
async def list_orders(_: AdminKey, db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(PaymentOrder).order_by(PaymentOrder.created_at.desc()))
    orders = res.scalars().all()
    return [{'id': str(o.id), 'status': o.status, 'provider': o.provider, 'wallet': o.user_wallet_address} for o in orders]


@router.get('/wallets')
async def list_wallets(_: AdminKey, db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(TreasuryWallet).order_by(TreasuryWallet.created_at.desc()))
    rows = res.scalars().all()
    return [{'id': str(w.id), 'network': w.network, 'address': w.address, 'label': w.label} for w in rows]


@router.post('/reconcile')
async def run_reconcile(_: AdminKey, db: AsyncSession = Depends(get_db)):
    return await reconcile(db)
