from __future__ import annotations

from typing import List

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request

from app.core.enums import (
    BotStatus,
    ConnectionHealth,
    PositionStatus,
)
from app.db.mongodb import ping_db
from app.models.documents import (
    AuditLogDoc,
    BotStateDoc,
    MarketSnapshotDoc,
    OrderDoc,
    PortfolioDoc,
    PositionDoc,
    SignalDoc,
    TradeHistoryDoc,
    UserDoc,
)
from app.models.schemas import (
    AgentView,
    AiAnalysis,
    ChatMessageView,
    ChatRequest,
    ChatThread,
    AuditEventView,
    BotControlRequest,
    BotStateView,
    ConnectionStatus,
    DashboardSnapshot,
    LoginRequest,
    MarketSnapshot,
    ModeUpdateRequest,
    OrderView,
    PairToggleRequest,
    PortfolioSummary,
    PositionView,
    RiskRejection,
    RiskUpdateRequest,
    SignalApproveRequest,
    SignalView,
    TokenResponse,
    TradingPair,
)
from app.services.audit.service import write_audit
from app.services.auth.deps import authenticate_user, require_admin
from app.services.auth.security import create_access_token
from app.services.container import AppContainer

router = APIRouter()


def get_container(request: Request) -> AppContainer:
    return request.app.state.container


