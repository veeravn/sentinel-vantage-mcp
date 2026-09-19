"""Backtest engine + metrics on synthetic data (deterministic, offline)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sentinel_vantage.backtest.core import run_backtest
from sentinel_vantage.backtest.metrics import assign_buckets, spearman


def test_spearman_monotonic():
    assert abs(spearman([1, 2, 3, 4], [10, 20, 30, 40]) - 1.0) < 1e-9
    assert abs(spearman([1, 2, 3, 4], [40, 30, 20, 10]) + 1.0) < 1e-9
    assert spearman([1], [1]) is None


def test_assign_buckets_equal_count():
    scored = [(f"S{i}", float(i)) for i in range(10)]
    buckets = assign_buckets(scored, 5)
    assert buckets["S0"] == 0 and buckets["S9"] == 4  # lowest -> 0, highest -> top
    # Roughly equal counts per bucket.
    counts = [sum(1 for b in buckets.values() if b == k) for k in range(5)]
    assert counts == [2, 2, 2, 2, 2]


def _dates(n):
    d0 = datetime(2026, 1, 5, tzinfo=UTC)
    return [d0 + timedelta(days=7 * i) for i in range(n)]


async def test_perfect_signal_has_positive_spread_and_ic():
    # Score equals the (deterministic) forward return -> perfect ranking.
    symbols = [f"S{i:02d}" for i in range(20)]
    fwd = {s: (i - 10) / 100.0 for i, s in enumerate(symbols)}  # -0.10 .. +0.09

    async def score_fn(as_of):
        return {s: fwd[s] for s in symbols}

    async def forward_return_fn(symbol, as_of):
        return fwd[symbol]

    report = await run_backtest(
        strategy="trend-v0",
        rebalance_dates=_dates(3),
        score_fn=score_fn,
        forward_return_fn=forward_return_fn,
        horizon_days=20,
        n_buckets=5,
        universe_size=len(symbols),
    )
    assert report.mean_rank_ic == 1.0
    assert report.mean_top_minus_bottom > 0
    # Bucket returns increase monotonically from bottom to top.
    assert report.mean_bucket_returns == sorted(report.mean_bucket_returns)
    assert report.hit_rate_top_gt_bottom == 1.0
    assert report.coverage == 1.0


async def test_random_like_signal_has_near_zero_ic():
    # Score and forward return are unrelated -> IC near zero, small spread.
    symbols = [f"S{i:02d}" for i in range(20)]
    score = {s: float(i) for i, s in enumerate(symbols)}
    fwd = {s: float((i * 7) % 20) / 100.0 for i, s in enumerate(symbols)}

    async def score_fn(as_of):
        return score

    async def forward_return_fn(symbol, as_of):
        return fwd[symbol]

    report = await run_backtest(
        strategy="trend-v0",
        rebalance_dates=_dates(2),
        score_fn=score_fn,
        forward_return_fn=forward_return_fn,
        horizon_days=20,
    )
    assert report.mean_rank_ic is not None
    assert abs(report.mean_rank_ic) < 0.5


async def test_missing_forward_returns_are_dropped():
    symbols = [f"S{i:02d}" for i in range(10)]

    async def score_fn(as_of):
        return {s: float(i) for i, s in enumerate(symbols)}

    async def forward_return_fn(symbol, as_of):
        return None  # e.g. delisted / no future bar

    report = await run_backtest(
        strategy="trend-v0",
        rebalance_dates=_dates(2),
        score_fn=score_fn,
        forward_return_fn=forward_return_fn,
        horizon_days=20,
    )
    # No date had enough scored names -> no rebalances recorded.
    assert report.rebalances == []
    assert report.mean_top_minus_bottom is None
