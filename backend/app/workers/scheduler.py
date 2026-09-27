"""Background scheduler for market polling and engine cycles."""

from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.core.logging import get_logger
from app.services.container import AppContainer

logger = get_logger(__name__)


class BotScheduler:
    def __init__(self, container: AppContainer) -> None:
        self.container = container
        self.scheduler = AsyncIOScheduler()
        self._started = False

    def start(self) -> None:
        if self._started:
            return
        s = self.container.settings
        self.scheduler.add_job(
            self._market_job,
            "interval",
            seconds=s.market_poll_seconds,
            id="market_poll",
            replace_existing=True,
            max_instances=1,
        )
        self.scheduler.add_job(
            self._engine_job,
            "interval",
            seconds=s.engine_cycle_seconds,
            id="engine_cycle",
            replace_existing=True,
            max_instances=1,
        )
        self.scheduler.start()
        self._started = True
        logger.info("scheduler_started")

    def shutdown(self) -> None:
        if self._started:
            self.scheduler.shutdown(wait=False)
            self._started = False
            logger.info("scheduler_stopped")

    async def _market_job(self) -> None:
        try:
            await self.container.market.fetch_and_store()
        except Exception as exc:
            logger.error("market_job_failed", error=str(exc))
            self.container.circuit.record_failure()

    async def _engine_job(self) -> None:
        try:
            await self.container.engine.run_cycle()
        except Exception as exc:
            logger.error("engine_job_failed", error=str(exc))
            self.container.circuit.record_failure()
