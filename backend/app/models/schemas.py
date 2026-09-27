"""Pydantic schemas for API and AI structured output."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator

from app.core.enums import (
    BotStatus,
    ConnectionHealth,
    OrderSide,
    OrderStatus,
    OrderType,
    PositionStatus,
    RiskLevel,
    SignalStatus,
    TradeDecision,
    TradingMode,
)


class RiskLimits(BaseModel):
    max_position_size_usd: float = Field(gt=0)
    max_daily_loss_usd: float = Field(gt=0)
    max_trades_per_day: int = Field(gt=0)
    max_portfolio_exposure_pct: float = Field(gt=0, le=100)
    stop_loss_pct: float = Field(gt=0, le=50)
    take_profit_pct: float = Field(gt=0, le=200)
    max_slippage_bps: int = Field(gt=0, le=5000)
    min_liquidity_usd: float = Field(ge=0)
    max_gas_usd: float = Field(gt=0)
    min_confidence: float = Field(ge=0, le=100)
    max_open_positions: int = Field(gt=0)


class TradingPair(BaseModel):
    symbol: str
    base_token: str
    quote_token: str
    base_address: Optional[str] = None
    quote_address: Optional[str] = None
    enabled: bool = True
    chain_id: Optional[int] = None


class MarketSnapshot(BaseModel):
    symbol: str
    price: float = Field(gt=0)
    bid: Optional[float] = None
    ask: Optional[float] = None
    volume_24h: float = Field(ge=0)
    liquidity_usd: float = Field(ge=0)
    price_change_24h_pct: float
    high_24h: Optional[float] = None
    low_24h: Optional[float] = None
    timestamp: datetime
    source: str
    stale: bool = False


class AiAnalysis(BaseModel):
    """Strict structured OpenAI output — validated before risk/execution."""

    decision: TradeDecision
    symbol: str = Field(min_length=3, max_length=64)
    entry_price: float = Field(gt=0)
    take_profit: float = Field(gt=0)
    stop_loss: float = Field(gt=0)
    confidence: float = Field(ge=0, le=100)
    risk_level: RiskLevel
    reasoning_summary: str = Field(max_length=2000)
    invalidation_condition: str = Field(max_length=1000)
    market_trend: Optional[Literal["BULLISH", "BEARISH", "SIDEWAYS"]] = None
    momentum: Optional[Literal["STRONG", "MODERATE", "WEAK"]] = None
    volatility: Optional[Literal["LOW", "MEDIUM", "HIGH"]] = None
    support: Optional[float] = Field(default=None, ge=0)
    resistance: Optional[float] = Field(default=None, ge=0)

    @field_validator("take_profit", "stop_loss")
    @classmethod
    def positive_levels(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("price levels must be positive")
        return v


class RiskRejection(BaseModel):
    code: str
    message: str
    rule: str


class RiskEvaluationResult(BaseModel):
    allowed: bool
    rejections: List[RiskRejection] = Field(default_factory=list)
    adjusted_size_usd: Optional[float] = None
    adjusted_take_profit: Optional[float] = None
    adjusted_stop_loss: Optional[float] = None


class LoginRequest(BaseModel):
    email: str
    password: str = Field(min_length=8)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class BotControlRequest(BaseModel):
    action: Literal[
        "START", "STOP", "PAUSE", "RESUME", "KILL_SWITCH", "RESET_KILL_SWITCH"
    ]


class ModeUpdateRequest(BaseModel):
    mode: TradingMode


class PairToggleRequest(BaseModel):
    symbol: str
    enabled: bool


class RiskUpdateRequest(BaseModel):
    limits: RiskLimits


class SignalApproveRequest(BaseModel):
    approve: bool
    note: Optional[str] = None


class PortfolioSummary(BaseModel):
    total_value_usd: float
    available_balance_usd: float
    invested_usd: float
    unrealized_pnl_usd: float
    realized_pnl_usd: float
    daily_pnl_usd: float
    open_positions: int
    win_rate: float
    total_trades: int
    wins: int
    losses: int


class PositionView(BaseModel):
    id: str
    symbol: str
    side: OrderSide
    status: PositionStatus
    entry_price: float
    current_price: float
    size: float
    size_usd: float
    unrealized_pnl_usd: float
    realized_pnl_usd: float
    take_profit: float
    stop_loss: float
    fees_usd: float
    gas_usd: float
    opened_at: datetime
    closed_at: Optional[datetime] = None
    entry_tx_hash: Optional[str] = None
    exit_tx_hash: Optional[str] = None


class OrderView(BaseModel):
    id: str
    symbol: str
    side: OrderSide
    type: OrderType
    status: OrderStatus
    requested_price: Optional[float] = None
    filled_price: Optional[float] = None
    size: float
    size_usd: float
    slippage_bps: Optional[int] = None
    tx_hash: Optional[str] = None
    failure_reason: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class SignalView(BaseModel):
    id: str
    symbol: str
    decision: TradeDecision
    status: SignalStatus
    confidence: float
    risk_level: RiskLevel
    entry_price: float
    take_profit: float
    stop_loss: float
    reasoning_summary: str
    invalidation_condition: str
    fingerprint: str
    created_at: datetime
    analysis: Optional[AiAnalysis] = None
    risk_rejections: Optional[List[RiskRejection]] = None


class ConnectionStatus(BaseModel):
    dex: ConnectionHealth
    openai: ConnectionHealth
    database: ConnectionHealth
    last_market_update: Optional[datetime] = None


class BotStateView(BaseModel):
    status: BotStatus
    mode: TradingMode
    kill_switch: bool
    paused: bool
    risk_limits: RiskLimits
    pairs: List[TradingPair]
    last_cycle_at: Optional[datetime] = None
    circuit_breaker_open: bool
    circuit_breaker_reason: Optional[str] = None


class AuditEventView(BaseModel):
    id: str
    action: str
    actor: str
    entity_type: str
    entity_id: Optional[str] = None
    details: Dict[str, Any]
    created_at: datetime


class DashboardSnapshot(BaseModel):
    bot: BotStateView
    portfolio: PortfolioSummary
    positions: List[PositionView]
    orders: List[OrderView]
    signals: List[SignalView]
    connections: ConnectionStatus
    recent_market: List[MarketSnapshot]
    trade_history: List[Dict[str, Any]] = Field(default_factory=list)
