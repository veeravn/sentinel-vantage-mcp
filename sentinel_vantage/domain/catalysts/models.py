"""Catalyst domain models: structured events and correlation evidence.

The system never claims a headline *caused* a move merely because they occurred close
together (design section 12). Correlation returns an evidence strength and competing
explanations; causal language is deliberately avoided.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

EvidenceStrength = Literal["weak", "moderate", "strong"]


class Event(BaseModel):
    """A structured market event (filing, earnings, corporate action, news)."""

    event_id: str
    source: str = "SEC"
    symbol: str | None = None
    cik: str | None = None
    type: str = Field(description="e.g. FILING_10K, FILING_10Q, FILING_8K, EARNINGS, SPLIT.")
    event_time: datetime = Field(description="Publication/filing time (UTC).")
    title: str | None = None
    url: str | None = None
    metadata: dict = Field(default_factory=dict)


class CatalystEvidence(BaseModel):
    """Evidence linking one event to a price move (design section 12)."""

    symbol: str
    event_id: str
    event_type: str
    event_time: datetime
    source: str
    relevance_score: float = Field(ge=0.0, le=1.0)
    temporal_proximity_score: float = Field(ge=0.0, le=1.0)
    novelty_score: float = Field(ge=0.0, le=1.0)
    evidence_strength: EvidenceStrength
    notes: str | None = None


class MoveSummary(BaseModel):
    symbol: str
    move_date: datetime
    return_pct: float
    volume_ratio: float | None = None
    direction: Literal["up", "down"]


class ExplainMove(BaseModel):
    symbol: str
    as_of: datetime
    move: MoveSummary | None = None
    catalysts: list[CatalystEvidence] = Field(default_factory=list)
    causal_confidence: Literal["none", "weak", "moderate", "strong"] = "none"
    disclaimer: str = (
        "Catalysts are correlations, not proven causes. Timing alignment and competing "
        "explanations are provided as evidence for research, not a causal conclusion."
    )
