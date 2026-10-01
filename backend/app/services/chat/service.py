"""Trading desk chat.

Answers from stored quotes, positions, and agent state. It never places orders.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from openai import AsyncOpenAI

from app.core.config import Settings
from app.core.enums import PositionStatus
from app.core.logging import get_logger
from app.models.documents import (
    AgentStateDoc,
    BotStateDoc,
    ChatMessageDoc,
    MarketSnapshotDoc,
    PortfolioDoc,
    PositionDoc,
)

logger = get_logger(__name__)

MARKET_NAMES = {
    "XAUTUSD": "Gold",
    "BTCUSD": "Bitcoin",
    "ETHUSD": "Ethereum",
}

ALIASES = {
    "gold": "XAUTUSD",
    "xaut": "XAUTUSD",
    "xautusd": "XAUTUSD",
    "btc": "BTCUSD",
    "bitcoin": "BTCUSD",
    "btcusd": "BTCUSD",
    "eth": "ETHUSD",
    "ethereum": "ETHUSD",
    "ethusd": "ETHUSD",
}

SYSTEM_PROMPT = """You are the trading desk assistant for a Delta paper-trading console.
Use only the JSON context. Do not invent prices, balances, or fills.
You cannot place, cancel, or approve orders. If asked to trade, say the operator
must start the bot and that the risk engine still has to approve every order.
Keep answers short and concrete. Mention the symbol when you quote a price.
"""


def _money(value: float) -> str:
    return f"${value:,.2f}"


def _mentioned(text: str) -> List[str]:
    found: List[str] = []
    for alias, symbol in ALIASES.items():
        if alias in text and symbol not in found:
            found.append(symbol)
    return found


def _quote_line(market: Dict[str, Any]) -> str:
    name = market.get("name") or market["symbol"]
    change = market.get("change_pct")
    change_text = f", 24h {change:+.2f}%" if isinstance(change, (int, float)) else ""
    stale = " (stale)" if market.get("stale") else ""
    return f"{name} ({market['symbol']}) {_money(float(market['price']))}{change_text}{stale}"


def local_reply(message: str, context: Dict[str, Any]) -> str:
    text = " ".join(message.lower().split())
    markets = {m["symbol"]: m for m in context.get("markets", [])}
    portfolio = context.get("portfolio") or {}
    positions = context.get("positions") or []
    bot = context.get("bot") or {}
    agent = context.get("agent") or {}

    if any(word in text for word in ("buy", "sell", "short", "long", "place order", "execute", "open a trade")):
        return (
            "Chat cannot place orders. Start the bot from Overview. "
            "Every order still has to pass the risk engine."
        )

    if any(word in text for word in ("portfolio", "balance", "p&l", "pnl", "equity")):
        return (
            f"Available {_money(float(portfolio.get('available_usd', 0)))}, "
            f"invested {_money(float(portfolio.get('invested_usd', 0)))}, "
            f"unrealized {_money(float(portfolio.get('unrealized_usd', 0)))}."
        )

    if "position" in text:
        if not positions:
            return "No open positions."
        lines = [
            f"{p['symbol']} {p['side']} entry {_money(float(p['entry_price']))}, "
            f"P&L {_money(float(p['unrealized_pnl_usd']))}"
            for p in positions
        ]
        return "Open positions: " + "; ".join(lines) + "."

    if any(word in text for word in ("agent", "bot status", "status")):
        return (
            f"Bot is {bot.get('status', 'UNKNOWN')} in {bot.get('mode', 'UNKNOWN')} mode. "
            f"Agent step {agent.get('step', 'IDLE')}: {agent.get('detail', 'waiting')}."
        )

    symbols = _mentioned(text) or (list(markets) if any(word in text for word in ("price", "quote", "market")) else [])
    if symbols:
        lines = []
        for symbol in symbols:
            market = markets.get(symbol)
            lines.append(_quote_line(market) if market else f"{MARKET_NAMES.get(symbol, symbol)} has no stored quote yet.")
        return " ".join(lines)

    if markets:
        brief = " ".join(_quote_line(m) for m in markets.values())
        return f"{brief} Bot is {bot.get('status', 'UNKNOWN')}."
    return "No market quotes are stored yet. Check the Delta connection, then ask again."


class TradingChat:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client: Optional[AsyncOpenAI] = None
        if settings.openai_api_key:
            kwargs: Dict[str, Any] = {"api_key": settings.openai_api_key}
            if settings.openai_base_url:
                kwargs["base_url"] = settings.openai_base_url
            self._client = AsyncOpenAI(**kwargs)

    async def history(self, limit: int = 40) -> List[ChatMessageDoc]:
        docs = await ChatMessageDoc.find_all().sort("-created_at").limit(limit).to_list()
        docs.reverse()
        return docs

    async def reply(self, message: str) -> ChatMessageDoc:
        context = await self._context()
        content = await self._answer(message.strip(), context)
        now = datetime.now(timezone.utc)
        await ChatMessageDoc(role="user", content=message.strip(), created_at=now).insert()
        answer = ChatMessageDoc(role="assistant", content=content, created_at=datetime.now(timezone.utc))
        await answer.insert()
        return answer

    async def _answer(self, message: str, context: Dict[str, Any]) -> str:
        if self._client is None:
            return local_reply(message, context)
        prior = await self.history(limit=8)
        messages: List[Dict[str, str]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "system",
                "content": "Context JSON:\n" + json.dumps(context),
            },
        ]
        for doc in prior:
            if doc.role in {"user", "assistant"}:
                messages.append({"role": doc.role, "content": doc.content})
        messages.append({"role": "user", "content": message})
        try:
            response = await self._client.chat.completions.create(
                model=self.settings.openai_model,
                temperature=0.2,
                messages=messages,
            )
            text = (response.choices[0].message.content or "").strip()
            if text:
                return text[:4000]
        except Exception as exc:
            logger.error("trading_chat_failed", error=str(exc))
        return local_reply(message, context)

    async def _context(self) -> Dict[str, Any]:
        bot = await BotStateDoc.find_one({"key": "singleton"})
        portfolio = await PortfolioDoc.find_one({"key": "singleton"})
        agent = await AgentStateDoc.find_one({"key": "singleton"})
        positions = await PositionDoc.find({"status": PositionStatus.OPEN}).to_list()
        snapshots = await MarketSnapshotDoc.find_all().sort("-timestamp").limit(30).to_list()
        latest: Dict[str, MarketSnapshotDoc] = {}
        for snap in snapshots:
            latest.setdefault(snap.symbol, snap)
        unrealized = sum(p.unrealized_pnl_usd for p in positions)
        return {
            "markets": [
                {
                    "symbol": snap.symbol,
                    "name": MARKET_NAMES.get(snap.symbol, snap.symbol),
                    "price": snap.price,
                    "change_pct": snap.price_change_24h_pct,
                    "stale": snap.stale,
                }
                for snap in latest.values()
            ],
            "portfolio": {
                "available_usd": portfolio.available_balance_usd if portfolio else 0,
                "invested_usd": portfolio.invested_usd if portfolio else 0,
                "unrealized_usd": unrealized,
            },
            "positions": [
                {
                    "symbol": p.symbol,
                    "side": p.side.value,
                    "entry_price": p.entry_price,
                    "unrealized_pnl_usd": p.unrealized_pnl_usd,
                }
                for p in positions
            ],
            "bot": {
                "status": bot.status.value if bot else "UNKNOWN",
                "mode": bot.mode.value if bot else "UNKNOWN",
            },
            "agent": {
                "step": agent.step.value if agent else "IDLE",
                "detail": agent.detail if agent else "Waiting",
            },
        }
