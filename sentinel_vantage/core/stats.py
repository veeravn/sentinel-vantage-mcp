"""Small deterministic stats helpers for cross-sectional scoring."""

from __future__ import annotations

import math
import statistics
from collections.abc import Mapping


def sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def winsorize(z: float, cap: float = 3.0) -> float:
    return max(-cap, min(cap, z))


def zscores(raw_by_symbol: Mapping[str, float | None], *, cap: float = 3.0) -> dict[str, float]:
    """Cross-sectional winsorized z-scores. Missing values map to a neutral 0.0."""
    present = {s: v for s, v in raw_by_symbol.items() if v is not None}
    out = {s: 0.0 for s in raw_by_symbol}
    if len(present) < 2:
        return out
    mean = statistics.fmean(present.values())
    stdev = statistics.pstdev(present.values())
    if stdev == 0:
        return out
    for s, v in present.items():
        out[s] = winsorize((v - mean) / stdev, cap)
    return out