@router.post("/auth/login", response_model=TokenResponse, tags=["auth"])
async def login(body: LoginRequest) -> TokenResponse:
    user = await authenticate_user(body.email, body.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = create_access_token(user.email, user.role)
    await write_audit("LOGIN", user.email, "user", str(user.id), {})
    return TokenResponse(access_token=token)


@router.get("/health", tags=["system"])
async def health(request: Request) -> dict:
    container: AppContainer = get_container(request)
    db_ok = await ping_db()
    dex = await container.dex.health()
    oi = await container.ai.health()
    return {
        "status": "ok" if db_ok else "degraded",
        "database": "CONNECTED" if db_ok else "DISCONNECTED",
        "dex": dex,
        "openai": oi.value,
    }


@router.get("/agent", response_model=AgentView, tags=["agent"])
async def agent_status(
    request: Request,
    user: UserDoc = Depends(require_admin),
) -> AgentView:
    container = get_container(request)
    return AgentView.model_validate(await container.agent.snapshot())


def _chat_view(doc) -> ChatMessageView:
    return ChatMessageView(
        id=str(doc.id),
        role=doc.role,
        content=doc.content,
        created_at=doc.created_at,
    )


@router.get("/chat", response_model=ChatThread, tags=["chat"])
async def chat_history(
    request: Request,
    user: UserDoc = Depends(require_admin),
) -> ChatThread:
    container = get_container(request)
    docs = await container.chat.history()
    return ChatThread(messages=[_chat_view(doc) for doc in docs])


@router.post("/chat", response_model=ChatThread, tags=["chat"])
async def chat_send(
    body: ChatRequest,
    request: Request,
    user: UserDoc = Depends(require_admin),
) -> ChatThread:
    container = get_container(request)
    await container.chat.reply(body.message)
    docs = await container.chat.history()
    return ChatThread(messages=[_chat_view(doc) for doc in docs])


@router.get("/dashboard", response_model=DashboardSnapshot, tags=["dashboard"])
async def dashboard(
    request: Request,
    user: UserDoc = Depends(require_admin),
) -> DashboardSnapshot:
    container = get_container(request)
    bot = await BotStateDoc.find_one({"key": "singleton"})
    portfolio = await PortfolioDoc.find_one({"key": "singleton"})
    if not bot or not portfolio:
        raise HTTPException(500, "System not initialized")

    positions = await PositionDoc.find({"status": PositionStatus.OPEN}).to_list()
    orders = await OrderDoc.find_all().sort("-created_at").limit(50).to_list()
    signals = await SignalDoc.find_all().sort("-created_at").limit(50).to_list()
    markets = await MarketSnapshotDoc.find_all().sort("-timestamp").limit(30).to_list()
    history = await TradeHistoryDoc.find_all().sort("-created_at").limit(50).to_list()

    unrealized = sum(p.unrealized_pnl_usd for p in positions)
    total = portfolio.available_balance_usd + portfolio.invested_usd + unrealized
    decided = portfolio.wins + portfolio.losses
    win_rate = (portfolio.wins / decided * 100) if decided else 0.0

    last_market = markets[0].timestamp if markets else None
    db_ok = await ping_db()

    agent = await container.agent.snapshot()

    return DashboardSnapshot(
        agent=AgentView.model_validate(agent),
        bot=BotStateView(
            status=bot.status,
            mode=bot.mode,
            kill_switch=bot.kill_switch,
            paused=bot.paused,
            risk_limits=bot.risk_limits,
            pairs=bot.pairs,
            last_cycle_at=bot.last_cycle_at,
            circuit_breaker_open=bot.circuit_breaker_open,
            circuit_breaker_reason=bot.circuit_breaker_reason,
        ),
        portfolio=PortfolioSummary(
            total_value_usd=round(total, 2),
            available_balance_usd=round(portfolio.available_balance_usd, 2),
            invested_usd=round(portfolio.invested_usd, 2),
            unrealized_pnl_usd=round(unrealized, 2),
            realized_pnl_usd=round(portfolio.realized_pnl_usd, 2),
            daily_pnl_usd=round(portfolio.daily_pnl_usd, 2),
            open_positions=len(positions),
            win_rate=round(win_rate, 2),
            total_trades=portfolio.total_trades,
            wins=portfolio.wins,
            losses=portfolio.losses,
        ),
        positions=[
            PositionView(
                id=str(p.id),
                symbol=p.symbol,
                side=p.side,
                status=p.status,
                entry_price=p.entry_price,
                current_price=p.current_price,
                size=p.size,
                size_usd=p.size_usd,
                unrealized_pnl_usd=p.unrealized_pnl_usd,
                realized_pnl_usd=p.realized_pnl_usd,
                take_profit=p.take_profit,
                stop_loss=p.stop_loss,
                fees_usd=p.fees_usd,
                gas_usd=p.gas_usd,
                opened_at=p.opened_at,
                closed_at=p.closed_at,
                entry_tx_hash=p.entry_tx_hash,
                exit_tx_hash=p.exit_tx_hash,
            )
            for p in positions
        ],
        orders=[
            OrderView(
                id=str(o.id),
                symbol=o.symbol,
                side=o.side,
                type=o.type,
                status=o.status,
                requested_price=o.requested_price,
                filled_price=o.filled_price,
                size=o.size,
                size_usd=o.size_usd,
                slippage_bps=o.slippage_bps,
                tx_hash=o.tx_hash,
                failure_reason=o.failure_reason,
                created_at=o.created_at,
                updated_at=o.updated_at,
            )
            for o in orders
        ],
        signals=[
            SignalView(
                id=str(s.id),
                symbol=s.symbol,
                decision=s.decision,
                status=s.status,
                confidence=s.confidence,
                risk_level=s.risk_level,
                entry_price=s.entry_price,
                take_profit=s.take_profit,
                stop_loss=s.stop_loss,
                reasoning_summary=s.reasoning_summary,
                invalidation_condition=s.invalidation_condition,
                fingerprint=s.fingerprint,
                created_at=s.created_at,
                analysis=AiAnalysis.model_validate(s.analysis) if s.analysis else None,
                risk_rejections=(
                    [RiskRejection.model_validate(r) for r in s.risk_rejections]
                    if s.risk_rejections
                    else None
                ),
            )
            for s in signals
        ],
        connections=ConnectionStatus(
            dex=ConnectionHealth(await container.dex.health()),
            openai=await container.ai.health(),
            database=ConnectionHealth.CONNECTED if db_ok else ConnectionHealth.DISCONNECTED,
            last_market_update=last_market,
        ),
        recent_market=[
            MarketSnapshot(
                symbol=m.symbol,
                price=m.price,
                bid=m.bid,
                ask=m.ask,
                volume_24h=m.volume_24h,
                liquidity_usd=m.liquidity_usd,
                price_change_24h_pct=m.price_change_24h_pct,
                high_24h=m.high_24h,
                low_24h=m.low_24h,
                timestamp=m.timestamp,
                source=m.source,
                stale=m.stale,
            )
            for m in markets
        ],
        trade_history=[
            {
                "id": str(t.id),
                "symbol": t.symbol,
                "side": t.side.value,
                "entry_price": t.entry_price,
                "exit_price": t.exit_price,
                "size": t.size,
                "pnl_usd": t.pnl_usd,
                "fees_usd": t.fees_usd,
                "reason": t.reason,
                "created_at": t.created_at.isoformat(),
            }
            for t in history
        ],
    )


@router.post("/bot/control", tags=["bot"])
async def bot_control(
    body: BotControlRequest,
    request: Request,
    user: UserDoc = Depends(require_admin),
) -> dict:
    bot = await BotStateDoc.find_one({"key": "singleton"})
    if not bot:
        raise HTTPException(500, "Bot state missing")
    container = get_container(request)

    action = body.action
    if action == "START":
        if bot.kill_switch:
            raise HTTPException(400, "Reset kill switch before starting")
        bot.status = BotStatus.RUNNING
        bot.paused = False
    elif action == "STOP":
        bot.status = BotStatus.STOPPED
        bot.paused = False
    elif action == "PAUSE":
        bot.paused = True
        bot.status = BotStatus.PAUSED
    elif action == "RESUME":
        if bot.kill_switch:
            raise HTTPException(400, "Kill switch active")
        bot.paused = False
        bot.status = BotStatus.RUNNING
    elif action == "KILL_SWITCH":
        bot.kill_switch = True
        bot.status = BotStatus.KILL_SWITCH
        bot.paused = True
    elif action == "RESET_KILL_SWITCH":
        bot.kill_switch = False
        bot.status = BotStatus.STOPPED
        bot.paused = False
        await container.circuit.reset(actor=user.email)

    bot.updated_at = datetime.now(timezone.utc)
    await bot.save()
    await write_audit(f"BOT_{action}", user.email, "bot", "singleton", {"status": bot.status.value})
    return {"status": bot.status.value, "kill_switch": bot.kill_switch, "paused": bot.paused}


@router.put("/bot/mode", tags=["bot"])
async def set_mode(
    body: ModeUpdateRequest,
    user: UserDoc = Depends(require_admin),
) -> dict:
    bot = await BotStateDoc.find_one({"key": "singleton"})
    if not bot:
        raise HTTPException(500, "Bot state missing")
    # Safety: default path always allows PAPER; live AUTO requires ops awareness
    bot.mode = body.mode
    bot.updated_at = datetime.now(timezone.utc)
    await bot.save()
    await write_audit("BOT_MODE_CHANGE", user.email, "bot", "singleton", {"mode": body.mode.value})
    return {"mode": bot.mode.value}


@router.put("/bot/risk", tags=["bot"])
async def update_risk(
    body: RiskUpdateRequest,
    user: UserDoc = Depends(require_admin),
) -> dict:
    bot = await BotStateDoc.find_one({"key": "singleton"})
    if not bot:
        raise HTTPException(500, "Bot state missing")
    bot.risk_limits = body.limits
    bot.updated_at = datetime.now(timezone.utc)
    await bot.save()
    await write_audit(
        "RISK_LIMITS_UPDATED",
        user.email,
        "bot",
        "singleton",
        body.limits.model_dump(),
    )
    return {"risk_limits": bot.risk_limits.model_dump()}


@router.put("/bot/pairs", tags=["bot"])
async def toggle_pair(
    body: PairToggleRequest,
    user: UserDoc = Depends(require_admin),
) -> dict:
    bot = await BotStateDoc.find_one({"key": "singleton"})
    if not bot:
        raise HTTPException(500, "Bot state missing")
    found = False
    updated: List[TradingPair] = []
    for p in bot.pairs:
        if p.symbol == body.symbol:
            p.enabled = body.enabled
            found = True
        updated.append(p)
    if not found:
        raise HTTPException(404, f"Pair {body.symbol} not found")
    bot.pairs = updated
    bot.updated_at = datetime.now(timezone.utc)
    await bot.save()
    await write_audit(
        "PAIR_TOGGLED",
        user.email,
        "pair",
        body.symbol,
        {"enabled": body.enabled},
    )
    return {"pairs": [p.model_dump() for p in bot.pairs]}


@router.post("/bot/cycle", tags=["bot"])
async def run_cycle_now(
    request: Request,
    user: UserDoc = Depends(require_admin),
) -> dict:
    container = get_container(request)
    result = await container.agent.run()
    await write_audit("MANUAL_CYCLE", user.email, "bot", "singleton", result)
    return result


@router.post("/signals/{signal_id}/approve", tags=["signals"])
async def approve_signal(
    signal_id: str,
    body: SignalApproveRequest,
    request: Request,
    user: UserDoc = Depends(require_admin),
) -> dict:
    container = get_container(request)
    try:
        signal = await container.engine.approve_signal(signal_id, body.approve, user.email)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"id": str(signal.id), "status": signal.status.value}


