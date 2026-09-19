"""Feature set produced from a symbol's bar history.

Phase 1 computes the five features from Appendix A over daily bars for the ``1d``
horizon. Every field needed by the eligibility gates and by cross-sectional scoring is
carried here, along with a ``confidence`` derived from data completeness — so a partial
input can never masquerade as a normal-confidence result (design section 11).
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class FeatureSet(BaseModel):
    symbol: str
    as_of: datetime
    n_days: int

    # Gate inputs
    last_price: float
    dollar_volume_median_20d: float | None = None

    # Scoring factors (None = not computable from available history)
    return_1d: float | None = None
    return_5d: float | None = None
    intraday_return: float | None = None
    relative_strength_1d: float | None = None
    volume_ratio: float | None = None
    realized_vol_20d: float | None = None

    benchmark_available: bool = False
    # Fraction of the five scoring factors that were computable.
    completeness: float = 0.0
    # 0-1 data confidence carried onto the score.
    confidence: float = 0.0
