"""Application container / dependency wiring."""

from __future__ import annotations

from dataclasses import dataclass

from app.core.config import Settings
from app.services.agent.trader import TradingAgent
from app.services.ai.analyzer import AiAnalyzer
from app.services.circuit.breaker import CircuitBreaker
from app.services.dex.base import DexClient
from app.services.dex.factory import create_dex_client
from app.services.engine.trading import TradingEngine
from app.services.executor.service import TradeExecutor
from app.services.market.service import MarketDataService
from app.services.position.manager import PositionManager
from app.services.risk.engine import RiskEngine


@dataclass
class AppContainer:
    settings: Settings
    dex: DexClient
    market: MarketDataService
    ai: AiAnalyzer
    risk: RiskEngine
    executor: TradeExecutor
    positions: PositionManager
    circuit: CircuitBreaker
    engine: TradingEngine
    agent: TradingAgent


def build_container(settings: Settings) -> AppContainer:
    dex = create_dex_client(settings)
    market = MarketDataService(dex, settings)
    ai = AiAnalyzer(settings)
    risk = RiskEngine()
    executor = TradeExecutor(dex)
    positions = PositionManager(dex)
    circuit = CircuitBreaker()
    engine = TradingEngine(dex, market, ai, risk, executor, positions, circuit)
    agent = TradingAgent(engine)
    return AppContainer(
        settings=settings,
        dex=dex,
        market=market,
        ai=ai,
        risk=risk,
        executor=executor,
        positions=positions,
        circuit=circuit,
        engine=engine,
        agent=agent,
    )
