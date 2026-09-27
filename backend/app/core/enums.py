"""Shared enums and constants."""

from __future__ import annotations

from enum import Enum


class TradingMode(str, Enum):
    PAPER = "PAPER"
    MANUAL_APPROVAL = "MANUAL_APPROVAL"
    AUTO = "AUTO"


class AgentStep(str, Enum):
    IDLE = "IDLE"
    OBSERVE = "OBSERVE"
    ANALYZE = "ANALYZE"
    RISK = "RISK"
    ACT = "ACT"
    DONE = "DONE"
    BLOCKED = "BLOCKED"


class BotStatus(str, Enum):
    STOPPED = "STOPPED"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    KILL_SWITCH = "KILL_SWITCH"
    ERROR = "ERROR"


class TradeDecision(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    NO_TRADE = "NO_TRADE"


class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"


class OrderStatus(str, Enum):
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUBMITTED = "SUBMITTED"
    PARTIAL = "PARTIAL"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"


class PositionStatus(str, Enum):
    OPEN = "OPEN"
    CLOSING = "CLOSING"
    CLOSED = "CLOSED"


class SignalStatus(str, Enum):
    NEW = "NEW"
    VALIDATED = "VALIDATED"
    RISK_REJECTED = "RISK_REJECTED"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    EXECUTED = "EXECUTED"
    EXPIRED = "EXPIRED"
    DUPLICATE = "DUPLICATE"


class ConnectionHealth(str, Enum):
    CONNECTED = "CONNECTED"
    DEGRADED = "DEGRADED"
    DISCONNECTED = "DISCONNECTED"