@router.get("/positions", tags=["trading"])
async def list_positions(user: UserDoc = Depends(require_admin)) -> List[dict]:
    docs = await PositionDoc.find_all().sort("-opened_at").limit(100).to_list()
    return [
        {
            "id": str(p.id),
            "symbol": p.symbol,
            "status": p.status.value,
            "entry_price": p.entry_price,
            "current_price": p.current_price,
            "unrealized_pnl_usd": p.unrealized_pnl_usd,
            "take_profit": p.take_profit,
            "stop_loss": p.stop_loss,
            "entry_tx_hash": p.entry_tx_hash,
        }
        for p in docs
    ]


@router.get("/orders", tags=["trading"])
async def list_orders(user: UserDoc = Depends(require_admin)) -> List[dict]:
    docs = await OrderDoc.find_all().sort("-created_at").limit(100).to_list()
    return [
        {
            "id": str(o.id),
            "symbol": o.symbol,
            "side": o.side.value,
            "status": o.status.value,
            "tx_hash": o.tx_hash,
            "size_usd": o.size_usd,
            "filled_price": o.filled_price,
        }
        for o in docs
    ]


@router.get("/signals", tags=["trading"])
async def list_signals(user: UserDoc = Depends(require_admin)) -> List[dict]:
    docs = await SignalDoc.find_all().sort("-created_at").limit(100).to_list()
    return [
        {
            "id": str(s.id),
            "symbol": s.symbol,
            "decision": s.decision.value,
            "status": s.status.value,
            "confidence": s.confidence,
            "entry_price": s.entry_price,
            "take_profit": s.take_profit,
            "stop_loss": s.stop_loss,
            "reasoning_summary": s.reasoning_summary,
        }
        for s in docs
    ]


