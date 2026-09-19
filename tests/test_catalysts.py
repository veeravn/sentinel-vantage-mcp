"""Catalyst correlator and CatalystService.explain_move (offline)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from conftest import make_daily_bars

from sentinel_vantage.domain.catalysts.correlator import correlate
from sentinel_vantage.domain.catalysts.models import Event
from sentinel_vantage.domain.catalysts.service import CatalystService
from sentinel_vantage.storage.memory import InMemoryBarRepository, InMemoryEventRepository

MOVE = datetime(2026, 5, 10, tzinfo=UTC)


def _event(etype, days_before, eid="e1"):
    return Event(
        event_id=eid, symbol="XYZ", type=etype, event_time=MOVE - timedelta(days=days_before)
    )


def test_8k_same_day_is_strong():
    ev = correlate("XYZ", MOVE, [_event("FILING_8K", 0)])
    assert len(ev) == 1
    assert ev[0].evidence_strength == "strong"
    assert ev[0].temporal_proximity_score == 1.0


def test_10q_a_few_days_before_is_moderate():
    ev = correlate("XYZ", MOVE, [_event("FILING_10Q", 3)], window_days=5.0)
    assert ev[0].evidence_strength == "moderate"


def test_event_after_move_is_excluded():
    ev = correlate("XYZ", MOVE, [_event("FILING_8K", -3)])  # 3 days AFTER the move
    assert ev == []


def test_stronger_evidence_ranks_first():
    events = [_event("FILING_10K", 4, "old"), _event("FILING_8K", 0, "fresh")]
    ev = correlate("XYZ", MOVE, events)
    assert ev[0].event_id == "fresh"


async def test_explain_move_detects_spike_and_attaches_catalyst():
    # 30 flat days, then a +10% spike on the last day.
    closes = [100.0] * 30 + [110.0]
    volumes = [1_000_000.0] * 30 + [4_000_000.0]
    bars = make_daily_bars("XYZ", closes, volumes)
    spike_ts = bars[-1].ts

    bar_repo = InMemoryBarRepository({"XYZ": bars})
    event_repo = InMemoryEventRepository()
    await event_repo.save_events(
        [
            Event(
                event_id="acc1",
                symbol="XYZ",
                type="FILING_8K",
                event_time=spike_ts,
                title="8-K — Earnings release",
            )
        ]
    )

    svc = CatalystService(bar_repo, event_repo)
    result = await svc.explain_move("XYZ", as_of=spike_ts, lookback_days=20)

    assert result.move is not None
    assert round(result.move.return_pct, 1) == 10.0
    assert result.move.direction == "up"
    assert result.move.volume_ratio == 4.0
    assert result.catalysts and result.catalysts[0].event_type == "FILING_8K"
    assert result.causal_confidence == "strong"


async def test_explain_move_with_no_events_reports_move_only():
    bars = make_daily_bars("XYZ", [100.0] * 20 + [92.0], [1_000_000.0] * 21)
    svc = CatalystService(InMemoryBarRepository({"XYZ": bars}), InMemoryEventRepository())
    result = await svc.explain_move("XYZ", as_of=bars[-1].ts, lookback_days=20)
    assert result.move is not None and result.move.direction == "down"
    assert result.catalysts == []
    assert result.causal_confidence == "none"
