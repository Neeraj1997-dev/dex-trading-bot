"""1inch aggregator client — secrets stay server-side only."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Literal, Tuple

import httpx

from app.core.config import Settings
from app.core.logging import get_logger
from app.models.schemas import MarketSnapshot
from app.services.dex.base import (
    DexClient,
    DexOrderRequest,
    DexOrderResult,
    DexQuote,
    DexQuoteRequest,
)

logger = get_logger(__name__)

# Common token addresses on Ethereum mainnet (extend via config/DB as needed)
TOKEN_ADDRESSES: Dict[str, str] = {
    "ETH": "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE",
    "WETH": "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
    "USDC": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
    "WBTC": "0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599",
    "LINK": "0x514910771AF9Ca656af840dff83E8264EcF986CA",
}


class OneInchDexClient(DexClient):
    """Read quotes from 1inch API. Live execution requires wallet key (kept server-side)."""

    name = "oneinch"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.base_url = settings.dex_base_url or "https://api.1inch.dev/swap/v6.0"
        self.api_key = settings.dex_api_key
        self.chain_id = settings.chain_id
        self._client = httpx.AsyncClient(timeout=20.0)

    def _headers(self) -> Dict[str, str]:
        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _split_symbol(self, symbol: str) -> Tuple[str, str]:
        base, quote = symbol.split("/")
        return base.upper(), quote.upper()

    def _addr(self, token: str) -> str:
        if token not in TOKEN_ADDRESSES:
            raise ValueError(f"Unknown token {token}; add address mapping")
        return TOKEN_ADDRESSES[token]

    async def health(self) -> Literal["CONNECTED", "DEGRADED", "DISCONNECTED"]:
        try:
            # Lightweight health — if no key, mark degraded but usable for mock fallbacks
            if not self.api_key:
                return "DEGRADED"
            url = f"{self.base_url}/{self.chain_id}/healthcheck"
            resp = await self._client.get(url, headers=self._headers())
            if resp.status_code < 500:
                return "CONNECTED"
            return "DEGRADED"
        except Exception:
            return "DISCONNECTED"

    async def get_market(self, symbol: str) -> MarketSnapshot:
        base, quote = self._split_symbol(symbol)
        # Quote 1 unit of base into quote
        amount = 10**18 if base in ("ETH", "WETH") else 10**8 if base == "WBTC" else 10**18
        url = f"{self.base_url}/{self.chain_id}/quote"
        params = {
            "src": self._addr(base if base != "ETH" else "WETH"),
            "dst": self._addr(quote),
            "amount": str(amount),
        }
        resp = await self._client.get(url, params=params, headers=self._headers())
        resp.raise_for_status()
        data: Dict[str, Any] = resp.json()
        dst_amount = float(data.get("dstAmount", 0))
        # Normalize approx price
        decimals_dst = 6 if quote == "USDC" else 18
        price = (dst_amount / (10**decimals_dst)) / (amount / (10**18 if base != "WBTC" else 10**8))
        return MarketSnapshot(
            symbol=symbol,
            price=max(price, 1e-12),
            volume_24h=0.0,
            liquidity_usd=float(data.get("gas", 0)) * 0 + 100_000,  # placeholder
            price_change_24h_pct=0.0,
            timestamp=datetime.now(timezone.utc),
            source=self.name,
            stale=False,
        )

    async def get_markets(self, symbols: List[str]) -> List[MarketSnapshot]:
        out: List[MarketSnapshot] = []
        for s in symbols:
            try:
                out.append(await self.get_market(s))
            except Exception as exc:
                logger.warning("oneinch_market_failed", symbol=s, error=str(exc))
        return out

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
            estimated_gas_usd=15.0,
            liquidity_usd=market.liquidity_usd,
            route="1inch",
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=20),
        )

    async def execute(self, req: DexOrderRequest) -> DexOrderResult:
        """Live swap submission is intentionally gated — never expose private keys."""
        raw_req = {
            "symbol": req.symbol,
            "side": req.side,
            "amount_usd": req.amount_usd,
            "client_order_id": req.client_order_id,
        }
        if not self.settings.wallet_private_key:
            return DexOrderResult(
                success=False,
                status="FAILED",
                error="WALLET_PRIVATE_KEY not configured; use PAPER mode or configure wallet server-side",
                raw_request=raw_req,
                raw_response={"error": "NO_WALLET"},
            )
        # For safety in this open-source template, live broadcast is not auto-enabled.
        # Operators should wire a dedicated signer service with least privilege.
        return DexOrderResult(
            success=False,
            status="FAILED",
            error="Live 1inch execution disabled in template; use PAPER or integrate a signer service",
            raw_request=raw_req,
            raw_response={"error": "LIVE_EXEC_DISABLED"},
        )

    async def aclose(self) -> None:
        await self._client.aclose()
