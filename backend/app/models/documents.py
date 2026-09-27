"""MongoDB Beanie document models."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from beanie import Document, Indexed
from pydantic import Field
from pymongo import ASCENDING, DESCENDING, IndexModel

from app.core.enums import (
    AgentStep,
    BotStatus,
    OrderSide,
    OrderStatus,
    OrderType,
    PositionStatus,
    RiskLevel,
    SignalStatus,
    TradeDecision,
    TradingMode,
)
from app.models.schemas import RiskLimits, TradingPair


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UserDoc(Document):
    email: Indexed(str, unique=True)
    password_hash: str
    role: str = "admin"
    created_at: datetime = Field(default_factory=utcnow)

    class Settings:
        name = "users"


class BotStateDoc(Document):
    key: Indexed(str, unique=True) = "singleton"
    status: BotStatus = BotStatus.STOPPED
    mode: TradingMode = TradingMode.PAPER
    kill_switch: bool = False
    paused: bool = False
    risk_limits: RiskLimits
    pairs: List[TradingPair] = Field(default_factory=list)
    circuit_breaker_open: bool = False
    circuit_breaker_reason: Optional[str] = None
    last_cycle_at: Optional[datetime] = None
    updated_at: datetime = Field(default_factory=utcnow)

    class Settings:
        name = "bot_state"


class AgentStateDoc(Document):
    key: Indexed(str, unique=True) = "singleton"
    step: AgentStep = AgentStep.IDLE
    detail: str = "Waiting for the bot to start"
    last_result: Dict[str, Any] = Field(default_factory=dict)
    runs: int = 0
    last_run_at: Optional[datetime] = None
    updated_at: datetime = Field(default_factory=utcnow)

    class Settings:
        name = "agent_state"


class MarketSnapshotDoc(Document):
    symbol: str
    price: float
    bid: Optional[float] = None
    ask: Optional[float] = None
    volume_24h: float
    liquidity_usd: float
    price_change_24h_pct: float
    high_24h: Optional[float] = None
    low_24h: Optional[float] = None
    source: str
    stale: bool = False
    timestamp: datetime
    created_at: datetime = Field(default_factory=utcnow)

    class Settings:
        name = "market_snapshots"
        indexes = [
            IndexModel([("symbol", ASCENDING), ("timestamp", DESCENDING)]),
        ]


class SignalDoc(Document):
    symbol: str
    decision: TradeDecision
    status: SignalStatus = SignalStatus.NEW
    confidence: float
    risk_level: RiskLevel
    entry_price: float
    take_profit: float
    stop_loss: float
    reasoning_summary: str
    invalidation_condition: str
    fingerprint: Indexed(str, unique=True)
    analysis: Dict[str, Any]
    risk_rejections: Optional[List[Dict[str, Any]]] = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    class Settings:
        name = "signals"
        indexes = [
            IndexModel([("symbol", ASCENDING), ("created_at", DESCENDING)]),
        ]


class OrderDoc(Document):
    signal_id: Optional[str] = None
    position_id: Optional[str] = None
    symbol: str
    side: OrderSide
    type: OrderType = OrderType.MARKET
    status: OrderStatus = OrderStatus.SUBMITTED
    requested_price: Optional[float] = None
    filled_price: Optional[float] = None
    size: float
    size_usd: float
    slippage_bps: Optional[int] = None
    fees_usd: float = 0.0
    gas_usd: float = 0.0
    tx_hash: Optional[str] = None
    request_payload: Optional[Dict[str, Any]] = None
    response_payload: Optional[Dict[str, Any]] = None
    failure_reason: Optional[str] = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    class Settings:
        name = "orders"
        indexes = [
            IndexModel([("symbol", ASCENDING), ("created_at", DESCENDING)]),
            IndexModel([("status", ASCENDING)]),
        ]


class PositionDoc(Document):
    symbol: str
    side: OrderSide
    status: PositionStatus = PositionStatus.OPEN
    entry_price: float
    current_price: float
    size: float
    size_usd: float
    unrealized_pnl_usd: float = 0.0
    realized_pnl_usd: float = 0.0
    take_profit: float
    stop_loss: float
    fees_usd: float = 0.0
    gas_usd: float = 0.0
    entry_tx_hash: Optional[str] = None
    exit_tx_hash: Optional[str] = None
    opened_at: datetime = Field(default_factory=utcnow)
    closed_at: Optional[datetime] = None

    class Settings:
        name = "positions"
        indexes = [
            IndexModel([("status", ASCENDING), ("symbol", ASCENDING)]),
        ]


class PortfolioDoc(Document):
    key: Indexed(str, unique=True) = "singleton"
    available_balance_usd: float
    invested_usd: float = 0.0
    realized_pnl_usd: float = 0.0
    daily_pnl_usd: float = 0.0
    daily_pnl_reset_at: datetime = Field(default_factory=utcnow)
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    updated_at: datetime = Field(default_factory=utcnow)

    class Settings:
        name = "portfolio"


class AuditLogDoc(Document):
    action: str
    actor: str
    entity_type: str
    entity_id: Optional[str] = None
    details: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utcnow)

    class Settings:
        name = "audit_logs"
        indexes = [
            IndexModel([("created_at", DESCENDING)]),
            IndexModel([("action", ASCENDING)]),
        ]


class TradeHistoryDoc(Document):
    position_id: Optional[str] = None
    order_id: Optional[str] = None
    symbol: str
    side: OrderSide
    entry_price: float
    exit_price: float
    size: float
    pnl_usd: float
    fees_usd: float
    reason: str
    created_at: datetime = Field(default_factory=utcnow)

    class Settings:
        name = "trade_history"
        indexes = [
            IndexModel([("created_at", DESCENDING)]),
        ]


DOCUMENT_MODELS = [
    UserDoc,
    BotStateDoc,
    AgentStateDoc,
    MarketSnapshotDoc,
    SignalDoc,
    OrderDoc,
    PositionDoc,
    PortfolioDoc,
    AuditLogDoc,
    TradeHistoryDoc,
]
