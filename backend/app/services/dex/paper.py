"""Paper / mock DEX with simulated market data and fills."""

from __future__ import annotations

import random
import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Literal

from app.models.schemas import MarketSnapshot
from app.services.dex.base import (
    DexClient,
    DexOrderRequest,
    DexOrderResult,
    DexQuote,
    DexQuoteRequest,
)

# Seed reference prices for common pairs
BASE_PRICES = {
    "ETH/USDC": 3200.0,
    "WBTC/USDC": 95_000.0,
    "LINK/USDC": 18.5,
    "UNI/USDC": 9.2,
    "AAVE/USDC": 180.0,
}


class PaperDexClient(DexClient):
    """Simulates DEX markets without real funds or private keys."""

    name = "paper"

    def __init__(self) -> None:
        self._prices: Dict[str, float] = dict(BASE_PRICES)
        self._rng = random.Random(42)

    def _ensure(self, symbol: str) -> float:
        if symbol not in self._prices:
            self._prices[symbol] = 10.0 + self._rng.random() * 100
        return self._prices[symbol]

    def _tick(self, symbol: str) -> float:
        price = self._ensure(symbol)
        # Geometric Brownian-ish micro move
        change = self._rng.gauss(0, 0.002)
        price = max(price * (1 + change), 0.0001)
        self._prices[symbol] = price
        return price

    async def health(self) -> Literal["CONNECTED", "DEGRADED", "DISCONNECTED"]:
        return "CONNECTED"

    async def get_market(self, symbol: str) -> MarketSnapshot:
        price = self._tick(symbol)
        spread = price * 0.0005
        vol = abs(self._rng.gauss(0, 0.8))
        return MarketSnapshot(
            symbol=symbol,
            price=price,
            bid=price - spread,
            ask=price + spread,
            volume_24h=1_000_000 + self._rng.random() * 5_000_000,
            liquidity_usd=500_000 + self._rng.random() * 2_000_000,
            price_change_24h_pct=vol * (1 if self._rng.random() > 0.5 else -1),
            high_24h=price * 1.02,
            low_24h=price * 0.98,
            timestamp=datetime.now(timezone.utc),
            source=self.name,
            stale=False,
        )

    async def get_markets(self, symbols: List[str]) -> List[MarketSnapshot]:
        return [await self.get_market(s) for s in symbols]

    async def quote(self, req: DexQuoteRequest) -> DexQuote:
        market = await self.get_market(req.symbol)
        slip = req.slippage_bps / 10_000
        price = market.price * (1 + slip if req.side == "BUY" else 1 - slip)
        size = req.amount_usd / price
        return DexQuote(
            symbol=req.symbol,
            side=req.side,
            price=price,
            amount_in=req.amount_usd if req.side == "BUY" else size,
            amount_out=size if req.side == "BUY" else req.amount_usd,
            estimated_gas_usd=2.5,
            liquidity_usd=market.liquidity_usd,
            route="paper-pool",
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=30),
        )

    async def execute(self, req: DexOrderRequest) -> DexOrderResult:
        quote = await self.quote(
            DexQuoteRequest(
                symbol=req.symbol,
                side=req.side,
                amount_usd=req.amount_usd,
                slippage_bps=req.slippage_bps,
            )
        )
        max_slip = req.slippage_bps / 10_000
        deviation = abs(quote.price - req.expected_price) / max(req.expected_price, 1e-9)
        raw_req = {
            "symbol": req.symbol,
            "side": req.side,
            "amount_usd": req.amount_usd,
            "expected_price": req.expected_price,
            "client_order_id": req.client_order_id,
        }
        if deviation > max_slip:
            return DexOrderResult(
                success=False,
                status="FAILED",
                error=f"Slippage {deviation:.4%} exceeds limit {max_slip:.4%}",
                raw_request=raw_req,
                raw_response={"error": "SLIPPAGE"},
            )

        filled_size = req.amount_usd / quote.price
        fees = req.amount_usd * 0.001
        tx = f"paper_{uuid.uuid4().hex[:24]}"
        return DexOrderResult(
            success=True,
            status="FILLED",
            filled_price=quote.price,
            filled_size=filled_size,
            fees_usd=fees,
            gas_usd=quote.estimated_gas_usd,
            tx_hash=tx,
            raw_request=raw_req,
            raw_response={
                "tx_hash": tx,
                "filled_price": quote.price,
                "filled_size": filled_size,
            },
        )


class MockVolatileDexClient(PaperDexClient):
    """Higher volatility mock for circuit-breaker testing."""

    name = "mock"

    def _tick(self, symbol: str) -> float:
        price = self._ensure(symbol)
        change = self._rng.gauss(0, 0.02)
        price = max(price * (1 + change), 0.0001)
        # Occasional spike
        if self._rng.random() < 0.05:
            price *= 1 + (0.08 * (1 if self._rng.random() > 0.5 else -1))
        self._prices[symbol] = price
        return price
