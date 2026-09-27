"""MongoDB connection and bootstrap."""

from __future__ import annotations

from typing import Optional

from beanie import init_beanie
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from app.core.config import Settings
from app.core.enums import TradingMode
from app.core.logging import get_logger
from app.models.documents import DOCUMENT_MODELS, BotStateDoc, PortfolioDoc
from app.models.schemas import RiskLimits, TradingPair
from app.services.auth.security import hash_password
from app.models.documents import UserDoc

logger = get_logger(__name__)

_client: Optional[AsyncIOMotorClient] = None


async def connect_db(settings: Settings) -> AsyncIOMotorDatabase:
    global _client
    _client = AsyncIOMotorClient(settings.mongodb_uri)
    db = _client[settings.mongodb_db]
    await init_beanie(database=db, document_models=DOCUMENT_MODELS)
    logger.info("mongodb_connected", db=settings.mongodb_db)
    return db


async def close_db() -> None:
    global _client
    if _client is not None:
        _client.close()
        _client = None
        logger.info("mongodb_disconnected")


def parse_pair(symbol: str, chain_id: int) -> TradingPair:
    s = symbol.strip().upper()
    if "/" in s:
        base, quote = s.split("/", 1)
    elif s.endswith("USDT"):
        base, quote = s[:-4], "USDT"
    elif s.endswith("USD"):
        base, quote = s[:-3], "USD"
    else:
        base, quote = s, "USD"
    return TradingPair(
        symbol=symbol.strip(),
        base_token=base,
        quote_token=quote,
        enabled=True,
        chain_id=chain_id,
    )


async def bootstrap_data(settings: Settings) -> None:
    """Seed admin user, bot state, and paper portfolio if missing."""
    existing_user = await UserDoc.find_one({"email": settings.admin_email})
    if not existing_user:
        await UserDoc(
            email=settings.admin_email,
            password_hash=hash_password(settings.admin_password),
            role="admin",
        ).insert()
        logger.info("admin_user_seeded", email=settings.admin_email)

    bot = await BotStateDoc.find_one({"key": "singleton"})
    if not bot:
        limits = RiskLimits(
            max_position_size_usd=settings.max_position_size_usd,
            max_daily_loss_usd=settings.max_daily_loss_usd,
            max_trades_per_day=settings.max_trades_per_day,
            max_portfolio_exposure_pct=settings.max_portfolio_exposure_pct,
            stop_loss_pct=settings.stop_loss_pct,
            take_profit_pct=settings.take_profit_pct,
            max_slippage_bps=settings.max_slippage_bps,
            min_liquidity_usd=settings.min_liquidity_usd,
            max_gas_usd=settings.max_gas_usd,
            min_confidence=settings.min_confidence,
            max_open_positions=settings.max_open_positions,
        )
        pairs = [parse_pair(s, settings.chain_id) for s in settings.pair_list]
        await BotStateDoc(
            key="singleton",
            mode=TradingMode(settings.trading_mode),
            risk_limits=limits,
            pairs=pairs,
        ).insert()
        logger.info("bot_state_seeded", mode=settings.trading_mode)

    portfolio = await PortfolioDoc.find_one({"key": "singleton"})
    if not portfolio:
        await PortfolioDoc(
            key="singleton",
            available_balance_usd=settings.paper_starting_balance,
        ).insert()
        logger.info(
            "portfolio_seeded",
            balance=settings.paper_starting_balance,
        )


async def ping_db() -> bool:
    if _client is None:
        return False
    try:
        await _client.admin.command("ping")
        return True
    except Exception:
        return False
