from fastapi import APIRouter

router = APIRouter(prefix='/fiat', tags=['fiat'])


@router.get('/providers')
async def list_fiat_providers():
    return {'providers': ['transak'], 'note': 'MoonPay intentionally not wired in this scaffold'}
