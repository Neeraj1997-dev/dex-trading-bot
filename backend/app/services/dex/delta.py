"""Delta Exchange REST API client.

Docs: https://docs.delta.exchange/#introduction

Production (India): https://api.india.delta.exchange
Testnet:            https://cdn-ind.testnet.deltaex.org

Auth (private endpoints):
  headers: api-key, timestamp, signature
  signature = HMAC_SHA256(secret, method + timestamp + path + query + body)
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Literal, Optional, Tuple
from urllib.parse import urlencode

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

DEFAULT_BASE_URL = "https://api.india.delta.exchange"
TESTNET_BASE_URL = "https://cdn-ind.testnet.deltaex.org"


def to_delta_symbol(symbol: str) -> str:
    """Map dashboard pairs like ETH/USDC → ETHUSD; pass through BTCUSD."""
    s = symbol.strip().upper().replace("-", "/")
    if "/" in s:
        base, quote = s.split("/", 1)
        quote = quote.replace("USDT", "USD").replace("USDC", "USD")
        return f"{base}{quote}"
    return s.replace("/", "")


class DeltaExchangeClient(DexClient):
    name = "delta"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.base_url = (settings.dex_base_url or DEFAULT_BASE_URL).rstrip("/")
        self.api_key = settings.delta_api_key or settings.dex_api_key
        self.api_secret = settings.delta_api_secret
        self.live_trading = settings.delta_live_trading
        self._client = httpx.AsyncClient(
            timeout=20.0,
            headers={
                "Accept": "application/json",
                "User-Agent": "dex-trading-platform/1.0",
            },
        )
        self._product_cache: Dict[str, Dict[str, Any]] = {}

    def _sign(self, method: str, path: str, query: str = "", body: str = "") -> Dict[str, str]:
        if not self.api_key or not self.api_secret:
            raise RuntimeError("DELTA_API_KEY and DELTA_API_SECRET required for private endpoints")
        timestamp = str(int(time.time()))
        # query_string must include leading '?' when present (per Delta docs examples)
        query_string = f"?{query}" if query and not query.startswith("?") else query
        payload = method.upper() + timestamp + path + query_string + body
        signature = hmac.new(
            self.api_secret.encode(),
            payload.encode(),
            hashlib.sha256,
        ).hexdigest()
        return {
            "api-key": self.api_key,
            "timestamp": timestamp,
            "signature": signature,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "dex-trading-platform/1.0",
        }

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
        private: bool = False,
    ) -> Dict[str, Any]:
        query = urlencode({k: v for k, v in (params or {}).items() if v is not None})
        body = json.dumps(json_body, separators=(",", ":")) if json_body is not None else ""
        headers: Dict[str, str] = {
            "Accept": "application/json",
            "User-Agent": "dex-trading-platform/1.0",
        }
        if private:
            headers.update(self._sign(method, path, query, body))
        elif body:
            headers["Content-Type"] = "application/json"

        url = f"{self.base_url}{path}"
        if query:
            url = f"{url}?{query}"

        resp = await self._client.request(
            method.upper(),
            url,
            content=body if body else None,
            headers=headers,
        )
        try:
            data = resp.json()
        except Exception:
            data = {"raw": resp.text}
        if resp.status_code >= 400:
            logger.error(
                "delta_api_error",
                status=resp.status_code,
                path=path,
                body=data,
            )
            raise RuntimeError(f"Delta API {resp.status_code}: {data}")
        if isinstance(data, dict) and data.get("success") is False:
            raise RuntimeError(f"Delta API error: {data}")
        return data if isinstance(data, dict) else {"result": data}

    async def health(self) -> Literal["CONNECTED", "DEGRADED", "DISCONNECTED"]:
        try:
            await self._request("GET", "/v2/assets")
            return "CONNECTED"
        except Exception as exc:
            logger.warning("delta_health_failed", error=str(exc))
            return "DISCONNECTED"

    async def _ticker(self, symbol: str) -> Dict[str, Any]:
        delta_sym = to_delta_symbol(symbol)
        data = await self._request("GET", f"/v2/tickers/{delta_sym}")
        result = data.get("result") or data
        if isinstance(result, list):
            result = result[0] if result else {}
        return result

    def _snapshot(self, symbol: str, ticker: Dict[str, Any]) -> MarketSnapshot:
        quotes = ticker.get("quotes") or {}
        mark = float(ticker.get("mark_price") or ticker.get("close") or ticker.get("spot_price") or 0)
        bid = float(quotes.get("best_bid") or mark)
        ask = float(quotes.get("best_ask") or mark)
        price = mark or ((bid + ask) / 2 if bid and ask else 0)
        volume = float(ticker.get("volume") or 0)
        turnover = float(ticker.get("turnover_usd") or ticker.get("turnover") or 0)
        oi_usd = float(ticker.get("oi_value_usd") or ticker.get("oi_value") or 0)
        change = float(
            ticker.get("mark_change_24h")
            or ticker.get("ltp_change_24h")
            or 0
        )
        high = float(ticker.get("mark_high_24h") or ticker.get("high") or 0) or None
        low = float(ticker.get("mark_low_24h") or ticker.get("low") or 0) or None
        ts = ticker.get("timestamp") or ticker.get("time")
        timestamp = datetime.now(timezone.utc)
        if isinstance(ts, (int, float)) and ts > 0:
            # 2026 scales: seconds ~1e9, ms ~1e12, us ~1e15, ns ~1e18
            if ts > 1e16:
                ts = ts / 1e9
            elif ts > 1e13:
                ts = ts / 1e6
            elif ts > 1e11:
                ts = ts / 1e3
            try:
                timestamp = datetime.fromtimestamp(ts, tz=timezone.utc)
            except (OverflowError, OSError, ValueError):
                timestamp = datetime.now(timezone.utc)

        return MarketSnapshot(
            symbol=symbol,
            price=max(price, 1e-12),
            bid=bid or None,
            ask=ask or None,
            volume_24h=volume,
            liquidity_usd=max(oi_usd, turnover, 100_000.0),
            price_change_24h_pct=change,
            high_24h=high,
            low_24h=low,
            timestamp=timestamp,
            source=self.name,
            stale=False,
        )

    async def get_market(self, symbol: str) -> MarketSnapshot:
        ticker = await self._ticker(symbol)
        return self._snapshot(symbol, ticker)

    async def get_markets(self, symbols: List[str]) -> List[MarketSnapshot]:
        out: List[MarketSnapshot] = []
        for symbol in symbols:
            try:
                out.append(await self.get_market(symbol))
            except Exception as exc:
                logger.warning("delta_market_failed", symbol=symbol, error=str(exc))
        return out

    async def quote(self, req: DexQuoteRequest) -> DexQuote:
        market = await self.get_market(req.symbol)
        slip = req.slippage_bps / 10_000
        price = market.price * (1 + slip if req.side == "BUY" else 1 - slip)
        size = req.amount_usd / price if price else 0
        return DexQuote(
            symbol=req.symbol,
            side=req.side,
            price=price,
            amount_in=req.amount_usd if req.side == "BUY" else size,
            amount_out=size if req.side == "BUY" else req.amount_usd,
            estimated_gas_usd=0.5,  # exchange fee proxy, not on-chain gas
            liquidity_usd=market.liquidity_usd,
            route="delta-exchange",
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=15),
        )

    async def _resolve_product(self, symbol: str) -> Tuple[Optional[int], str]:
        delta_sym = to_delta_symbol(symbol)
        if delta_sym in self._product_cache:
            cached = self._product_cache[delta_sym]
            return cached.get("id"), delta_sym
        try:
            data = await self._request("GET", f"/v2/products/{delta_sym}")
            product = data.get("result") or {}
            self._product_cache[delta_sym] = product
            return product.get("id"), delta_sym
        except Exception:
            return None, delta_sym

    async def execute(self, req: DexOrderRequest) -> DexOrderResult:
        raw_req: Dict[str, Any] = {
            "symbol": req.symbol,
            "side": req.side,
            "amount_usd": req.amount_usd,
            "client_order_id": req.client_order_id,
            "provider": "delta",
        }

        # Safety: live trading requires explicit flag + credentials
        if not self.live_trading or not self.api_key or not self.api_secret:
            return await self._paper_fill_at_live_price(req, raw_req)

        market = await self.get_market(req.symbol)
        product_id, delta_sym = await self._resolve_product(req.symbol)
        # Contract size approximation: USD notional / price → contracts (floor at 1)
        size = max(1, int(req.amount_usd / max(market.price, 1e-9)))
        body = {
            "product_symbol": delta_sym,
            "size": size,
            "side": "buy" if req.side == "BUY" else "sell",
            "order_type": "market_order",
            "time_in_force": "ioc",
            "client_order_id": req.client_order_id[:32],
        }
        if product_id is not None:
            body["product_id"] = product_id
        raw_req["order_body"] = body

        try:
            data = await self._request(
                "POST",
                "/v2/orders",
                json_body=body,
                private=True,
            )
            result = data.get("result") or {}
            filled_price = float(
                result.get("average_fill_price")
                or result.get("limit_price")
                or market.price
            )
            filled_size = float(result.get("size") or size)
            order_id = str(result.get("id") or uuid.uuid4().hex)
            return DexOrderResult(
                success=True,
                status="FILLED",
                filled_price=filled_price,
                filled_size=filled_size,
                fees_usd=float(result.get("paid_commission") or 0) or req.amount_usd * 0.0005,
                gas_usd=0.0,
                tx_hash=f"delta_{order_id}",
                raw_request=raw_req,
                raw_response=data,
            )
        except Exception as exc:
            return DexOrderResult(
                success=False,
                status="FAILED",
                error=str(exc),
                raw_request=raw_req,
                raw_response={"error": str(exc)},
            )

    async def _paper_fill_at_live_price(
        self,
        req: DexOrderRequest,
        raw_req: Dict[str, Any],
    ) -> DexOrderResult:
        """Simulate fill using live Delta prices (safe default)."""
        market = await self.get_market(req.symbol)
        slip = req.slippage_bps / 10_000
        price = market.price * (1 + slip if req.side == "BUY" else 1 - slip)
        deviation = abs(price - req.expected_price) / max(req.expected_price, 1e-9)
        if deviation > max(slip * 2, 0.02):
            return DexOrderResult(
                success=False,
                status="FAILED",
                error=f"Slippage {deviation:.4%} exceeds limit",
                raw_request=raw_req,
                raw_response={"mode": "delta_paper_sim"},
            )
        filled_size = req.amount_usd / price
        tx = f"delta_sim_{uuid.uuid4().hex[:20]}"
        return DexOrderResult(
            success=True,
            status="FILLED",
            filled_price=price,
            filled_size=filled_size,
            fees_usd=req.amount_usd * 0.0005,
            gas_usd=0.0,
            tx_hash=tx,
            raw_request={**raw_req, "mode": "delta_paper_sim"},
            raw_response={"tx_hash": tx, "mark_price": market.price, "mode": "delta_paper_sim"},
        )

    async def aclose(self) -> None:
        await self._client.aclose()
