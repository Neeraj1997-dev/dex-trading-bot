"""Trade execution — records every request/response/tx hash."""

from __future__ import annotations

from typing import Optional

from datetime import datetime, timezone

from app.core.enums import OrderSide, OrderStatus, OrderType, PositionStatus, SignalStatus
from app.core.logging import get_logger
from app.models.documents import OrderDoc, PortfolioDoc, PositionDoc, SignalDoc
from app.models.schemas import AiAnalysis, RiskEvaluationResult
from app.services.audit.service import write_audit
from app.services.dex.base import DexClient, DexOrderRequest

logger = get_logger(__name__)


class TradeExecutor:
    def __init__(self, dex: DexClient) -> None:
        self.dex = dex

    async def execute_entry(
        self,
        signal: SignalDoc,
        analysis: AiAnalysis,
        risk: RiskEvaluationResult,
        slippage_bps: int,
        actor: str = "engine",
    ) -> Optional[OrderDoc]:
        if not risk.allowed or risk.adjusted_size_usd is None:
            return None

        size_usd = risk.adjusted_size_usd
        side = OrderSide.BUY if analysis.decision.value == "BUY" else OrderSide.SELL
        client_order_id = f"sig_{signal.id}"

        # Prevent duplicate execution of same signal
        existing = await OrderDoc.find_one({"signal_id": str(signal.id)})
        if existing and existing.status in {
            OrderStatus.SUBMITTED,
            OrderStatus.FILLED,
            OrderStatus.PARTIAL,
        }:
            logger.warning("duplicate_order_blocked", signal_id=str(signal.id))
            return existing

        order = OrderDoc(
            signal_id=str(signal.id),
            symbol=analysis.symbol,
            side=side,
            type=OrderType.MARKET,
            status=OrderStatus.SUBMITTED,
            requested_price=analysis.entry_price,
            size=0.0,
            size_usd=size_usd,
            slippage_bps=slippage_bps,
            request_payload={
                "symbol": analysis.symbol,
                "side": side.value,
                "size_usd": size_usd,
                "slippage_bps": slippage_bps,
            },
        )
        await order.insert()

        result = await self.dex.execute(
            DexOrderRequest(
                symbol=analysis.symbol,
                side=side.value,  # type: ignore[arg-type]
                amount_usd=size_usd,
                slippage_bps=slippage_bps,
                expected_price=analysis.entry_price,
                client_order_id=client_order_id,
            )
        )

        order.response_payload = result.raw_response
        order.request_payload = result.raw_request
        order.tx_hash = result.tx_hash
        order.fees_usd = result.fees_usd
        order.gas_usd = result.gas_usd
        order.updated_at = datetime.now(timezone.utc)

        if not result.success or result.filled_price is None or result.filled_size is None:
            order.status = OrderStatus.FAILED
            order.failure_reason = result.error or "execution_failed"
            await order.save()
            await write_audit(
                "ORDER_FAILED",
                actor,
                "order",
                str(order.id),
                {"error": order.failure_reason, "tx_hash": result.tx_hash},
            )
            return order

        order.status = OrderStatus.FILLED if result.status == "FILLED" else OrderStatus.PARTIAL
        order.filled_price = result.filled_price
        order.size = result.filled_size
        await order.save()

        take_profit = risk.adjusted_take_profit or analysis.take_profit
        stop_loss = risk.adjusted_stop_loss or analysis.stop_loss

        position = PositionDoc(
            symbol=analysis.symbol,
            side=side,
            status=PositionStatus.OPEN,
            entry_price=result.filled_price,
            current_price=result.filled_price,
            size=result.filled_size,
            size_usd=size_usd,
            take_profit=take_profit,
            stop_loss=stop_loss,
            fees_usd=result.fees_usd,
            gas_usd=result.gas_usd,
            entry_tx_hash=result.tx_hash,
        )
        await position.insert()
        order.position_id = str(position.id)
        await order.save()

        portfolio = await PortfolioDoc.find_one({"key": "singleton"})
        if portfolio:
            cost = size_usd + result.fees_usd + result.gas_usd
            portfolio.available_balance_usd = max(0.0, portfolio.available_balance_usd - cost)
            portfolio.invested_usd += size_usd
            portfolio.total_trades += 1
            portfolio.updated_at = datetime.now(timezone.utc)
            await portfolio.save()

        signal.status = SignalStatus.EXECUTED
        signal.updated_at = datetime.now(timezone.utc)
        await signal.save()

        await write_audit(
            "ORDER_FILLED",
            actor,
            "order",
            str(order.id),
            {
                "symbol": analysis.symbol,
                "tx_hash": result.tx_hash,
                "filled_price": result.filled_price,
                "size_usd": size_usd,
                "position_id": str(position.id),
            },
        )
        logger.info("order_filled", order_id=str(order.id), tx_hash=result.tx_hash)
        return order
