"""Trading agent.

Observes the market, asks for structured analysis, then lets the risk engine
decide. The agent never sends an order by itself.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from app.core.enums import AgentStep
from app.core.logging import get_logger
from app.models.documents import AgentStateDoc

logger = get_logger(__name__)


def summarize_cycle(result: Dict[str, Any]) -> str:
    if result.get("skipped"):
        reason = str(result.get("reason", "skipped")).replace("_", " ")
        detail = result.get("detail")
        return f"Blocked: {reason}" + (f" ({detail})" if detail else "")
    if result.get("error"):
        return f"Error: {result['error']}"
    return (
        f"Markets {result.get('markets', 0)} · "
        f"signals {result.get('signals_created', 0)} · "
        f"executed {result.get('executed', 0)} · "
        f"rejected {result.get('rejected', 0)} · "
        f"awaiting approval {result.get('pending_approval', 0)}"
    )


class TradingAgent:
    def __init__(self, engine) -> None:
        self.engine = engine
        self.engine.reporter = self.report

    async def report(self, step: AgentStep, detail: str = "") -> None:
        state = await self._state()
        state.step = step
        if detail:
            state.detail = detail[:500]
        state.updated_at = datetime.now(timezone.utc)
        await state.save()
        logger.info("agent_step", step=step.value, detail=detail)

    async def run(self) -> Dict[str, Any]:
        state = await self._state()
        state.runs += 1
        state.last_run_at = datetime.now(timezone.utc)
        await state.save()
        try:
            result = await self.engine.run_cycle()
        except Exception as exc:
            await self.report(AgentStep.BLOCKED, f"Cycle failed: {exc}")
            raise
        blocked = bool(result.get("skipped") or result.get("error"))
        await self.report(
            AgentStep.BLOCKED if blocked else AgentStep.DONE,
            summarize_cycle(result),
        )
        state = await self._state()
        state.last_result = {k: v for k, v in result.items() if k != "detail" or isinstance(v, str)}
        state.updated_at = datetime.now(timezone.utc)
        await state.save()
        return result

    async def snapshot(self) -> Dict[str, Any]:
        state = await self._state()
        return {
            "step": state.step.value,
            "detail": state.detail,
            "runs": state.runs,
            "last_run_at": state.last_run_at.isoformat() if state.last_run_at else None,
            "last_result": state.last_result or {},
        }

    async def _state(self) -> AgentStateDoc:
        state: Optional[AgentStateDoc] = await AgentStateDoc.find_one({"key": "singleton"})
        if state:
            return state
        state = AgentStateDoc(key="singleton")
        await state.insert()
        return state
