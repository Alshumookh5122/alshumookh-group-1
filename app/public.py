from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.ledger_service import get_order
from app.payments import payment_page_html

router = APIRouter(tags=["public"])


@router.get("/pay/{order_id}", response_class=HTMLResponse, include_in_schema=False)
async def public_payment_page(order_id: str, db: AsyncSession = Depends(get_db)):
    order = await get_order(db, order_id)
    return HTMLResponse(payment_page_html(order))


@router.get("/pay/mock", response_class=HTMLResponse, include_in_schema=False)
async def mock_payment_page():
    return HTMLResponse(
        """
        <html><body style='font-family:Arial;background:#07111f;color:white;padding:40px'>
        <h1>AL SHUMOOKH Transak Mock Payment</h1>
        <p>Transak is currently in mock mode until partner approval is completed.</p>
        </body></html>
        """
    )
