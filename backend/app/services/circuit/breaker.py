"""Circuit breakers for volatility, failures, and losses."""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from collections import deque
from datetime import datetime, timezone

from app.core.logging import get_logger
from app.models.documents import BotStateDoc, PortfolioDoc
from app.models.schemas import MarketSnapshot, RiskLimits
from app.services.audit.service import write_audit

logger = get_logger(__name__)


class CircuitBreaker:
    def __init__(self) -> None:
        self._failures: deque[datetime] = deque(maxlen=50)
        self._last_prices: Dict[str, float] = {}

    def record_failure(self) -> None:
        self._failures.append(datetime.now(timezone.utc))

    async def evaluate(
        self,
        markets: List[MarketSnapshot],
        limits: RiskLimits,
    ) -> Tuple[bool, Optional[str]]:
        bot = await BotStateDoc.find_one({"key": "singleton"})
        if not bot:
            return False, None

        # Excessive recent failures
        now = datetime.now(timezone.utc)
        recent_failures = sum(1 for t in self._failures if (now - t).total_seconds() < 300)
        if recent_failures >= 5:
            reason = f"Repeated failures: {recent_failures} in 5m"
            await self._trip(bot, reason)
            return True, reason

        # Abnormal volatility spike
        for m in markets:
            prev = self._last_prices.get(m.symbol)
            self._last_prices[m.symbol] = m.price
            if prev and prev > 0:
                move = abs(m.price - prev) / prev
                if move >= 0.08:  # 8% single-tick move
                    reason = f"Abnormal volatility on {m.symbol}: {move:.2%}"
                    await self._trip(bot, reason)
                    return True, reason

        # Excessive daily loss
        portfolio = await PortfolioDoc.find_one({"key": "singleton"})
        if portfolio and portfolio.daily_pnl_usd <= -abs(limits.max_daily_loss_usd):
            reason = f"Daily loss limit breached: {portfolio.daily_pnl_usd}"
            await self._trip(bot, reason)
            return True, reason

        return bot.circuit_breaker_open, bot.circuit_breaker_reason

    async def _trip(self, bot: BotStateDoc, reason: str) -> None:
        if bot.circuit_breaker_open and bot.circuit_breaker_reason == reason:
            return
        bot.circuit_breaker_open = True
        bot.circuit_breaker_reason = reason
        bot.updated_at = datetime.now(timezone.utc)
        await bot.save()
        await write_audit("CIRCUIT_BREAKER_OPEN", "system", "bot", "singleton", {"reason": reason})
        logger.warning("circuit_breaker_open", reason=reason)

    async def reset(self, actor: str = "admin") -> None:
        bot = await BotStateDoc.find_one({"key": "singleton"})
        if not bot:
            return
        bot.circuit_breaker_open = False
        bot.circuit_breaker_reason = None
        bot.updated_at = datetime.now(timezone.utc)
        await bot.save()
        self._failures.clear()
        await write_audit("CIRCUIT_BREAKER_RESET", actor, "bot", "singleton", {})
