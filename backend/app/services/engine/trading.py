"""
Trading engine orchestrator:

Market Data → Strategy/AI Analysis → Risk Engine → Trade Executor → Position Manager

AI never bypasses deterministic risk controls.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.core.enums import BotStatus, SignalStatus, TradeDecision, TradingMode
from app.core.logging import get_logger
from app.models.documents import BotStateDoc, SignalDoc
from app.models.schemas import AiAnalysis
from app.services.ai.analyzer import AiAnalyzer
from app.services.audit.service import write_audit
from app.services.circuit.breaker import CircuitBreaker
from app.services.dex.base import DexClient, DexQuoteRequest, signal_fingerprint
from app.services.executor.service import TradeExecutor
from app.services.market.service import MarketDataService
from app.services.position.manager import PositionManager
from app.services.risk.engine import RiskEngine

logger = get_logger(__name__)


class TradingEngine:
    def __init__(
        self,
        dex: DexClient,
        market: MarketDataService,
        ai: AiAnalyzer,
        risk: RiskEngine,
        executor: TradeExecutor,
        positions: PositionManager,
        circuit: CircuitBreaker,
    ) -> None:
        self.dex = dex
        self.market = market
        self.ai = ai
        self.risk = risk
        self.executor = executor
        self.positions = positions
        self.circuit = circuit
        self._running_cycle = False

    async def run_cycle(self) -> dict:
        if self._running_cycle:
            return {"skipped": True, "reason": "cycle_in_progress"}
        self._running_cycle = True
        try:
            return await self._run_cycle()
        finally:
            self._running_cycle = False

    async def _run_cycle(self) -> dict:
        bot = await BotStateDoc.find_one({"key": "singleton"})
        if not bot:
            return {"error": "bot_state_missing"}

        if bot.kill_switch:
            return {"skipped": True, "reason": "kill_switch"}
        if bot.status not in {BotStatus.RUNNING, BotStatus.STARTING}:
            return {"skipped": True, "reason": f"status_{bot.status.value}"}
        if bot.paused:
            return {"skipped": True, "reason": "paused"}

        # 1) Market data
        snapshots = await self.market.fetch_and_store()
        markets = {s.symbol: s for s in snapshots}

        # Circuit breaker
        open_cb, cb_reason = await self.circuit.evaluate(snapshots, bot.risk_limits)
        if open_cb:
            return {"skipped": True, "reason": "circuit_breaker", "detail": cb_reason}

        # Mark MTM + exits
        await self.positions.mark_to_market(markets)
        closed = await self.positions.check_exits(
            markets, bot.risk_limits.max_slippage_bps
        )

        signals_created = 0
        executed = 0
        pending_approval = 0
        rejected = 0

        for snap in snapshots:
            if snap.stale:
                continue
            history = await self.market.history(snap.symbol, limit=50)

            # 2) AI analysis (structured)
            analysis = await self.ai.analyze(snap, history)
            # Stable fingerprint for NO_TRADE so we keep one record per window
            if analysis.decision == TradeDecision.NO_TRADE:
                fp = signal_fingerprint(analysis.symbol, "NO_TRADE", 1.0, 1.0, 1.0)
            else:
                fp = signal_fingerprint(
                    analysis.symbol,
                    analysis.decision.value,
                    analysis.entry_price,
                    analysis.take_profit,
                    analysis.stop_loss,
                )
            existing = await SignalDoc.find_one({"fingerprint": fp})
            if existing:
                continue

            if analysis.decision == TradeDecision.NO_TRADE:
                await SignalDoc(
                    symbol=analysis.symbol,
                    decision=analysis.decision,
                    status=SignalStatus.EXPIRED,
                    confidence=analysis.confidence,
                    risk_level=analysis.risk_level,
                    entry_price=analysis.entry_price,
                    take_profit=analysis.take_profit,
                    stop_loss=analysis.stop_loss,
                    reasoning_summary=analysis.reasoning_summary,
                    invalidation_condition=analysis.invalidation_condition,
                    fingerprint=fp,
                    analysis=analysis.model_dump(mode="json"),
                ).insert()
                signals_created += 1
                continue

            signal = SignalDoc(
                symbol=analysis.symbol,
                decision=analysis.decision,
                status=SignalStatus.NEW,
                confidence=analysis.confidence,
                risk_level=analysis.risk_level,
                entry_price=analysis.entry_price,
                take_profit=analysis.take_profit,
                stop_loss=analysis.stop_loss,
                reasoning_summary=analysis.reasoning_summary,
                invalidation_condition=analysis.invalidation_condition,
                fingerprint=fp,
                analysis=analysis.model_dump(mode="json"),
            )
            await signal.insert()
            signals_created += 1

            # Quote for gas estimate
            quote = await self.dex.quote(
                DexQuoteRequest(
                    symbol=snap.symbol,
                    side="BUY" if analysis.decision == TradeDecision.BUY else "SELL",
                    amount_usd=bot.risk_limits.max_position_size_usd,
                    slippage_bps=bot.risk_limits.max_slippage_bps,
                )
            )

            # 3) Deterministic risk
            risk_result = await self.risk.evaluate(
                analysis,
                snap,
                bot.risk_limits,
                kill_switch=bot.kill_switch,
                circuit_open=bot.circuit_breaker_open,
                estimated_gas_usd=quote.estimated_gas_usd,
            )

            if not risk_result.allowed:
                signal.status = SignalStatus.RISK_REJECTED
                signal.risk_rejections = [r.model_dump() for r in risk_result.rejections]
                signal.updated_at = datetime.now(timezone.utc)
                await signal.save()
                rejected += 1
                await write_audit(
                    "SIGNAL_RISK_REJECTED",
                    "engine",
                    "signal",
                    str(signal.id),
                    {"rejections": signal.risk_rejections},
                )
                continue

            signal.status = SignalStatus.VALIDATED
            await signal.save()

            # 4) Mode routing
            if bot.mode == TradingMode.MANUAL_APPROVAL:
                signal.status = SignalStatus.PENDING_APPROVAL
                await signal.save()
                pending_approval += 1
                await write_audit(
                    "SIGNAL_PENDING_APPROVAL",
                    "engine",
                    "signal",
                    str(signal.id),
                    {"symbol": signal.symbol, "decision": signal.decision.value},
                )
                continue

            # PAPER and AUTO both execute through executor;
            # paper DEX simulates fills; live DEX uses server-side keys only.
            if bot.mode in {TradingMode.PAPER, TradingMode.AUTO}:
                order = await self.executor.execute_entry(
                    signal,
                    analysis,
                    risk_result,
                    bot.risk_limits.max_slippage_bps,
                    actor="engine",
                )
                if order and order.status.value == "FILLED":
                    executed += 1
                elif order and order.status.value == "FAILED":
                    self.circuit.record_failure()

        bot.last_cycle_at = datetime.now(timezone.utc)
        bot.status = BotStatus.RUNNING
        bot.updated_at = bot.last_cycle_at
        await bot.save()

        summary = {
            "signals_created": signals_created,
            "executed": executed,
            "pending_approval": pending_approval,
            "rejected": rejected,
            "positions_closed": len(closed),
            "markets": len(snapshots),
            "mode": bot.mode.value,
        }
        logger.info("engine_cycle_complete", **summary)
        return summary

    async def approve_signal(self, signal_id: str, approve: bool, actor: str) -> SignalDoc:
        signal = await SignalDoc.get(signal_id)
        if not signal:
            raise ValueError("Signal not found")
        if signal.status != SignalStatus.PENDING_APPROVAL:
            raise ValueError(f"Signal not pending approval: {signal.status}")

        bot = await BotStateDoc.find_one({"key": "singleton"})
        if not bot:
            raise ValueError("Bot state missing")
        if bot.kill_switch:
            raise ValueError("Kill switch active")

        if not approve:
            signal.status = SignalStatus.EXPIRED
            signal.updated_at = datetime.now(timezone.utc)
            await signal.save()
            await write_audit("SIGNAL_REJECTED_BY_USER", actor, "signal", signal_id, {})
            return signal

        analysis = AiAnalysis.model_validate(signal.analysis)
        market = await self.market.latest(signal.symbol)
        if not market:
            raise ValueError("No market data")

        quote = await self.dex.quote(
            DexQuoteRequest(
                symbol=signal.symbol,
                side="BUY" if analysis.decision == TradeDecision.BUY else "SELL",
                amount_usd=bot.risk_limits.max_position_size_usd,
                slippage_bps=bot.risk_limits.max_slippage_bps,
            )
        )
        risk_result = await self.risk.evaluate(
            analysis,
            market,
            bot.risk_limits,
            kill_switch=bot.kill_switch,
            circuit_open=bot.circuit_breaker_open,
            estimated_gas_usd=quote.estimated_gas_usd,
        )
        if not risk_result.allowed:
            signal.status = SignalStatus.RISK_REJECTED
            signal.risk_rejections = [r.model_dump() for r in risk_result.rejections]
            await signal.save()
            raise ValueError(f"Risk rejected: {[r.code for r in risk_result.rejections]}")

        signal.status = SignalStatus.APPROVED
        await signal.save()
        await self.executor.execute_entry(
            signal,
            analysis,
            risk_result,
            bot.risk_limits.max_slippage_bps,
            actor=actor,
        )
        await write_audit("SIGNAL_APPROVED", actor, "signal", signal_id, {})
        refreshed = await SignalDoc.get(signal_id)
        assert refreshed is not None
        return refreshed
