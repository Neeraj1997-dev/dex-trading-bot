"""Unit tests for risk engine and AI schema validation."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.enums import RiskLevel, TradeDecision
from app.models.schemas import AiAnalysis, MarketSnapshot, RiskLimits
from app.services.risk.engine import RiskEngine


def sample_limits(**overrides):
    base = dict(
        max_position_size_usd=1000,
        max_daily_loss_usd=500,
        max_trades_per_day=20,
        max_portfolio_exposure_pct=50,
        stop_loss_pct=3,
        take_profit_pct=6,
        max_slippage_bps=100,
        min_liquidity_usd=50_000,
        max_gas_usd=25,
        min_confidence=60,
        max_open_positions=5,
    )
    base.update(overrides)
    return RiskLimits(**base)


def sample_market(**overrides):
    base = dict(
        symbol="ETH/USDC",
        price=3200.0,
        volume_24h=1_000_000,
        liquidity_usd=500_000,
        price_change_24h_pct=2.5,
        timestamp=datetime.now(timezone.utc),
        source="paper",
        stale=False,
    )
    base.update(overrides)
    return MarketSnapshot(**base)


def sample_analysis(**overrides):
    base = dict(
        decision=TradeDecision.BUY,
        symbol="ETH/USDC",
        entry_price=3200.0,
        take_profit=3392.0,
        stop_loss=3104.0,
        confidence=70,
        risk_level=RiskLevel.LOW,
        reasoning_summary="Test bullish setup",
        invalidation_condition="Break below support",
    )
    base.update(overrides)
    return AiAnalysis(**base)


def _portfolio_mock():
    portfolio = AsyncMock()
    portfolio.available_balance_usd = 100_000
    portfolio.invested_usd = 0
    portfolio.daily_pnl_usd = 0
    portfolio.daily_pnl_reset_at = datetime.now(timezone.utc)
    portfolio.save = AsyncMock()
    return portfolio


def _patch_db(portfolio):
    order_query = MagicMock()
    order_query.count = AsyncMock(return_value=0)
    position_query = MagicMock()
    position_query.to_list = AsyncMock(return_value=[])
    return (
        patch(
            "app.services.risk.engine.PortfolioDoc.find_one",
            new=AsyncMock(return_value=portfolio),
        ),
        patch("app.services.risk.engine.OrderDoc.find", return_value=order_query),
        patch("app.services.risk.engine.PositionDoc.find", return_value=position_query),
    )


@pytest.mark.asyncio
async def test_kill_switch_blocks_trade():
    engine = RiskEngine()
    portfolio = _portfolio_mock()
    p1, p2, p3 = _patch_db(portfolio)
    with p1, p2, p3:
        result = await engine.evaluate(
            sample_analysis(),
            sample_market(),
            sample_limits(),
            kill_switch=True,
            circuit_open=False,
            estimated_gas_usd=5,
        )
        assert result.allowed is False
        assert any(r.code == "KILL_SWITCH" for r in result.rejections)


@pytest.mark.asyncio
async def test_low_confidence_rejected():
    engine = RiskEngine()
    portfolio = _portfolio_mock()
    p1, p2, p3 = _patch_db(portfolio)
    with p1, p2, p3:
        result = await engine.evaluate(
            sample_analysis(confidence=40),
            sample_market(),
            sample_limits(min_confidence=60),
            kill_switch=False,
            circuit_open=False,
            estimated_gas_usd=5,
        )
        assert result.allowed is False
        assert any(r.code == "LOW_CONFIDENCE" for r in result.rejections)


@pytest.mark.asyncio
async def test_stale_market_rejected():
    engine = RiskEngine()
    portfolio = _portfolio_mock()
    p1, p2, p3 = _patch_db(portfolio)
    with p1, p2, p3:
        result = await engine.evaluate(
            sample_analysis(),
            sample_market(stale=True),
            sample_limits(),
            kill_switch=False,
            circuit_open=False,
            estimated_gas_usd=5,
        )
        assert any(r.code == "STALE_MARKET" for r in result.rejections)


def test_ai_analysis_schema_buy_levels():
    a = sample_analysis()
    assert a.take_profit > a.entry_price > a.stop_loss


def test_ai_analysis_rejects_bad_confidence():
    with pytest.raises(Exception):
        sample_analysis(confidence=150)


@pytest.mark.asyncio
async def test_paper_dex_execute_fill():
    from app.services.dex.base import DexOrderRequest
    from app.services.dex.paper import PaperDexClient

    client = PaperDexClient()
    market = await client.get_market("ETH/USDC")
    result = await client.execute(
        DexOrderRequest(
            symbol="ETH/USDC",
            side="BUY",
            amount_usd=1000,
            slippage_bps=100,
            expected_price=market.price,
            client_order_id="test-1",
        )
    )
    assert result.success is True
    assert result.tx_hash and result.tx_hash.startswith("paper_")
    assert result.filled_price is not None
