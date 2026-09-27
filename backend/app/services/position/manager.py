"""Position management — mark-to-market and auto TP/SL exits."""

from __future__ import annotations

from typing import Dict, List, Optional

from datetime import datetime, timezone

from app.core.enums import OrderSide, OrderStatus, OrderType, PositionStatus
from app.core.logging import get_logger
from app.models.documents import OrderDoc, PortfolioDoc, PositionDoc, TradeHistoryDoc
from app.models.schemas import MarketSnapshot
from app.services.audit.service import write_audit
from app.services.dex.base import DexClient, DexOrderRequest

logger = get_logger(__name__)


class PositionManager:
    def __init__(self, dex: DexClient) -> None:
        self.dex = dex

    async def mark_to_market(self, markets: Dict[str, MarketSnapshot]) -> None:
        opens = await PositionDoc.find({"status": PositionStatus.OPEN}).to_list()
        for pos in opens:
            m = markets.get(pos.symbol)
            if not m:
                continue
            pos.current_price = m.price
            if pos.side == OrderSide.BUY:
                pos.unrealized_pnl_usd = (m.price - pos.entry_price) * pos.size
            else:
                pos.unrealized_pnl_usd = (pos.entry_price - m.price) * pos.size
            await pos.save()

    async def check_exits(self, markets: Dict[str, MarketSnapshot], slippage_bps: int) -> List[str]:
        closed: List[str] = []
        opens = await PositionDoc.find({"status": PositionStatus.OPEN}).to_list()
        for pos in opens:
            m = markets.get(pos.symbol)
            if not m:
                continue
            reason: Optional[str] = None
            if pos.side == OrderSide.BUY:
                if m.price >= pos.take_profit:
                    reason = "TAKE_PROFIT"
                elif m.price <= pos.stop_loss:
                    reason = "STOP_LOSS"
            else:
                if m.price <= pos.take_profit:
                    reason = "TAKE_PROFIT"
                elif m.price >= pos.stop_loss:
                    reason = "STOP_LOSS"
            if reason:
                await self.close_position(pos, m, reason, slippage_bps)
                closed.append(str(pos.id))
        return closed

    async def close_position(
        self,
        pos: PositionDoc,
        market: MarketSnapshot,
        reason: str,
        slippage_bps: int,
        actor: str = "position_manager",
    ) -> OrderDoc:
        pos.status = PositionStatus.CLOSING
        await pos.save()

        exit_side = OrderSide.SELL if pos.side == OrderSide.BUY else OrderSide.BUY
        amount_usd = pos.size * market.price

        order = OrderDoc(
            position_id=str(pos.id),
            symbol=pos.symbol,
            side=exit_side,
            type=OrderType.MARKET,
            status=OrderStatus.SUBMITTED,
            requested_price=market.price,
            size=pos.size,
            size_usd=amount_usd,
            slippage_bps=slippage_bps,
            request_payload={"reason": reason, "position_id": str(pos.id)},
        )
        await order.insert()

        result = await self.dex.execute(
            DexOrderRequest(
                symbol=pos.symbol,
                side=exit_side.value,  # type: ignore[arg-type]
                amount_usd=amount_usd,
                slippage_bps=slippage_bps,
                expected_price=market.price,
                client_order_id=f"exit_{pos.id}",
            )
        )
        order.response_payload = result.raw_response
        order.tx_hash = result.tx_hash
        order.fees_usd = result.fees_usd
        order.gas_usd = result.gas_usd
        order.updated_at = datetime.now(timezone.utc)

        if not result.success or result.filled_price is None:
            order.status = OrderStatus.FAILED
            order.failure_reason = result.error or "exit_failed"
            await order.save()
            pos.status = PositionStatus.OPEN
            await pos.save()
            await write_audit("EXIT_FAILED", actor, "position", str(pos.id), {"error": order.failure_reason})
            return order

        exit_price = result.filled_price
        if pos.side == OrderSide.BUY:
            pnl = (exit_price - pos.entry_price) * pos.size - result.fees_usd - result.gas_usd
        else:
            pnl = (pos.entry_price - exit_price) * pos.size - result.fees_usd - result.gas_usd

        order.status = OrderStatus.FILLED
        order.filled_price = exit_price
        await order.save()

        pos.status = PositionStatus.CLOSED
        pos.current_price = exit_price
        pos.realized_pnl_usd = pnl
        pos.unrealized_pnl_usd = 0.0
        pos.fees_usd += result.fees_usd
        pos.gas_usd += result.gas_usd
        pos.exit_tx_hash = result.tx_hash
        pos.closed_at = datetime.now(timezone.utc)
        await pos.save()

        portfolio = await PortfolioDoc.find_one({"key": "singleton"})
        if portfolio:
            proceeds = pos.size * exit_price - result.fees_usd - result.gas_usd
            portfolio.available_balance_usd += proceeds
            portfolio.invested_usd = max(0.0, portfolio.invested_usd - pos.size_usd)
            portfolio.realized_pnl_usd += pnl
            portfolio.daily_pnl_usd += pnl
            portfolio.total_trades += 1
            if pnl >= 0:
                portfolio.wins += 1
            else:
                portfolio.losses += 1
            portfolio.updated_at = datetime.now(timezone.utc)
            await portfolio.save()

        await TradeHistoryDoc(
            position_id=str(pos.id),
            order_id=str(order.id),
            symbol=pos.symbol,
            side=pos.side,
            entry_price=pos.entry_price,
            exit_price=exit_price,
            size=pos.size,
            pnl_usd=pnl,
            fees_usd=pos.fees_usd,
            reason=reason,
        ).insert()

        await write_audit(
            "POSITION_CLOSED",
            actor,
            "position",
            str(pos.id),
            {"reason": reason, "pnl": pnl, "tx_hash": result.tx_hash},
        )
        logger.info("position_closed", position_id=str(pos.id), reason=reason, pnl=pnl)
        return order
