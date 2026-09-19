"""Research hard gates (design section 10.3).

A strategy declares hard eligibility rules; a symbol failing any is ineligible for that
strategy and reported with its failures, never given a misleading score. Distinct from
the trend gates — a name can trend strongly yet fail a research gate (acceptance AT-3).
"""

from __future__ import annotations

from sentinel_vantage.domain.research.models import Fundamentals, ResearchEligibility
from sentinel_vantage.domain.research.strategy import StrategyProfile

GATE_PRICE = "GATE_PRICE_BELOW_MIN"
GATE_LIQUIDITY = "GATE_LIQUIDITY_BELOW_MIN"
GATE_DATA_CONFIDENCE = "GATE_LOW_DATA_CONFIDENCE"
GATE_MISSING_GROWTH = "GATE_MISSING_GROWTH"
GATE_GROWTH = "GATE_GROWTH_BELOW_MIN"


def evaluate_research_gates(
    fundamentals: Fundamentals,
    *,
    price: float | None,
    dollar_volume_median_20d: float | None,
    profile: StrategyProfile,
) -> ResearchEligibility:
    failures: list[str] = []
    u = profile.universe

    if price is None or price < u.min_price:
        failures.append(GATE_PRICE)
    if (
        dollar_volume_median_20d is None
        or dollar_volume_median_20d < u.min_median_dollar_volume_20d
    ):
        failures.append(GATE_LIQUIDITY)
    if fundamentals.data_confidence < profile.hard_gates.data_confidence_min:
        failures.append(GATE_DATA_CONFIDENCE)

    min_growth = profile.hard_gates.revenue_growth_yoy_min
    if min_growth is not None:
        if fundamentals.revenue_growth_yoy is None:
            failures.append(GATE_MISSING_GROWTH)
        elif fundamentals.revenue_growth_yoy < min_growth:
            failures.append(GATE_GROWTH)

    return ResearchEligibility(
        symbol=fundamentals.symbol, eligible=not failures, hard_gate_failures=failures
    )
