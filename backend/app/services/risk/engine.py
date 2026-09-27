"""Deterministic risk engine — AI signals cannot bypass these rules."""

from __future__ import annotations

from typing import List

from datetime import datetime, timezone

from app.core.enums import OrderStatus, PositionStatus, TradeDecision
from app.core.logging import get_logger
from app.models.documents import OrderDoc, PortfolioDoc, PositionDoc
from app.models.schemas import (
    AiAnalysis,
    MarketSnapshot,
    RiskEvaluationResult,
    RiskLimits,
    RiskRejection,
)

logger = get_logger(__name__)


class RiskEngine:
    async def evaluate(
        self,
        analysis: AiAnalysis,
        market: MarketSnapshot,
        limits: RiskLimits,
        *,
        kill_switch: bool,
        circuit_open: bool,
        estimated_gas_usd: float,
    ) -> RiskEvaluationResult:
        rejections: List[RiskRejection] = []

        if kill_switch:
            rejections.append(
                RiskRejection(
                    code="KILL_SWITCH",
                    message="Emergency kill switch is active",
                    rule="kill_switch",
                )
            )
        if circuit_open:
            rejections.append(
                RiskRejection(
                    code="CIRCUIT_BREAKER",
                    message="Circuit breaker is open",
                    rule="circuit_breaker",
                )
            )
        if analysis.decision == TradeDecision.NO_TRADE:
            rejections.append(
                RiskRejection(
                    code="NO_TRADE",
                    message="AI decision is NO_TRADE",
                    rule="decision",
                )
            )
        if market.stale:
            rejections.append(
                RiskRejection(
                    code="STALE_MARKET",
                    message="Market data is stale",
                    rule="market_freshness",
                )
            )
        if analysis.confidence < limits.min_confidence:
            rejections.append(
                RiskRejection(
                    code="LOW_CONFIDENCE",
                    message=f"Confidence {analysis.confidence} < {limits.min_confidence}",
                    rule="min_confidence",
                )
            )
        if market.liquidity_usd < limits.min_liquidity_usd:
            rejections.append(
                RiskRejection(
                    code="LOW_LIQUIDITY",
                    message=f"Liquidity {market.liquidity_usd} < {limits.min_liquidity_usd}",
                    rule="min_liquidity",
                )
            )
        if estimated_gas_usd > limits.max_gas_usd:
            rejections.append(
                RiskRejection(
                    code="GAS_TOO_HIGH",
                    message=f"Gas {estimated_gas_usd} > {limits.max_gas_usd}",
                    rule="max_gas",
                )
            )

        # Price deviation vs AI entry
        if analysis.entry_price > 0:
            deviation = abs(market.price - analysis.entry_price) / analysis.entry_price
            max_dev = limits.max_slippage_bps / 10_000 * 2
            if deviation > max_dev:
                rejections.append(
                    RiskRejection(
                        code="PRICE_DEVIATION",
                        message=f"Market vs entry deviation {deviation:.4%}",
                        rule="price_sanity",
                    )
                )

        portfolio = await PortfolioDoc.find_one({"key": "singleton"})
        if not portfolio:
            rejections.append(
                RiskRejection(
                    code="NO_PORTFOLIO",
                    message="Portfolio not initialized",
                    rule="portfolio",
                )
            )
            return RiskEvaluationResult(allowed=False, rejections=rejections)

        # Daily loss / trade count reset
        now = datetime.now(timezone.utc)
        if portfolio.daily_pnl_reset_at.date() != now.date():
            portfolio.daily_pnl_usd = 0.0
            portfolio.daily_pnl_reset_at = now
            await portfolio.save()

        if portfolio.daily_pnl_usd <= -abs(limits.max_daily_loss_usd):
            rejections.append(
                RiskRejection(
                    code="MAX_DAILY_LOSS",
                    message=f"Daily PnL {portfolio.daily_pnl_usd} hit limit",
                    rule="max_daily_loss",
                )
            )

        start_of_day = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
        trades_today = await OrderDoc.find(
            {
                "created_at": {"$gte": start_of_day},
                "status": OrderStatus.FILLED,
            }
        ).count()
        if trades_today >= limits.max_trades_per_day:
            rejections.append(
                RiskRejection(
                    code="MAX_TRADES",
                    message=f"Trades today {trades_today} >= {limits.max_trades_per_day}",
                    rule="max_trades_per_day",
                )
            )

        open_positions = await PositionDoc.find({"status": PositionStatus.OPEN}).to_list()
        if len(open_positions) >= limits.max_open_positions:
            rejections.append(
                RiskRejection(
                    code="MAX_POSITIONS",
                    message="Max open positions reached",
                    rule="max_open_positions",
                )
            )

        if any(p.symbol == analysis.symbol for p in open_positions):
            if analysis.decision == TradeDecision.BUY:
                rejections.append(
                    RiskRejection(
                        code="DUPLICATE_POSITION",
                        message=f"Already open on {analysis.symbol}",
                        rule="one_position_per_symbol",
                    )
                )

        total_value = portfolio.available_balance_usd + portfolio.invested_usd
        size_usd = min(limits.max_position_size_usd, portfolio.available_balance_usd * 0.25)
        if size_usd <= 0:
            rejections.append(
                RiskRejection(
                    code="INSUFFICIENT_BALANCE",
                    message="No available balance",
                    rule="balance",
                )
            )

        projected_exposure = (
            ((portfolio.invested_usd + size_usd) / total_value * 100) if total_value > 0 else 100
        )
        if projected_exposure > limits.max_portfolio_exposure_pct:
            rejections.append(
                RiskRejection(
                    code="MAX_EXPOSURE",
                    message=f"Exposure {projected_exposure:.1f}% > {limits.max_portfolio_exposure_pct}%",
                    rule="max_portfolio_exposure",
                )
            )

        # Enforce deterministic TP/SL percentages relative to market
        if analysis.decision == TradeDecision.BUY:
            adj_tp = market.price * (1 + limits.take_profit_pct / 100)
            adj_sl = market.price * (1 - limits.stop_loss_pct / 100)
        else:
            adj_tp = analysis.take_profit
            adj_sl = analysis.stop_loss

        allowed = len(rejections) == 0
        result = RiskEvaluationResult(
            allowed=allowed,
            rejections=rejections,
            adjusted_size_usd=round(size_usd, 2) if allowed else None,
            adjusted_take_profit=round(adj_tp, 8) if allowed else None,
            adjusted_stop_loss=round(adj_sl, 8) if allowed else None,
        )
        logger.info(
            "risk_evaluated",
            symbol=analysis.symbol,
            allowed=allowed,
            rejections=[r.code for r in rejections],
        )
        return result
