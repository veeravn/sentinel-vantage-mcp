"""Backtest result models."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class BucketStat(BaseModel):
    bucket: int = Field(description="0 = lowest-score group, n_buckets-1 = highest.")
    count: int
    mean_forward_return: float


class RebalanceResult(BaseModel):
    as_of: datetime
    n_scored: int
    buckets: list[BucketStat]
    top_minus_bottom: float | None = None
    rank_ic: float | None = Field(default=None, description="Spearman corr(score, fwd return).")


class BacktestReport(BaseModel):
    """Aggregate evaluation across all rebalance dates (design section 17.1)."""

    strategy: str
    horizon_days: int
    n_buckets: int
    rebalances: list[RebalanceResult]

    mean_bucket_returns: list[float] = Field(
        default_factory=list, description="Forward return per bucket, averaged over dates."
    )
    mean_top_minus_bottom: float | None = None
    hit_rate_top_gt_bottom: float | None = Field(
        default=None, description="Fraction of dates where the top bucket beat the bottom."
    )
    mean_rank_ic: float | None = None
    avg_turnover_top_bucket: float | None = None
    coverage: float = Field(default=0.0, description="Avg fraction of the universe scored.")
