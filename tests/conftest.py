"""Shared test fixtures: deterministic synthetic bar builders."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sentinel_vantage.providers.base import Bar


def make_daily_bars(
    symbol: str,
    closes: list[float],
    volumes: list[float] | None = None,
    *,
    start: str = "2026-03-02",
    provider: str = "test",
    feed: str = "test/fixture",
) -> list[Bar]:
    """Build consecutive daily bars from a close series (open = previous close)."""
    if volumes is None:
        volumes = [1_000_000.0] * len(closes)
    assert len(closes) == len(volumes)

    d0 = datetime.fromisoformat(start).replace(tzinfo=UTC)
    bars: list[Bar] = []
    prev = closes[0]
    for i, (c, v) in enumerate(zip(closes, volumes, strict=True)):
        o = prev
        bars.append(
            Bar(
                symbol=symbol,
                ts=d0 + timedelta(days=i),
                timeframe="1d",
                open=o,
                high=max(o, c) * 1.01,
                low=min(o, c) * 0.99,
                close=c,
                volume=v,
                provider=provider,
                feed=feed,
            )
        )
        prev = c
    return bars


def flat_series(value: float, n: int) -> list[float]:
    return [value] * n


def as_of_of(bars: list[Bar]) -> datetime:
    return bars[-1].ts
