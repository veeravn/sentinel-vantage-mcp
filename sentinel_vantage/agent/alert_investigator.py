"""Agent-written alert notes: for fired alerts above a severity floor, run a short read-only
investigation per symbol and return a note to attach to the notification. Spend is capped
per hour and per cycle, and every failure degrades to "no note" so alerts are never lost."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime, timedelta

from sentinel_vantage.agent.runner import AgentRunner
from sentinel_vantage.agent.runs import AgentRunRepository
from sentinel_vantage.core.logging import get_logger
from sentinel_vantage.core.timeutils import utcnow
from sentinel_vantage.domain.alerts.models import AlertEvent

log = get_logger("alert_investigator")

INVESTIGATION_KIND = "alert_investigation"
INVESTIGATION_TOOLS = frozenset({"analyze_stock", "explain_move", "get_score_history"})
SEVERITY_RANK = {"info": 0, "warning": 1, "critical": 2}


def investigation_goal(event: AlertEvent) -> str:
    metrics = ", ".join(f"{k}={v}" for k, v in sorted(event.metrics.items())) or "none"
    return (
        f"Alert fired for {event.symbol} (severity {event.severity}, rule {event.rule_id}). "
        f"Evaluated metrics: {metrics}. Call analyze_stock and explain_move for "
        f"{event.symbol}, then write a 2-4 sentence note: what the scores and metrics show, "
        "and any catalyst evidence with its causal_confidence as the tool states it."
    )


class AlertInvestigator:
    def __init__(
        self,
        runner: AgentRunner,
        runs: AgentRunRepository,
        *,
        min_severity: str = "warning",
        max_per_hour: int = 6,
        max_per_cycle: int = 3,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._runner = runner
        self._runs = runs
        self._min_rank = SEVERITY_RANK.get(min_severity, 1)
        self._max_per_hour = max_per_hour
        self._max_per_cycle = max_per_cycle
        self._clock = clock

    def _candidates(self, events: Sequence[AlertEvent]) -> list[AlertEvent]:
        eligible = [e for e in events if SEVERITY_RANK.get(e.severity, 0) >= self._min_rank]
        eligible.sort(key=lambda e: SEVERITY_RANK.get(e.severity, 0), reverse=True)
        seen: set[str] = set()
        unique = []
        for e in eligible:
            if e.symbol not in seen:
                seen.add(e.symbol)
                unique.append(e)
        return unique

    async def _budget(self) -> int:
        since = self._clock() - timedelta(hours=1)
        recent = await self._runs.list_runs(kind=INVESTIGATION_KIND, limit=self._max_per_hour)
        used = sum(1 for r in recent if r.started_at >= since)
        return max(0, min(self._max_per_hour - used, self._max_per_cycle))

    async def investigate(self, events: Sequence[AlertEvent]) -> dict[str, str]:
        """Return ``{symbol: note}`` for the alerts that were investigated and grounded."""
        notes: dict[str, str] = {}
        candidates = self._candidates(events)
        if not candidates:
            return notes
        budget = await self._budget()
        if budget == 0:
            log.warning("alert_investigator.budget_exhausted", skipped=len(candidates))
            return notes
        for event in candidates[:budget]:
            try:
                result = await self._runner.run(investigation_goal(event), kind=INVESTIGATION_KIND)
            except Exception as exc:  # noqa: BLE001 - one bad investigation must not drop the rest
                log.error("alert_investigator.failed", symbol=event.symbol, error=str(exc))
                continue
            if result.stop_reason != "answered" or not result.answer.strip():
                continue
            if result.grounding is not None and not result.grounding.ok:
                log.warning("alert_investigator.ungrounded_note_dropped", symbol=event.symbol)
                continue
            notes[event.symbol] = result.answer.strip()
        return notes
