"""Unit tests for WhatsApp phone normalization and message formatting."""

from __future__ import annotations

from app.services.notify.whatsapp import format_message, normalize_phone


def test_normalize_indian_10_digit():
    assert normalize_phone("6206240867") == "+916206240867"


def test_normalize_already_e164():
    assert normalize_phone("+916206240867") == "+916206240867"


def test_format_message_includes_action():
    msg = format_message("ORDER_FILLED", {"symbol": "BTCUSD", "tx_hash": "delta_123"})
    assert "ORDER FILLED" in msg or "ORDER_FILLED" in msg.replace("_", " ")
    assert "BTCUSD" in msg
    assert "delta_123" in msg
