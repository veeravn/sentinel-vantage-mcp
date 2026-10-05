"""Agent-written alert notes: selection, spend caps, failure isolation, and formatting."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from test_agent import FakeTools, ScriptedLLM, _call

from sentinel_vantage.agent.alert_investigator import (
    INVESTIGATION_KIND,
    AlertInvestigator,
    investigation_goal,
)
from sentinel_vantage.agent.llm import LLMError, LLMResponse
from sentinel_vantage.agent.runner import AgentRunner
from sentinel_vantage.apps.scheduler.notify import format_alert_message
from sentinel_vantage.core.timeutils import utcnow
from sentinel_vantage.domain.alerts.models import AlertEvent
from sentinel_vantage.storage.memory import InMemoryAgentRunRepository

NOW = datetime(2026, 10, 5, 14, 0, tzinfo=UTC)


def _event(symbol: str, severity: str = "warning", **metrics: float) -> AlertEvent:
    return AlertEvent(
        event_id=f"e-{symbol}-{severity}",
        rule_id="r1",
        symbol=symbol,
        as_of=NOW,
        severity=severity,
        fingerprint=f"r1|{symbol}",
        metrics=metrics or {"trend_score": 82.5},
        created_at=NOW,
    )


def _investigator(responses, runs=None, **kwargs):
    runs = runs or InMemoryAgentRunRepository()
    llm = ScriptedLLM(responses)
    runner = AgentRunner(llm, FakeTools(), runs=runs)
    return AlertInvestigator(runner, runs, **kwargs), runs, llm


def _answer(text="Quiet tape, nothing to add."):
    return [_call(), LLMResponse(text)]


async def test_investigates_alert_and_returns_note():
    inv, runs, _ = _investigator(_answer("Score is elevated; no catalyst evidence found."))
    notes = await inv.investigate([_event("NVDA")])
    assert notes == {"NVDA": "Score is elevated; no catalyst evidence found."}
    assert (await runs.list_runs(kind=INVESTIGATION_KIND))[0].status == "answered"


async def test_goal_includes_alert_metrics_and_grounds_on_them():
    event = _event("NVDA", trend_score=82.5)
    assert "trend_score=82.5" in investigation_goal(event)
    inv, _, _ = _investigator(_answer("Trend score is 82.5."))
    assert await inv.investigate([event]) == {"NVDA": "Trend score is 82.5."}


async def test_below_severity_floor_skipped_without_llm_call():
    inv, runs, llm = _investigator([])
    assert await inv.investigate([_event("AAPL", "info")]) == {}
    assert llm.seen_messages == [] and await runs.list_runs() == []


async def test_dedupes_symbols_and_prefers_critical():
    inv, _, llm = _investigator(_answer(), max_per_cycle=1)
    notes = await inv.investigate([_event("AMD", "warning"), _event("NVDA", "critical")])
    assert list(notes) == ["NVDA"]
    assert "NVDA" in llm.seen_messages[0][0].text


async def test_per_cycle_cap():
    inv, _, _ = _investigator(_answer() * 2, max_per_cycle=2)
    notes = await inv.investigate([_event("A"), _event("B"), _event("C")])
    assert len(notes) == 2


async def test_hourly_cap_counts_recent_runs_only():
    runs = InMemoryAgentRunRepository()
    inv, _, llm = _investigator(_answer() * 6, runs, max_per_hour=2, max_per_cycle=3)
    assert len(await inv.investigate([_event("A"), _event("B"), _event("C")])) == 2
    remaining = len(llm._responses)
    assert await inv.investigate([_event("D")]) == {}  # budget spent this hour
    assert len(llm._responses) == remaining  # no further LLM calls

    inv2 = AlertInvestigator(
        inv._runner, runs, max_per_hour=2, clock=lambda: utcnow() + timedelta(hours=2)
    )
    inv2._runner._llm._responses.extend(_answer())
    assert list(await inv2.investigate([_event("E")])) == ["E"]


async def test_failure_isolated_and_not_fatal():
    class Flaky(ScriptedLLM):
        async def complete(self, **kwargs):
            if not self._responses:
                raise LLMError("boom")
            return await super().complete(**kwargs)

    runs = InMemoryAgentRunRepository()
    llm = Flaky(_answer("Second symbol note."))
    runner = AgentRunner(llm, FakeTools(), runs=runs)
    inv = AlertInvestigator(runner, runs)
    notes = await inv.investigate([_event("A"), _event("B")])
    assert notes == {"A": "Second symbol note."}
    statuses = {r.status for r in await runs.list_runs(kind=INVESTIGATION_KIND)}
    assert statuses == {"answered", "error"}


async def test_ungrounded_note_dropped():
    inv, _, _ = _investigator([_call(), LLMResponse("Score hit 99.9."), LLMResponse("Now 88.8.")])
    assert await inv.investigate([_event("NVDA")]) == {}


async def test_budget_exhausted_runs_do_not_yield_notes():
    inv, _, _ = _investigator([_call(id="c1"), _call(id="c2")])
    inv._runner._max_steps = 2
    assert await inv.investigate([_event("NVDA")]) == {}


def test_format_alert_message_with_notes():
    subject, body = format_alert_message([_event("NVDA")], {"NVDA": "Strong volume."})
    assert subject.endswith("1 alert(s)")
    assert body.endswith("Agent notes:\n- NVDA: Strong volume.")
    assert "Agent notes" not in format_alert_message([_event("NVDA")])[1]
