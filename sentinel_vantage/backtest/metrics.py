"""Deterministic metrics for backtesting: rank correlation and quantile buckets."""

from __future__ import annotations

import statistics
from collections.abc import Sequence


def _average_ranks(values: Sequence[float]) -> list[float]:
    """1-based ranks with ties assigned their average rank."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(values):
        j = i
        while j + 1 < len(values) and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def _pearson(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    n = len(xs)
    if n < 2:
        return None
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True))
    vx = sum((x - mx) ** 2 for x in xs)
    vy = sum((y - my) ** 2 for y in ys)
    if vx == 0 or vy == 0:
        return None
    return cov / (vx * vy) ** 0.5


def spearman(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    """Rank (Spearman) correlation — the information coefficient (IC)."""
    if len(xs) < 2:
        return None
    return _pearson(_average_ranks(xs), _average_ranks(ys))


def assign_buckets(scored: Sequence[tuple[str, float]], n_buckets: int) -> dict[str, int]:
    """Split symbols into equal-count quantile buckets by score (0 = lowest), breaking ties
    by symbol for determinism."""
    order = sorted(scored, key=lambda t: (t[1], t[0]))
    m = len(order)
    out: dict[str, int] = {}
    for idx, (symbol, _) in enumerate(order):
        out[symbol] = min(n_buckets - 1, idx * n_buckets // m)
    return out
