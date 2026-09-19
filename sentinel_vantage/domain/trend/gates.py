"""Eligibility gates (design section 10.1).

Scores are produced only when minimum data-quality and investability gates pass. A
failing symbol is *ineligible* — it is excluded from scoring and reported with its gate
failures, never given a zero-but-normal-confidence score. Thresholds are versioned
config so they can evolve deliberately.
"""

from __future__ import annotations

from pydantic import BaseModel

from sentinel_vantage.domain.features.models import FeatureSet


class TrendGateConfig(BaseModel):
    min_price: float = 3.0
    min_dollar_volume_median_20d: float = 10_000_000.0
    min_history_days: int = 60


DEFAULT_GATES = TrendGateConfig()

# Gate failure reason codes.
GATE_PRICE = "GATE_PRICE_BELOW_MIN"
GATE_LIQUIDITY = "GATE_LIQUIDITY_BELOW_MIN"
GATE_HISTORY = "GATE_INSUFFICIENT_HISTORY"
GATE_MISSING_DATA = "GATE_MISSING_RECENT_DATA"
GATE_INACTIVE = "GATE_INACTIVE_LISTING"


def evaluate_gates(
    features: FeatureSet,
    *,
    is_active: bool = True,
    config: TrendGateConfig = DEFAULT_GATES,
):
    """Return an Eligibility for the symbol. Pure and deterministic."""
    from sentinel_vantage.domain.trend.models import Eligibility  # avoid circular import

    failures: list[str] = []

    if not is_active:
        failures.append(GATE_INACTIVE)
    if features.n_days < config.min_history_days:
        failures.append(GATE_HISTORY)
    if features.last_price < config.min_price:
        failures.append(GATE_PRICE)
    if (
        features.dollar_volume_median_20d is None
        or features.dollar_volume_median_20d < config.min_dollar_volume_median_20d
    ):
        failures.append(GATE_LIQUIDITY)
    # Core recent-data check: without a 1d return or a volume ratio the symbol cannot be
    # scored honestly at this horizon (acceptance test AT-2).
    if features.return_1d is None or features.volume_ratio is None:
        failures.append(GATE_MISSING_DATA)

    return Eligibility(symbol=features.symbol, eligible=not failures, gate_failures=failures)
