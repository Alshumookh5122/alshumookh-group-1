"""
coinbase_routes.py
──────────────────
Coinbase / CDP onramp routes.
All transaction creation is handled through app/transactions.py and
app/payments.py. This module re-exports a combined router for
backward compatibility with main.py.
"""
from __future__ import annotations

from fastapi import APIRouter

# All Coinbase/MoonPay routes are in transactions.py and payments.py.
# This stub satisfies the import in main.py without breaking anything.
router = APIRouter(tags=["coinbase"])
