"""trend-v0 scoring.

The Trend Score is a percentile-normalized, horizon-specific signal. Each factor is
winsorized and z-scored *cross-sectionally* across the eligible universe, combined with
fixed weights, and squashed through a sigmoid to 0-100 (design section 10.2).

trend-v0 uses the four factors computable from the Phase 1 feature set. Attention
velocity and catalyst strength (design factors) arrive with news/catalyst data in a
later phase; adding them will create trend-v1, not mutate trend-v0. Realized volatility
and extreme moves are surfaced as risk flags, not as positive score contributors.

Determinism: pure functions, stable ordering, rounded outputs. Same inputs -> same
scores, which is what the replay/acceptance test AT-1 verifies.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Mapping
from datetime import datetime

from pydantic import BaseModel

from sentinel_vantage.core.versioning import TREND_MODEL_VERSION
from sentinel_vantage.domain.features.models import FeatureSet
from sentinel_vantage.domain.trend.models import TrendResult

# Fixed weights (trend-v0). Sum to 1.0.
TREND_V0_WEIGHTS: dict[str, float] = {
    "momentum": 0.35,
    "volume": 0.30,
    "relative_strength": 0.25,
    "acceleration": 0.10,
}

WINSOR_Z = 3.0


class TrendScoringConfig(BaseModel):
    # Reason-code thresholds (in z units unless noted).
    volume_hot_z: float = 1.5
    volume_cold_z: float = -1.5
    rs_strong_z: float = 1.0
    rs_weak_z: float = -1.0
    momentum_strong_z: float = 1.0
    momentum_weak_z: float = -1.0
    acceleration_breakout_z: float = 1.0
    # Risk-flag thresholds (raw units).
    extended_move_abs_return_1d: float = 0.15  # +/-15% in a day
    high_realized_vol_20d: float = 0.05  # 5% daily stdev


DEFAULT_SCORING = TrendScoringConfig()


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def _winsorize(z: float) -> float:
    return max(-WINSOR_Z, min(WINSOR_Z, z))


def _momentum_raw(fs: FeatureSet) -> float | None:
    if fs.return_1d is None and fs.return_5d is None:
        return None
    if fs.return_5d is None:
        return fs.return_1d
    if fs.return_1d is None:
        return fs.return_5d
    # Blend horizons so a single bar cannot dominate (design note).
    return 0.6 * fs.return_1d + 0.4 * fs.return_5d


def _factor_raw(fs: FeatureSet) -> dict[str, float | None]:
    return {
        "momentum": _momentum_raw(fs),
        "volume": fs.volume_ratio,
        "relative_strength": fs.relative_strength_1d,
        "acceleration": fs.intraday_return,
    }


def _zscores(raw_by_symbol: Mapping[str, float | None]) -> dict[str, float]:
    """Cross-sectional z-score for one factor. Missing values -> neutral 0.0."""
    present = {s: v for s, v in raw_by_symbol.items() if v is not None}
    out = {s: 0.0 for s in raw_by_symbol}
    if len(present) < 2:
        return out
    values = list(present.values())
    mean = statistics.fmean(values)
    stdev = statistics.pstdev(values)
    if stdev == 0:
        return out
    for s, v in present.items():
        out[s] = _winsorize((v - mean) / stdev)
    return out


def _reasons(factor_z: Mapping[str, float], cfg: TrendScoringConfig) -> list[str]:
    reasons: list[str] = []
    if factor_z["volume"] >= cfg.volume_hot_z:
        reasons.append("ABNORMAL_VOLUME")
    elif factor_z["volume"] <= cfg.volume_cold_z:
        reasons.append("BELOW_AVERAGE_VOLUME")
    if factor_z["relative_strength"] >= cfg.rs_strong_z:
        reasons.append("STRONG_RELATIVE_STRENGTH")
    elif factor_z["relative_strength"] <= cfg.rs_weak_z:
        reasons.append("WEAK_RELATIVE_STRENGTH")
    if factor_z["momentum"] >= cfg.momentum_strong_z:
        reasons.append("STRONG_MOMENTUM")
    elif factor_z["momentum"] <= cfg.momentum_weak_z:
        reasons.append("NEGATIVE_MOMENTUM")
    if factor_z["acceleration"] >= cfg.acceleration_breakout_z:
        reasons.append("INTRADAY_BREAKOUT")
    return reasons


def _risk_flags(fs: FeatureSet, cfg: TrendScoringConfig) -> list[str]:
    flags: list[str] = []
    if fs.return_1d is not None and abs(fs.return_1d) >= cfg.extended_move_abs_return_1d:
        flags.append("EXTENDED_SHORT_TERM_MOVE")
    if fs.realized_vol_20d is not None and fs.realized_vol_20d >= cfg.high_realized_vol_20d:
        flags.append("HIGH_VOLATILITY")
    return flags


def _metrics(fs: FeatureSet) -> dict[str, float]:
    out: dict[str, float] = {}
    if fs.return_1d is not None:
        out["return_1d_pct"] = round(fs.return_1d * 100, 4)
    if fs.return_5d is not None:
        out["return_5d_pct"] = round(fs.return_5d * 100, 4)
    if fs.relative_strength_1d is not None:
        out["relative_strength_1d_pct"] = round(fs.relative_strength_1d * 100, 4)
    if fs.volume_ratio is not None:
        out["volume_ratio"] = round(fs.volume_ratio, 4)
    if fs.realized_vol_20d is not None:
        out["realized_vol_20d"] = round(fs.realized_vol_20d, 6)
    return out


def score_universe(
    features_by_symbol: Mapping[str, FeatureSet],
    *,
    horizon: str,
    as_of: datetime,
    config: TrendScoringConfig = DEFAULT_SCORING,
) -> list[TrendResult]:
    """Score every eligible symbol cross-sectionally. Returns results sorted by score desc."""
    symbols = sorted(features_by_symbol)  # stable ordering for determinism
    if not symbols:
        return []

    # One z-map per factor across the universe.
    z_by_factor = {
        factor: _zscores({s: _factor_raw(features_by_symbol[s])[factor] for s in symbols})
        for factor in TREND_V0_WEIGHTS
    }

    results: list[TrendResult] = []
    for s in symbols:
        fs = features_by_symbol[s]
        factor_z = {factor: round(z_by_factor[factor][s], 6) for factor in TREND_V0_WEIGHTS}
        linear = sum(TREND_V0_WEIGHTS[f] * factor_z[f] for f in TREND_V0_WEIGHTS)
        score = round(100.0 * _sigmoid(linear), 4)
        results.append(
            TrendResult(
                symbol=s,
                horizon=horizon,
                as_of=as_of,
                score=score,
                confidence=fs.confidence,
                metrics=_metrics(fs),
                factor_z=factor_z,
                reasons=_reasons(factor_z, config),
                risk_flags=_risk_flags(fs, config),
                model_version=TREND_MODEL_VERSION,
            )
        )

    # Percentile rank within the scored set (deterministic; ties share the lower rank).
    scores_sorted = sorted(r.score for r in results)
    n = len(scores_sorted)
    for r in results:
        below = sum(1 for v in scores_sorted if v < r.score)
        r.rank_percentile = round(100.0 * below / (n - 1), 4) if n > 1 else 100.0

    results.sort(key=lambda r: (-r.score, r.symbol))
    return results
