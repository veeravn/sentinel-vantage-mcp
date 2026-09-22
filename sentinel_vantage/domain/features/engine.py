"""Feature engine — pure, deterministic functions from daily bar history to a FeatureSet."""

from __future__ import annotations

import statistics
from collections.abc import Sequence
from datetime import datetime

from sentinel_vantage.domain.features.models import FeatureSet
from sentinel_vantage.providers.base import Bar

FULL_CONFIDENCE_DAYS = 120
_SCORING_FACTORS = 5
_HISTORY_FLOOR = 0.5
_FRESHNESS_FLOOR = 0.4
_STALE_DAYS = 10
_BASELINE_DAYS = 20
_BASELINE_FLOOR = 0.6


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _freshness_factor(staleness_days: int) -> float:
    """1.0 when the latest bar is current, decaying to a floor as it lags ``as_of``."""
    if staleness_days <= 1:
        return 1.0
    if staleness_days >= _STALE_DAYS:
        return _FRESHNESS_FLOOR
    return 1.0 - (1.0 - _FRESHNESS_FLOOR) * (staleness_days - 1) / (_STALE_DAYS - 1)


def _sorted(bars: Sequence[Bar]) -> list[Bar]:
    return sorted(bars, key=lambda b: b.ts)


def _pct_change(newer: float, older: float) -> float | None:
    if older == 0:
        return None
    return newer / older - 1.0


def _benchmark_return_1d(benchmark_bars: Sequence[Bar] | None) -> float | None:
    if not benchmark_bars:
        return None
    b = _sorted(benchmark_bars)
    if len(b) < 2:
        return None
    return _pct_change(b[-1].close, b[-2].close)


def compute_features(
    symbol: str,
    bars: Sequence[Bar],
    *,
    as_of: datetime,
    benchmark_bars: Sequence[Bar] | None = None,
) -> FeatureSet:
    """Compute the Phase 1 feature set. Never raises; missing inputs stay None."""
    b = _sorted(bars)
    n = len(b)
    if n == 0:
        return FeatureSet(symbol=symbol, as_of=as_of, n_days=0, last_price=0.0)

    closes = [x.close for x in b]
    volumes = [x.volume for x in b]
    last = b[-1]

    return_1d = _pct_change(closes[-1], closes[-2]) if n >= 2 else None
    return_5d = _pct_change(closes[-1], closes[-6]) if n >= 6 else None
    intraday_return = _pct_change(last.close, last.open) if last.open else None

    daily_returns = [
        r for i in range(1, n) if (r := _pct_change(closes[i], closes[i - 1])) is not None
    ]
    realized_vol_20d = (
        statistics.pstdev(daily_returns[-20:]) if len(daily_returns[-20:]) >= 2 else None
    )

    dollar_vols = [closes[i] * volumes[i] for i in range(n)]
    dollar_volume_median_20d = statistics.median(dollar_vols[-20:]) if n >= 1 else None

    # Volume ratio vs trailing 20-day median, excluding the latest bar.
    baseline = volumes[-21:-1] if n >= 21 else volumes[:-1]
    baseline = [v for v in baseline if v > 0]
    median_base = statistics.median(baseline) if baseline else None
    volume_ratio = (volumes[-1] / median_base) if median_base else None

    bench_1d = _benchmark_return_1d(benchmark_bars)
    benchmark_available = bench_1d is not None
    relative_strength_1d = (
        (return_1d - bench_1d) if (return_1d is not None and bench_1d is not None) else None
    )

    factors = [return_1d, return_5d, intraday_return, relative_strength_1d, volume_ratio]
    computable = sum(1 for f in factors if f is not None)
    completeness = round(computable / _SCORING_FACTORS, 4)

    history_factor = _clamp(n / FULL_CONFIDENCE_DAYS, _HISTORY_FLOOR, 1.0)
    benchmark_factor = 1.0 if benchmark_available else 0.7
    freshness_factor = _freshness_factor((as_of.date() - last.ts.date()).days)
    baseline_factor = (
        _clamp(len(baseline) / _BASELINE_DAYS, _BASELINE_FLOOR, 1.0)
        if volume_ratio is not None
        else 1.0
    )
    confidence = round(
        completeness * history_factor * benchmark_factor * freshness_factor * baseline_factor,
        4,
    )

    return FeatureSet(
        symbol=symbol,
        as_of=as_of,
        n_days=n,
        last_price=closes[-1],
        dollar_volume_median_20d=dollar_volume_median_20d,
        return_1d=return_1d,
        return_5d=return_5d,
        intraday_return=intraday_return,
        relative_strength_1d=relative_strength_1d,
        volume_ratio=volume_ratio,
        realized_vol_20d=realized_vol_20d,
        benchmark_available=benchmark_available,
        completeness=completeness,
        confidence=confidence,
    )
