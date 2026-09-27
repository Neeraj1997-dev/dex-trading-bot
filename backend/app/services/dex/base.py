"""DEX client interfaces and helpers."""

from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

from app.models.schemas import MarketSnapshot


@dataclass
class DexQuoteRequest:
    symbol: str
    side: Literal["BUY", "SELL"]
    amount_usd: float
    slippage_bps: int


@dataclass
class DexQuote:
    symbol: str
    side: str
    price: float
    amount_in: float
    amount_out: float
    estimated_gas_usd: float
    liquidity_usd: float
    route: str
    expires_at: datetime


@dataclass
class DexOrderRequest:
    symbol: str
    side: Literal["BUY", "SELL"]
    amount_usd: float
    slippage_bps: int
    expected_price: float
    client_order_id: str


@dataclass
class DexOrderResult:
    success: bool
    status: Literal["FILLED", "PARTIAL", "FAILED"]
    filled_price: Optional[float] = None
    filled_size: Optional[float] = None
    fees_usd: float = 0.0
    gas_usd: float = 0.0
    tx_hash: Optional[str] = None
    raw_request: Dict[str, Any] = field(default_factory=dict)
    raw_response: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None


class DexClient(ABC):
    name: str

    @abstractmethod
    async def health(self) -> Literal["CONNECTED", "DEGRADED", "DISCONNECTED"]:
        ...

    @abstractmethod
    async def get_market(self, symbol: str) -> MarketSnapshot:
        ...

    @abstractmethod
    async def get_markets(self, symbols: List[str]) -> List[MarketSnapshot]:
        ...

    @abstractmethod
    async def quote(self, req: DexQuoteRequest) -> DexQuote:
        ...

    @abstractmethod
    async def execute(self, req: DexOrderRequest) -> DexOrderResult:
        ...


def signal_fingerprint(
    symbol: str,
    decision: str,
    entry_price: float,
    take_profit: float,
    stop_loss: float,
    bucket_minutes: int = 15,
) -> str:
    """Deterministic fingerprint to prevent duplicate signal execution."""
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    window = now_ms // (bucket_minutes * 60_000)
    payload = "|".join(
        [
            symbol,
            decision,
            f"{round(entry_price, 4)}",
            f"{round(take_profit, 4)}",
            f"{round(stop_loss, 4)}",
            str(window),
        ]
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:32]
