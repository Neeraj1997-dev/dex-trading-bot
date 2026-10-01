"""Unit tests for trading chat replies that do not call OpenAI."""

from __future__ import annotations

from app.services.chat.service import local_reply


def _context():
    return {
        "markets": [
            {"symbol": "XAUTUSD", "name": "Gold", "price": 4288.5, "change_pct": -0.03, "stale": False},
            {"symbol": "BTCUSD", "name": "Bitcoin", "price": 84400.0, "change_pct": 0.6, "stale": False},
            {"symbol": "ETHUSD", "name": "Ethereum", "price": 2706.0, "change_pct": 0.4, "stale": False},
        ],
        "portfolio": {"available_usd": 100000, "invested_usd": 0, "unrealized_usd": 0},
        "positions": [],
        "bot": {"status": "STOPPED", "mode": "PAPER"},
        "agent": {"step": "IDLE", "detail": "Waiting"},
    }


def test_gold_price_uses_live_context():
    text = local_reply("what is the gold price", _context())
    assert "XAUTUSD" in text
    assert "4,288.50" in text


def test_chat_refuses_to_place_orders():
    text = local_reply("buy bitcoin now", _context())
    assert "cannot place orders" in text
    assert "risk engine" in text


def test_empty_positions():
    assert local_reply("any open positions?", _context()) == "No open positions."
