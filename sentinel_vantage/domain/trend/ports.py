"""Ports (Protocols) the trend service depends on, keeping the domain independent of the
storage and provider implementations that satisfy them."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol, runtime_checkable

from sentinel_vantage.domain.trend.models import TrendResult
from sentinel_vantage.providers.base import Bar


@runtime_checkable
class BarRepository(Protocol):
    """Source of the universe and its daily bar history for a point in time."""

    benchmark_symbol: str

    async def list_active_universe(
        self, as_of: datetime, *, sector: str | None = None
    ) -> list[str]: ...

    async def get_daily_history(
        self, symbols: Sequence[str], as_of: datetime, *, lookback_days: int
    ) -> dict[str, list[Bar]]: ...

    async def is_active(self, symbol: str, as_of: datetime) -> bool: ...

    async def latest_bar_ts(self, *, timeframe: str = "1d") -> datetime | None: ...


@runtime_checkable
class ScoreRepository(Protocol):
    """Persistence for immutable trend-score snapshots and history reads."""

    async def save_trend_scores(self, results: Sequence[TrendResult]) -> None: ...

    async def get_trend_history(
        self, symbol: str, *, horizon: str, start: datetime, end: datetime
    ) -> list[TrendResult]: ...
