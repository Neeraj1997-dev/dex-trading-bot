"""Unit tests for the trading agent summary."""

from __future__ import annotations

from app.services.agent.trader import summarize_cycle


def test_summarize_blocked_cycle():
    text = summarize_cycle({"skipped": True, "reason": "kill_switch"})
    assert text == "Blocked: kill switch"


def test_summarize_successful_cycle():
    text = summarize_cycle(
        {
            "markets": 2,
            "signals_created": 1,
            "executed": 1,
            "rejected": 0,
            "pending_approval": 0,
        }
    )
    assert "Markets 2" in text
    assert "executed 1" in text
