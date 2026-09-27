"""WhatsApp trade notifications.

Supports:
  - twilio   — Twilio WhatsApp API
  - meta     — Meta WhatsApp Cloud API
  - callmebot — personal CallMeBot (simple setup)

Phone numbers are stored server-side only (never sent to OpenAI/frontend secrets).
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Set
from urllib.parse import quote

import httpx

from app.core.config import Settings, get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# Events that trigger WhatsApp alerts
NOTIFY_ACTIONS: Set[str] = {
    "BOT_START",
    "BOT_STOP",
    "BOT_PAUSE",
    "BOT_RESUME",
    "BOT_KILL_SWITCH",
    "BOT_RESET_KILL_SWITCH",
    "BOT_MODE_CHANGE",
    "ORDER_FILLED",
    "ORDER_FAILED",
    "POSITION_CLOSED",
    "EXIT_FAILED",
    "SIGNAL_PENDING_APPROVAL",
    "SIGNAL_APPROVED",
    "SIGNAL_REJECTED_BY_USER",
    "SIGNAL_RISK_REJECTED",
    "CIRCUIT_BREAKER_OPEN",
    "CIRCUIT_BREAKER_RESET",
}


def normalize_phone(raw: str) -> str:
    """Normalize to E.164. Bare 10-digit Indian numbers get +91."""
    digits = "".join(c for c in raw if c.isdigit())
    if raw.strip().startswith("+"):
        return "+" + digits
    if len(digits) == 10:
        return f"+91{digits}"
    if digits.startswith("91") and len(digits) == 12:
        return f"+{digits}"
    return f"+{digits}" if digits else raw


def format_message(action: str, details: Optional[Dict[str, Any]] = None) -> str:
    details = details or {}
    lines = [
        "Delta Trading Alert",
        f"Event: {action.replace('_', ' ')}",
    ]
    for key in (
        "symbol",
        "decision",
        "status",
        "mode",
        "tx_hash",
        "filled_price",
        "size_usd",
        "pnl",
        "reason",
        "error",
        "rejections",
    ):
        if key in details and details[key] not in (None, "", [], {}):
            val = details[key]
            if isinstance(val, list):
                val = ", ".join(str(x) for x in val[:5])
            lines.append(f"{key}: {val}")
    return "\n".join(lines)


class WhatsAppNotifier:
    def __init__(self, settings: Optional[Settings] = None) -> None:
        self.settings = settings or get_settings()

    @property
    def enabled(self) -> bool:
        return bool(self.settings.whatsapp_enabled and self.settings.whatsapp_to)

    async def send(self, text: str, to: Optional[str] = None) -> bool:
        if not self.settings.whatsapp_enabled:
            logger.info("whatsapp_skipped_disabled")
            return False
        phone = normalize_phone(to or self.settings.whatsapp_to or "")
        if not phone:
            logger.warning("whatsapp_no_recipient")
            return False

        provider = (self.settings.whatsapp_provider or "twilio").lower()
        try:
            if provider == "meta":
                ok = await self._send_meta(phone, text)
            elif provider == "callmebot":
                ok = await self._send_callmebot(phone, text)
            else:
                ok = await self._send_twilio(phone, text)
            if ok:
                logger.info("whatsapp_sent", provider=provider, to=phone[-4:].rjust(len(phone), "*"))
            return ok
        except Exception as exc:
            logger.error("whatsapp_send_failed", provider=provider, error=str(exc))
            return False

    async def notify_action(
        self,
        action: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> bool:
        if action not in NOTIFY_ACTIONS:
            return False
        return await self.send(format_message(action, details))

    async def _send_twilio(self, phone: str, text: str) -> bool:
        sid = self.settings.twilio_account_sid
        token = self.settings.twilio_auth_token
        from_wa = self.settings.twilio_whatsapp_from
        if not sid or not token or not from_wa:
            logger.warning("whatsapp_twilio_not_configured")
            return False
        url = f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"
        data = {
            "From": from_wa if from_wa.startswith("whatsapp:") else f"whatsapp:{from_wa}",
            "To": f"whatsapp:{phone}",
            "Body": text,
        }
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(url, data=data, auth=(sid, token))
            if resp.status_code >= 400:
                logger.error("twilio_error", status=resp.status_code, body=resp.text[:300])
                return False
            return True

    async def _send_meta(self, phone: str, text: str) -> bool:
        token = self.settings.whatsapp_meta_token
        phone_id = self.settings.whatsapp_meta_phone_id
        if not token or not phone_id:
            logger.warning("whatsapp_meta_not_configured")
            return False
        # Meta expects digits only for `to`
        to_digits = "".join(c for c in phone if c.isdigit())
        url = f"https://graph.facebook.com/v19.0/{phone_id}/messages"
        payload = {
            "messaging_product": "whatsapp",
            "to": to_digits,
            "type": "text",
            "text": {"body": text[:4096]},
        }
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
            if resp.status_code >= 400:
                logger.error("meta_whatsapp_error", status=resp.status_code, body=resp.text[:300])
                return False
            return True

    async def _send_callmebot(self, phone: str, text: str) -> bool:
        apikey = self.settings.callmebot_apikey
        if not apikey:
            logger.warning("whatsapp_callmebot_not_configured")
            return False
        to_digits = "".join(c for c in phone if c.isdigit())
        url = (
            "https://api.callmebot.com/whatsapp.php"
            f"?phone={to_digits}&text={quote(text)}&apikey={quote(apikey)}"
        )
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(url)
            if resp.status_code >= 400:
                logger.error("callmebot_error", status=resp.status_code, body=resp.text[:300])
                return False
            return True


_notifier: Optional[WhatsAppNotifier] = None


def get_notifier() -> WhatsAppNotifier:
    global _notifier
    if _notifier is None:
        _notifier = WhatsAppNotifier()
    return _notifier
