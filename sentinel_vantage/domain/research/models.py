"""Research domain models: normalized fundamentals and the research-score result."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class Fundamentals(BaseModel):
    """Normalized, point-in-time fundamental metrics for one symbol. A missing input stays
    ``None`` and lowers ``data_confidence`` rather than being imputed."""

    symbol: str
    cik: str
    as_of: datetime

    revenue: float | None = None
    revenue_prior: float | None = None
    revenue_growth_yoy: float | None = None
    eps: float | None = None
    eps_prior: float | None = None
    eps_growth_yoy: float | None = None

    gross_margin: float | None = None
    operating_margin: float | None = None
    roe: float | None = None

    debt_to_equity: float | None = None
    net_debt: float | None = None

    price: float | None = None
    shares_outstanding: float | None = None
    market_cap: float | None = None
    pe: float | None = None
    ev_to_sales: float | None = None

    data_confidence: float = 0.0
    missing: list[str] = Field(default_factory=list)


class ResearchResult(BaseModel):
    """An immutable per-strategy research-candidate score snapshot."""

    symbol: str
    strategy: str
    as_of: datetime

    score: float = Field(ge=0.0, le=100.0)
    confidence: float = Field(ge=0.0, le=1.0)
    rank_percentile: float | None = Field(default=None, ge=0.0, le=100.0)

    factors: dict[str, float] = Field(default_factory=dict)
    penalties: dict[str, float] = Field(default_factory=dict)
    positive_reasons: list[str] = Field(default_factory=list)
    negative_reasons: list[str] = Field(default_factory=list)
    hard_gate_failures: list[str] = Field(default_factory=list)

    model_version: str


class ResearchEligibility(BaseModel):
    symbol: str
    eligible: bool
    hard_gate_failures: list[str] = Field(default_factory=list)
