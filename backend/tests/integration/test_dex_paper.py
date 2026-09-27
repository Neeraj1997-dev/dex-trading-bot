"""Integration-style tests for fingerprint and paper quote path."""

from __future__ import annotations

import pytest

from app.services.dex.base import signal_fingerprint
from app.services.dex.paper import PaperDexClient
from app.services.dex.base import DexQuoteRequest


def test_fingerprint_stable_within_bucket():
    a = signal_fingerprint("ETH/USDC", "BUY", 3200.12345, 3400.0, 3100.0)
    b = signal_fingerprint("ETH/USDC", "BUY", 3200.12349, 3400.0, 3100.0)
    assert a == b


def test_fingerprint_differs_by_decision():
    a = signal_fingerprint("ETH/USDC", "BUY", 3200.0, 3400.0, 3100.0)
    b = signal_fingerprint("ETH/USDC", "SELL", 3200.0, 3400.0, 3100.0)
    assert a != b


@pytest.mark.asyncio
async def test_paper_quote_and_markets():
    client = PaperDexClient()
    markets = await client.get_markets(["ETH/USDC", "WBTC/USDC"])
    assert len(markets) == 2
    q = await client.quote(
        DexQuoteRequest(symbol="ETH/USDC", side="BUY", amount_usd=500, slippage_bps=50)
    )
    assert q.price > 0
    assert q.estimated_gas_usd > 0