@router.get("/audit", tags=["system"])
async def list_audit(
    user: UserDoc = Depends(require_admin),
) -> List[AuditEventView]:
    docs = await AuditLogDoc.find_all().sort("-created_at").limit(100).to_list()
    return [
        AuditEventView(
            id=str(a.id),
            action=a.action,
            actor=a.actor,
            entity_type=a.entity_type,
            entity_id=a.entity_id,
            details=a.details,
            created_at=a.created_at,
        )
        for a in docs
    ]


@router.get("/markets", tags=["market"])
async def list_markets(user: UserDoc = Depends(require_admin)) -> List[dict]:
    docs = await MarketSnapshotDoc.find_all().sort("-timestamp").limit(50).to_list()
    return [
        {
            "symbol": m.symbol,
            "price": m.price,
            "liquidity_usd": m.liquidity_usd,
            "volume_24h": m.volume_24h,
            "price_change_24h_pct": m.price_change_24h_pct,
            "stale": m.stale,
            "timestamp": m.timestamp.isoformat(),
            "source": m.source,
        }
        for m in docs
    ]


@router.get("/notifications/whatsapp", tags=["notifications"])
async def whatsapp_status(
    request: Request,
    user: UserDoc = Depends(require_admin),
) -> dict:
    settings = get_container(request).settings
    provider = settings.whatsapp_provider
    configured = False
    if provider == "twilio":
        configured = bool(
            settings.twilio_account_sid
            and settings.twilio_auth_token
            and settings.twilio_whatsapp_from
        )
    elif provider == "meta":
        configured = bool(settings.whatsapp_meta_token and settings.whatsapp_meta_phone_id)
    elif provider == "callmebot":
        configured = bool(settings.callmebot_apikey)
    return {
        "enabled": settings.whatsapp_enabled,
        "provider": provider,
        "to": settings.whatsapp_to_e164,
        "configured": configured,
    }


@router.post("/notifications/whatsapp/test", tags=["notifications"])
async def whatsapp_test(
    request: Request,
    user: UserDoc = Depends(require_admin),
) -> dict:
    from app.services.notify.whatsapp import get_notifier

    notifier = get_notifier()
    ok = await notifier.send(
        "Delta Trading Console\nTest notification OK.\n"
        f"If you received this, WhatsApp alerts are working for {notifier.settings.whatsapp_to_e164}."
    )
    await write_audit(
        "WHATSAPP_TEST",
        user.email,
        "notification",
        None,
        {"success": ok, "to": notifier.settings.whatsapp_to_e164},
    )
    if not ok:
        raise HTTPException(
            status_code=400,
            detail=(
                "WhatsApp send failed. Set credentials for the selected provider "
                "(CALLMEBOT_APIKEY, or Twilio / Meta keys) in .env"
            ),
        )
    return {"success": True, "to": notifier.settings.whatsapp_to_e164}

