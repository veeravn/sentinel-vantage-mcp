"""Alerts and watchlists: a structured, validated rule DSL (never free-form LLM text) and
its stored state, so rules evaluate deterministically and replay."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Op = Literal[">=", "<=", ">", "<", "==", "!="]


class Condition(BaseModel):
    metric: str = Field(description="e.g. 'trend_score', 'volume_ratio', 'research_score:GARP'.")
    op: Op
    value: float


class RuleDSL(BaseModel):
    """All of ``all`` must hold and at least one of ``any`` (when given)."""

    all: list[Condition] = Field(default_factory=list)
    any: list[Condition] = Field(default_factory=list)
    cooldown_hours: float = 4.0

    def referenced_metrics(self) -> list[str]:
        return sorted({c.metric for c in (*self.all, *self.any)})


class AlertRule(BaseModel):
    rule_id: str
    name: str | None = None
    owner: str | None = None
    symbols: list[str] = Field(default_factory=list)
    watchlist_id: str | None = None
    rule: RuleDSL
    severity: Literal["info", "warning", "critical"] = "info"
    active: bool = True
    created_at: datetime


class AlertEvent(BaseModel):
    event_id: str
    rule_id: str
    symbol: str
    as_of: datetime
    severity: str
    fingerprint: str = Field(description="rule_id|symbol — used for cooldown dedup.")
    metrics: dict[str, float] = Field(
        default_factory=dict, description="Evaluated metric values (auditable)."
    )
    created_at: datetime


class Watchlist(BaseModel):
    watchlist_id: str
    owner: str | None = None
    name: str
    symbols: list[str] = Field(default_factory=list)
    settings: dict = Field(default_factory=dict)
    created_at: datetime


class SymbolChange(BaseModel):
    symbol: str
    trend_score_now: float | None = None
    trend_score_prev: float | None = None
    trend_score_delta: float | None = None
    new_events: int = 0
    notes: list[str] = Field(default_factory=list)


class WatchlistChanges(BaseModel):
    watchlist_id: str
    since: datetime
    as_of: datetime
    changes: list[SymbolChange] = Field(default_factory=list)
