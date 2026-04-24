from contextlib import asynccontextmanager
import sentry_sdk
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.admin import router as admin_router
from app.config import get_settings
from app.crypto import router as crypto_router
from app.database import Base, engine
from app.fiat import router as fiat_router
from app.payments import router as payments_router
from app.public import router as public_router
from app.treasury import router as treasury_router
from app.webhooks import router as webhooks_router

settings = get_settings()
if settings.sentry_dsn:
    sentry_sdk.init(dsn=settings.sentry_dsn)


@asynccontextmanager
async def lifespan(_: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield


app = FastAPI(title=settings.app_name, debug=settings.app_debug, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)

app.include_router(payments_router, prefix=settings.api_prefix)
app.include_router(fiat_router, prefix=settings.api_prefix)
app.include_router(crypto_router, prefix=settings.api_prefix)
app.include_router(treasury_router, prefix=settings.api_prefix)
app.include_router(admin_router, prefix=settings.api_prefix)
app.include_router(webhooks_router)
app.include_router(public_router)


@app.get('/health')
async def health():
    return {'status': 'ok', 'env': settings.app_env}

@app.get('/')
async def root():
    return {'message': 'Alshumookh API is running', 'status': 'live', 'docs': '/docs', 'health': '/health'}
