"""Trend domain models: eligibility outcome and the trend result snapshot."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class Eligibility(BaseModel):
    symbol: str
    eligible: bool
    gate_failures: list[str] = Field(default_factory=list)


class TrendResult(BaseModel):
    """An immutable, reproducible trend-score snapshot for one symbol/horizon."""

    symbol: str
    horizon: str
    as_of: datetime

    score: float = Field(ge=0.0, le=100.0)
    confidence: float = Field(ge=0.0, le=1.0)
    rank_percentile: float | None = Field(default=None, ge=0.0, le=100.0)

    # Raw, human-readable metrics (never require the LLM to recompute these).
    metrics: dict[str, float] = Field(default_factory=dict)
    # Normalized factor z-scores that drove the result (inspectability).
    factor_z: dict[str, float] = Field(default_factory=dict)

    reasons: list[str] = Field(default_factory=list)
    risk_flags: list[str] = Field(default_factory=list)

    model_version: str
