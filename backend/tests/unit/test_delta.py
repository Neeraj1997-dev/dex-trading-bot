"""Tests for Delta Exchange symbol mapping."""

from __future__ import annotations

from app.services.dex.delta import to_delta_symbol


def test_to_delta_symbol_slash_pairs():
    assert to_delta_symbol("ETH/USDC") == "ETHUSD"
    assert to_delta_symbol("BTC/USD") == "BTCUSD"
    assert to_delta_symbol("btc/usdt") == "BTCUSD"


def test_to_delta_symbol_passthrough():
    assert to_delta_symbol("BTCUSD") == "BTCUSD"
    assert to_delta_symbol("ETHUSD") == "ETHUSD"


def test_delta_microsecond_timestamp_is_current():
    from datetime import datetime, timezone

    from app.services.dex.delta import DeltaExchangeClient

    client = DeltaExchangeClient.__new__(DeltaExchangeClient)
    client.name = "delta"
    # ~2026-09-26 in microseconds
    us = int(datetime(2026, 9, 26, tzinfo=timezone.utc).timestamp() * 1_000_000)
    snap = client._snapshot(
        "BTCUSD",
        {
            "mark_price": "84000",
            "mark_change_24h": "0.4",
            "turnover_usd": 1_000_000,
            "volume": 10,
            "time": us,
            "quotes": {"best_bid": "83990", "best_ask": "84010"},
        },
    )
    assert snap.timestamp.year == 2026
    assert snap.stale is False
    assert snap.price_change_24h_pct == 0.4


def test_heuristic_buy_clears_default_confidence():
    from datetime import datetime, timezone

    from app.core.config import Settings
    from app.models.schemas import MarketSnapshot
    from app.services.ai.analyzer import AiAnalyzer

    settings = Settings(
        jwt_secret="change-me-to-a-long-random-secret-key-32+",
        openai_api_key=None,
    )
    analyzer = AiAnalyzer(settings)
    market = MarketSnapshot(
        symbol="BTCUSD",
        price=84000,
        volume_24h=4000,
        liquidity_usd=60_000_000,
        price_change_24h_pct=0.4,
        timestamp=datetime.now(timezone.utc),
        source="delta",
        stale=False,
    )
    analysis = analyzer._heuristic(market, [])
    assert analysis.decision.value == "BUY"
    assert analysis.confidence >= 60
    assert analysis.take_profit > analysis.entry_price > analysis.stop_loss
