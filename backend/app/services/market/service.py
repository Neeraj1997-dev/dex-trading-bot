"""Market data ingestion and history storage."""

from __future__ import annotations

from typing import List, Optional

from datetime import datetime, timedelta, timezone

from app.core.config import Settings
from app.core.logging import get_logger
from app.models.documents import BotStateDoc, MarketSnapshotDoc
from app.models.schemas import MarketSnapshot
from app.services.dex.base import DexClient

logger = get_logger(__name__)


class MarketDataService:
    def __init__(self, dex: DexClient, settings: Settings) -> None:
        self.dex = dex
        self.settings = settings

    async def enabled_symbols(self) -> List[str]:
        bot = await BotStateDoc.find_one({"key": "singleton"})
        if not bot:
            return self.settings.pair_list
        return [p.symbol for p in bot.pairs if p.enabled]

    async def fetch_and_store(self) -> List[MarketSnapshot]:
        symbols = await self.enabled_symbols()
        snapshots = await self.dex.get_markets(symbols)
        now = datetime.now(timezone.utc)
        stale_after = timedelta(seconds=self.settings.market_stale_seconds)
        stored: List[MarketSnapshot] = []
        for snap in snapshots:
            age = now - snap.timestamp.replace(tzinfo=timezone.utc) if snap.timestamp.tzinfo is None else now - snap.timestamp
            snap.stale = age > stale_after
            doc = MarketSnapshotDoc(**snap.model_dump())
            await doc.insert()
            stored.append(snap)
        logger.info("market_snapshots_stored", count=len(stored))
        return stored

    async def latest(self, symbol: str) -> Optional[MarketSnapshot]:
        doc = await MarketSnapshotDoc.find({"symbol": symbol}).sort(
            "-timestamp"
        ).first_or_none()
        if not doc:
            return None
        return MarketSnapshot(
            symbol=doc.symbol,
            price=doc.price,
            bid=doc.bid,
            ask=doc.ask,
            volume_24h=doc.volume_24h,
            liquidity_usd=doc.liquidity_usd,
            price_change_24h_pct=doc.price_change_24h_pct,
            high_24h=doc.high_24h,
            low_24h=doc.low_24h,
            timestamp=doc.timestamp,
            source=doc.source,
            stale=doc.stale,
        )

    async def history(self, symbol: str, limit: int = 50) -> List[MarketSnapshot]:
        docs = (
            await MarketSnapshotDoc.find({"symbol": symbol})
            .sort("-timestamp")
            .limit(limit)
            .to_list()
        )
        docs.reverse()
        return [
            MarketSnapshot(
                symbol=d.symbol,
                price=d.price,
                bid=d.bid,
                ask=d.ask,
                volume_24h=d.volume_24h,
                liquidity_usd=d.liquidity_usd,
                price_change_24h_pct=d.price_change_24h_pct,
                high_24h=d.high_24h,
                low_24h=d.low_24h,
                timestamp=d.timestamp,
                source=d.source,
                stale=d.stale,
            )
            for d in docs
        ]
