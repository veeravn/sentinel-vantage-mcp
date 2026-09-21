"""Feature set produced from a symbol's bar history, carrying a ``confidence`` derived
from data completeness so a partial input can't masquerade as a normal-confidence result."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class FeatureSet(BaseModel):
    symbol: str
    as_of: datetime
    n_days: int

    last_price: float
    dollar_volume_median_20d: float | None = None

    # Scoring factors (None = not computable from available history).
    return_1d: float | None = None
    return_5d: float | None = None
    intraday_return: float | None = None
    relative_strength_1d: float | None = None
    volume_ratio: float | None = None
    realized_vol_20d: float | None = None

    benchmark_available: bool = False
    completeness: float = 0.0
    confidence: float = 0.0
