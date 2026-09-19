"""research-v1 scoring for a single strategy.

Per-strategy, not a universal buy score (design section 10.3). Each factor is a family
of metrics with a direction (higher- or lower-is-better); every metric is z-scored
cross-sectionally across the eligible universe, signed by its direction, and averaged
into a factor z. Factor scores (sigmoid of the factor z, 0-1) are combined with the
strategy weights into a 0-100 weighted factor score, then risk penalties (in points)
are subtracted:

    ResearchCandidateScore = clamp(WeightedFactorScore - RiskPenalty, 0, 100)

Deterministic: pure functions, stable ordering, rounded outputs.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

from pydantic import BaseModel

from sentinel_vantage.core.stats import sigmoid, zscores
from sentinel_vantage.domain.research.models import Fundamentals, ResearchResult
from sentinel_vantage.domain.research.strategy import StrategyProfile

# Each factor -> list of (metric attribute on Fundamentals, direction). +1 higher-better.
FACTOR_METRICS: dict[str, list[tuple[str, int]]] = {
    "growth": [("revenue_growth_yoy", +1), ("eps_growth_yoy", +1)],
    "quality": [("gross_margin", +1), ("operating_margin", +1), ("roe", +1)],
    "valuation": [("pe", -1), ("ev_to_sales", -1)],
    "momentum": [("momentum_6m", +1)],
    "financial_strength": [("debt_to_equity", -1)],
}

_POS_Z = 0.75
_NEG_Z = -0.75
_REASON = {
    "growth": ("STRONG_GROWTH", "WEAK_GROWTH"),
    "quality": ("HIGH_QUALITY", "LOW_QUALITY"),
    "valuation": ("ATTRACTIVE_VALUATION", "EXPENSIVE_VALUATION"),
    "momentum": ("STRONG_MOMENTUM", "WEAK_MOMENTUM"),
    "financial_strength": ("STRONG_BALANCE_SHEET", "HIGH_LEVERAGE"),
}


class ResearchInputs(BaseModel):
    """Everything the engine needs for one symbol beyond the strategy config."""

    fundamentals: Fundamentals
    momentum_6m: float | None = None
    realized_vol_20d: float | None = None
    return_1d: float | None = None


def _metric_value(inp: ResearchInputs, attr: str) -> float | None:
    if attr == "momentum_6m":
        return inp.momentum_6m
    return getattr(inp.fundamentals, attr)


def _penalties(inp: ResearchInputs, profile: StrategyProfile) -> dict[str, float]:
    p, th = profile.penalties, profile.thresholds
    out: dict[str, float] = {}
    if (
        inp.realized_vol_20d is not None
        and inp.realized_vol_20d >= th.extreme_volatility_20d
        and p.extreme_volatility
    ):
        out["extreme_volatility"] = p.extreme_volatility
    if (
        inp.return_1d is not None
        and abs(inp.return_1d) >= th.extreme_short_term_move_1d
        and p.extreme_short_term_move
    ):
        out["extreme_short_term_move"] = p.extreme_short_term_move
    dte = inp.fundamentals.debt_to_equity
    if dte is not None and dte >= th.leverage_debt_to_equity and p.leverage:
        out["leverage"] = p.leverage
    return out


def score_research(
    inputs_by_symbol: Mapping[str, ResearchInputs],
    *,
    profile: StrategyProfile,
    as_of: datetime,
) -> list[ResearchResult]:
    symbols = sorted(inputs_by_symbol)
    if not symbols:
        return []

    # Cross-sectional z per underlying metric across the eligible universe.
    metric_names = {m for metrics in FACTOR_METRICS.values() for m, _ in metrics}
    z_by_metric = {
        name: zscores({s: _metric_value(inputs_by_symbol[s], name) for s in symbols})
        for name in metric_names
    }

    weights = profile.weights
    total_weight = sum(weights.get(f, 0.0) for f in FACTOR_METRICS) or 1.0

    results: list[ResearchResult] = []
    for s in symbols:
        inp = inputs_by_symbol[s]
        factor_z: dict[str, float] = {}
        covered_weight = 0.0
        for factor, metrics in FACTOR_METRICS.items():
            signed = [
                sign * z_by_metric[m][s] for m, sign in metrics if _metric_value(inp, m) is not None
            ]
            if signed:
                factor_z[factor] = round(sum(signed) / len(signed), 6)
                covered_weight += weights.get(factor, 0.0)
            else:
                factor_z[factor] = 0.0

        weighted = 100.0 * sum(weights.get(f, 0.0) * sigmoid(factor_z[f]) for f in FACTOR_METRICS)
        penalties = _penalties(inp, profile)
        score = max(0.0, min(100.0, round(weighted - sum(penalties.values()), 4)))

        pos = [_REASON[f][0] for f in FACTOR_METRICS if factor_z[f] >= _POS_Z]
        neg = [_REASON[f][1] for f in FACTOR_METRICS if factor_z[f] <= _NEG_Z]

        coverage = covered_weight / total_weight
        confidence = round(inp.fundamentals.data_confidence * coverage, 4)

        results.append(
            ResearchResult(
                symbol=s,
                strategy=profile.id,
                as_of=as_of,
                score=score,
                confidence=confidence,
                factors={f: round(sigmoid(factor_z[f]) * 100, 4) for f in FACTOR_METRICS},
                penalties=penalties,
                positive_reasons=pos,
                negative_reasons=neg,
                model_version=profile.score_version,
            )
        )

    scores_sorted = sorted(r.score for r in results)
    n = len(scores_sorted)
    for r in results:
        below = sum(1 for v in scores_sorted if v < r.score)
        r.rank_percentile = round(100.0 * below / (n - 1), 4) if n > 1 else 100.0

    results.sort(key=lambda r: (-r.score, r.symbol))
    return results
