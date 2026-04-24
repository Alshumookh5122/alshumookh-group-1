# Alshumookh Crypto Payment Gateway — Ledger Edition

FastAPI payment gateway for receiving USDT directly into a Ledger treasury wallet while Transak approval is pending.

## Included

- Render-ready backend
- Professional payment page: `/pay/{order_id}`
- Ledger direct payment orders
- Ethereum ERC-20 USDT and Tron TRC-20 USDT treasury addresses
- Admin manual confirmation endpoint
- Transak mock mode until approval
- Swagger docs at `/docs`

## Security

Do not put Ledger seed phrase or private keys in Render, GitHub, or `.env`.
Only use public Ledger receiving addresses:

```env
ETH_TREASURY_ADDRESS=your_ledger_eth_address
TRON_TREASURY_ADDRESS=your_ledger_tron_address
AUTO_PAYOUT_ENABLED=false
```

## Render commands

Build Command:

```bash
pip install -r requirements.txt
```

Start Command:

```bash
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

## Key Environment Variables

```env
PUBLIC_BASE_URL=https://your-service.onrender.com
TRANSAK_MOCK_ENABLED=true
AUTO_PAYOUT_ENABLED=false
ETH_TREASURY_ADDRESS=your-ledger-eth-address
TRON_TREASURY_ADDRESS=your-ledger-tron-address
```

After Transak approval:

```env
TRANSAK_MOCK_ENABLED=false
TRANSAK_ENV=production
TRANSAK_API_KEY=approved-production-key
TRANSAK_API_SECRET=approved-production-secret
```

## Create a Ledger payment order

`POST /api/v1/payments/ledger/order`

```json
{
  "network": "tron",
  "crypto_currency": "USDT",
  "crypto_amount": 100,
  "fiat_currency": "USD",
  "fiat_amount": 100,
  "payer_email": "client@example.com"
}
```

The response includes `payment_url`, `treasury_wallet_address`, `qr_url`, and `payment_reference`.

## Public payment page

`GET /pay/{order_id}`

## Check order status

`GET /api/v1/payments/ledger/status/{order_id}`

## Manually confirm after Ledger receives funds

`POST /api/v1/payments/ledger/confirm`

Header:

```text
X-Admin-Api-Key: your-admin-key
```

Body:

```json
{
  "order_id": "ORDER_ID",
  "tx_hash": "BLOCKCHAIN_TX_HASH",
  "note": "Confirmed in Ledger Live"
}
```
