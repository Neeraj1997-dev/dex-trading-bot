"""OpenAI structured market analysis — never receives secrets or keys."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from openai import AsyncOpenAI
from pydantic import ValidationError

from app.core.config import Settings
from app.core.enums import ConnectionHealth, RiskLevel, TradeDecision
from app.core.logging import get_logger
from app.models.schemas import AiAnalysis, MarketSnapshot

logger = get_logger(__name__)

SYSTEM_PROMPT = """You are a quantitative market analyst for a DEX trading system.
Return ONLY valid JSON matching the required schema. Do not include markdown.
Never invent wallet addresses, private keys, or credentials.
Be conservative: prefer NO_TRADE when data is weak, stale, or risk is high.
For BUY: take_profit > entry_price > stop_loss.
For SELL (short/exit bias): stop_loss > entry_price > take_profit when applicable,
otherwise use NO_TRADE if unsure.
"""


class AiAnalyzer:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client: Optional[AsyncOpenAI] = None
        if settings.openai_api_key:
            kwargs: Dict[str, Any] = {"api_key": settings.openai_api_key}
            if settings.openai_base_url:
                kwargs["base_url"] = settings.openai_base_url
            self._client = AsyncOpenAI(**kwargs)

    async def health(self) -> ConnectionHealth:
        if not self._client:
            return ConnectionHealth.DISCONNECTED
        return ConnectionHealth.CONNECTED

    def _heuristic(self, market: MarketSnapshot, history: List[MarketSnapshot]) -> AiAnalysis:
        """Deterministic offline baseline when OpenAI is unavailable.

        Mild positive 24h change with real liquidity is a valid paper BUY.
        Confidence is kept above the default risk floor (60) so the signal
        can reach the risk engine instead of dying as an unvalidated idea.
        """
        change = market.price_change_24h_pct
        decision = TradeDecision.NO_TRADE
        confidence = 45.0
        liquid = market.liquidity_usd >= 50_000
        if change >= 0.2 and liquid and not market.stale:
            decision = TradeDecision.BUY
            confidence = min(85.0, 64.0 + abs(change))
        elif change <= -1.5 and liquid:
            decision = TradeDecision.NO_TRADE
            confidence = 58.0

        entry = market.price
        tp = entry * 1.06
        sl = entry * 0.97
        return AiAnalysis(
            decision=decision,
            symbol=market.symbol,
            entry_price=round(entry, 6),
            take_profit=round(tp, 6),
            stop_loss=round(sl, 6),
            confidence=confidence,
            risk_level=RiskLevel.MEDIUM if abs(change) > 3 else RiskLevel.LOW,
            reasoning_summary=(
                f"Heuristic analysis: 24h change {change:.2f}%, "
                f"liquidity ${market.liquidity_usd:,.0f}, source={market.source}"
            ),
            invalidation_condition=f"Price closes below {sl:.6f} or liquidity collapses",
            market_trend="BULLISH" if change > 1 else "BEARISH" if change < -1 else "SIDEWAYS",
            momentum="STRONG" if abs(change) > 4 else "MODERATE" if abs(change) > 1.5 else "WEAK",
            volatility="HIGH" if abs(change) > 5 else "MEDIUM" if abs(change) > 2 else "LOW",
            support=round(entry * 0.97, 6),
            resistance=round(entry * 1.05, 6),
        )

    async def analyze(
        self,
        market: MarketSnapshot,
        history: Optional[List[MarketSnapshot]] = None,
    ) -> AiAnalysis:
        history = history or []
        if not self._client:
            logger.warning("openai_unavailable_using_heuristic", symbol=market.symbol)
            return self._heuristic(market, history)

        hist_payload = [
            {
                "price": h.price,
                "volume_24h": h.volume_24h,
                "liquidity_usd": h.liquidity_usd,
                "price_change_24h_pct": h.price_change_24h_pct,
                "timestamp": h.timestamp.isoformat(),
            }
            for h in history[-50:]
        ]
        user_payload = {
            "market": market.model_dump(mode="json"),
            "history": hist_payload,
            "required_schema": {
                "decision": "BUY|SELL|NO_TRADE",
                "symbol": market.symbol,
                "entry_price": "number",
                "take_profit": "number",
                "stop_loss": "number",
                "confidence": "0-100",
                "risk_level": "LOW|MEDIUM|HIGH",
                "reasoning_summary": "string",
                "invalidation_condition": "string",
                "market_trend": "BULLISH|BEARISH|SIDEWAYS",
                "momentum": "STRONG|MODERATE|WEAK",
                "volatility": "LOW|MEDIUM|HIGH",
                "support": "number",
                "resistance": "number",
            },
        }

        try:
            response = await self._client.chat.completions.create(
                model=self.settings.openai_model,
                temperature=0.1,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": (
                            "Analyze this DEX market data and return structured JSON only:\n"
                            + json.dumps(user_payload)
                        ),
                    },
                ],
            )
            content = response.choices[0].message.content or "{}"
            # Never send secrets; only validate structured analysis
            data = json.loads(content)
            data["symbol"] = market.symbol  # force known symbol
            analysis = AiAnalysis.model_validate(data)
            analysis = self._validate_price_logic(analysis)
            return analysis
        except (ValidationError, json.JSONDecodeError, Exception) as exc:
            logger.error("openai_analysis_failed", error=str(exc), symbol=market.symbol)
            # Fail closed toward NO_TRADE via heuristic with low confidence
            fallback = self._heuristic(market, history)
            fallback.decision = TradeDecision.NO_TRADE
            fallback.confidence = min(fallback.confidence, 30)
            fallback.reasoning_summary = f"AI validation failed ({exc}); defaulting to NO_TRADE"
            return fallback

    def _validate_price_logic(self, analysis: AiAnalysis) -> AiAnalysis:
        if analysis.decision == TradeDecision.BUY:
            if not (analysis.take_profit > analysis.entry_price > analysis.stop_loss):
                raise ValueError("BUY requires TP > entry > SL")
        return analysis
