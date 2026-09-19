"""In-memory repositories.

Back the trend service without a live database — used by tests and as the default MCP
wiring until the Postgres/Redis and Polygon implementations land. They satisfy the same
ports (BarRepository, ScoreRepository), so swapping in the durable versions changes no
domain or MCP code.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from sentinel_vantage.domain.trend.models import TrendResult
from sentinel_vantage.providers.base import Bar


class InMemoryBarRepository:
    benchmark_symbol: str = "SPY"

    def __init__(
        self,
        histories: dict[str, list[Bar]] | None = None,
        *,
        benchmark_symbol: str = "SPY",
        inactive: set[str] | None = None,
    ) -> None:
        self._histories = histories or {}
        self.benchmark_symbol = benchmark_symbol
        self._inactive = inactive or set()

    def set_history(self, symbol: str, bars: list[Bar]) -> None:
        self._histories[symbol] = bars

    async def list_active_universe(
        self, as_of: datetime, *, sector: str | None = None
    ) -> list[str]:
        return sorted(
            s for s in self._histories if s != self.benchmark_symbol and s not in self._inactive
        )

    async def get_daily_history(
        self, symbols: Sequence[str], as_of: datetime, *, lookback_days: int
    ) -> dict[str, list[Bar]]:
        out: dict[str, list[Bar]] = {}
        for s in symbols:
            bars = [b for b in self._histories.get(s, []) if b.ts <= as_of]
            if bars:
                out[s] = bars[-lookback_days:]
        return out

    async def is_active(self, symbol: str, as_of: datetime) -> bool:
        return symbol not in self._inactive


class InMemoryScoreRepository:
    def __init__(self) -> None:
        # keyed by (symbol, horizon) -> list of results ordered by as_of
        self._snapshots: dict[tuple[str, str], list[TrendResult]] = {}

    async def save_trend_scores(self, results: Sequence[TrendResult]) -> None:
        for r in results:
            self._snapshots.setdefault((r.symbol, r.horizon), []).append(r)

    async def get_trend_history(
        self, symbol: str, *, horizon: str, start: datetime, end: datetime
    ) -> list[TrendResult]:
        snaps = self._snapshots.get((symbol, horizon), [])
        return sorted((r for r in snaps if start <= r.as_of <= end), key=lambda r: r.as_of)
