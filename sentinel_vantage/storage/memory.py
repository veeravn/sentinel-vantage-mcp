"""In-memory repositories.

Back the trend service without a live database — used by tests and as the default MCP
wiring until the Postgres/Redis and Polygon implementations land. They satisfy the same
ports (BarRepository, ScoreRepository), so swapping in the durable versions changes no
domain or MCP code.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime

from sentinel_vantage.domain.features.models import FeatureSet
from sentinel_vantage.domain.trend.models import TrendResult
from sentinel_vantage.providers.base import Bar, FundamentalFact


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

    async def latest_bar_ts(self, *, timeframe: str = "1d") -> datetime | None:
        all_ts = [b.ts for bars in self._histories.values() for b in bars]
        return max(all_ts) if all_ts else None


class InMemoryFeatureRepository:
    def __init__(self) -> None:
        self.saved: list[tuple[str, FeatureSet]] = []

    async def save_feature_snapshots(
        self, features: Sequence[FeatureSet], *, feature_set_version: str
    ) -> None:
        for fs in features:
            self.saved.append((feature_set_version, fs))


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


class InMemoryFundamentalRepository:
    def __init__(
        self,
        ciks: dict[str, str] | None = None,
        facts: dict[str, list[FundamentalFact]] | None = None,
    ) -> None:
        self._ciks = ciks or {}
        self._facts = facts or {}

    def set_cik(self, symbol: str, cik: str) -> None:
        self._ciks[symbol] = cik

    def set_facts(self, cik: str, facts: list[FundamentalFact]) -> None:
        self._facts[cik] = facts

    async def cik_for(self, symbol: str) -> str | None:
        return self._ciks.get(symbol)

    async def get_facts_asof(
        self, cik: str, tags: Sequence[str], as_of: date
    ) -> list[FundamentalFact]:
        wanted = set(tags)
        return [f for f in self._facts.get(cik, []) if f.tag in wanted and f.filed_at <= as_of]


class InMemoryResearchScoreRepository:
    def __init__(self) -> None:
        self._snapshots: dict[tuple[str, str], list] = {}

    async def save_research_scores(self, results) -> None:
        for r in results:
            self._snapshots.setdefault((r.symbol, r.strategy), []).append(r)

    async def get_research_history(self, symbol, *, strategy, start, end):
        snaps = self._snapshots.get((symbol, strategy), [])
        return sorted((r for r in snaps if start <= r.as_of <= end), key=lambda r: r.as_of)
