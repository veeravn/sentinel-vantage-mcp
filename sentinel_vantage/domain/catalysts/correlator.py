"""Catalyst correlation: score each nearby event's link to a price move by temporal
proximity, relevance, and novelty. Conservative — a catalyst must plausibly precede the
move, and nothing is called a cause."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from sentinel_vantage.domain.catalysts.models import CatalystEvidence, Event

# Base relevance and novelty per event type (structured company events rank highest).
_RELEVANCE = {
    "EARNINGS": 0.9,
    "FILING_8K": 0.9,
    "FILING_10Q": 0.7,
    "FILING_10K": 0.7,
    "SPLIT": 0.6,
    "DIVIDEND": 0.6,
    "NEWS": 0.4,
}
_NOVELTY = {
    "FILING_8K": 0.85,
    "EARNINGS": 0.85,
    "FILING_10K": 0.8,
    "FILING_10Q": 0.7,
    "SPLIT": 0.9,
    "DIVIDEND": 0.5,
    "NEWS": 0.6,
}
_STRUCTURED = {"EARNINGS", "FILING_8K", "FILING_10Q", "FILING_10K", "SPLIT", "DIVIDEND"}


def _proximity(move_time: datetime, event_time: datetime, window_days: float) -> float:
    delta_days = abs((move_time - event_time).total_seconds()) / 86400.0
    return max(0.0, 1.0 - delta_days / window_days)


def _strength(temporal: float, relevance: float, event_type: str) -> str:
    if event_type in _STRUCTURED and temporal >= 0.7 and relevance >= 0.7:
        return "strong"
    if temporal >= 0.4 and relevance >= 0.5:
        return "moderate"
    return "weak"


def _notes(event: Event, move_time: datetime) -> str:
    days = (move_time - event.event_time).total_seconds() / 86400.0
    if abs(days) < 1.0:
        when = "same day as the move"
    elif days >= 1.0:
        when = f"{days:.0f} day(s) before the move"
    else:
        when = f"{-days:.0f} day(s) after the move"
    return f"{event.metadata.get('form', event.type)} {when}."


def correlate(
    symbol: str,
    move_time: datetime,
    events: Sequence[Event],
    *,
    window_days: float = 5.0,
) -> list[CatalystEvidence]:
    """Rank events as catalyst evidence for a move. Events after the move are excluded
    (a catalyst precedes its move); a small same-day tolerance is allowed."""
    evidence: list[CatalystEvidence] = []
    for e in events:
        lead_days = (move_time - e.event_time).total_seconds() / 86400.0
        if lead_days < -1.0 or lead_days > window_days:  # after the move, or too far before
            continue
        temporal = _proximity(move_time, e.event_time, window_days)
        relevance = _RELEVANCE.get(e.type, 0.3)
        novelty = _NOVELTY.get(e.type, 0.5)
        evidence.append(
            CatalystEvidence(
                symbol=symbol,
                event_id=e.event_id,
                event_type=e.type,
                event_time=e.event_time,
                source=e.source,
                relevance_score=round(relevance, 4),
                temporal_proximity_score=round(temporal, 4),
                novelty_score=round(novelty, 4),
                evidence_strength=_strength(temporal, relevance, e.type),
                notes=_notes(e, move_time),
            )
        )
    # Rank by the composite of the three scores; ties broken by recency.
    evidence.sort(
        key=lambda c: (
            -(c.temporal_proximity_score * c.relevance_score * c.novelty_score),
            -c.event_time.timestamp(),
        )
    )
    return evidence
