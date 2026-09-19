"""Wire the backtest engine to real stored data.

Loads full daily history once, then drives the engine with point-in-time score
functions (the trend/research services, which already honor ``as_of``) and a
forward-return function derived from future bars. Forward returns are the one place a
backtest legitimately looks past ``as_of`` — because ``as_of`` is historical, that
"future" is still in the past relative to now.
"""

from __future__ import annotations

import bisect
from collections.abc import Sequence
from datetime import datetime

from sentinel_vantage.backtest.core import BacktestReport, ForwardReturnFn, ScoreFn, run_backtest
from sentinel_vantage.domain.research.ports import FundamentalRepository
from sentinel_vantage.domain.research.service import ResearchService
from sentinel_vantage.domain.trend.service import TrendService
from sentinel_vantage.providers.base import Bar
from sentinel_vantage.storage.memory import InMemoryBarRepository
from sentinel_vantage.storage.postgres import Database

BENCHMARK = "SPY"


class _Series:
    def __init__(self, bars: Sequence[Bar]) -> None:
        ordered = sorted(bars, key=lambda b: b.ts)
        self.ts = [b.ts for b in ordered]
        self.close = [b.close for b in ordered]

    def forward_return(self, as_of: datetime, horizon: int) -> float | None:
        i = bisect.bisect_right(self.ts, as_of) - 1
        if i < 0:
            return None
        j = i + horizon
        if j >= len(self.close) or self.close[i] == 0:
            return None
        return self.close[j] / self.close[i] - 1.0


async def load_daily_histories(db: Database, symbols: Sequence[str]) -> dict[str, list[Bar]]:
    rows = await db.pool.fetch(
        "SELECT symbol, ts, open, high, low, close, volume, provider, feed "
        "FROM market_bar WHERE symbol = ANY($1::text[]) AND timeframe = '1d' ORDER BY symbol, ts",
        list(symbols),
    )
    out: dict[str, list[Bar]] = {}
    for r in rows:
        out.setdefault(r["symbol"], []).append(
            Bar(
                symbol=r["symbol"],
                ts=r["ts"],
                timeframe="1d",
                open=r["open"],
                high=r["high"],
                low=r["low"],
                close=r["close"],
                volume=r["volume"],
                provider=r["provider"],
                feed=r["feed"],
            )
        )
    return out


def rebalance_dates(
    histories: dict[str, list[Bar]], *, every: int, warmup: int, horizon: int
) -> list[datetime]:
    """Trading dates (from the benchmark calendar) spaced ``every`` trading days,
    starting after ``warmup`` and leaving ``horizon`` days of future room at the end."""
    cal = sorted({b.ts for b in histories.get(BENCHMARK, [])})
    if not cal:
        cal = sorted({b.ts for bars in histories.values() for b in bars})
    usable = cal[warmup : len(cal) - horizon]
    return usable[::every]


def forward_return_fn(histories: dict[str, list[Bar]], horizon: int) -> ForwardReturnFn:
    series = {s: _Series(b) for s, b in histories.items()}

    async def _fn(symbol: str, as_of: datetime) -> float | None:
        ser = series.get(symbol)
        return ser.forward_return(as_of, horizon) if ser else None

    return _fn


def trend_score_fn(histories: dict[str, list[Bar]], *, min_confidence: float) -> ScoreFn:
    repo = InMemoryBarRepository(histories, benchmark_symbol=BENCHMARK)
    service = TrendService(repo)

    async def _fn(as_of: datetime) -> dict[str, float]:
        scan = await service.scan(as_of=as_of, limit=10**9, min_confidence=min_confidence)
        return {r.symbol: r.score for r in scan.results}

    return _fn


def research_score_fn(
    histories: dict[str, list[Bar]],
    fundamentals: FundamentalRepository,
    *,
    strategy: str,
    min_confidence: float,
) -> ScoreFn:
    repo = InMemoryBarRepository(histories, benchmark_symbol=BENCHMARK)
    service = ResearchService(repo, fundamentals)

    async def _fn(as_of: datetime) -> dict[str, float]:
        rank = await service.rank(strategy, as_of=as_of, limit=10**9, min_confidence=min_confidence)
        return {r.symbol: r.score for r in rank.results}

    return _fn


async def run_trend_backtest(
    db: Database,
    symbols: Sequence[str],
    *,
    horizon: int = 20,
    every: int = 5,
    warmup: int = 60,
    n_buckets: int = 5,
    min_confidence: float = 0.0,
) -> BacktestReport:
    histories = await load_daily_histories(db, [BENCHMARK, *symbols])
    dates = rebalance_dates(histories, every=every, warmup=warmup, horizon=horizon)
    return await run_backtest(
        strategy="trend-v0",
        rebalance_dates=dates,
        score_fn=trend_score_fn(histories, min_confidence=min_confidence),
        forward_return_fn=forward_return_fn(histories, horizon),
        horizon_days=horizon,
        n_buckets=n_buckets,
        universe_size=len(symbols),
    )


async def run_research_backtest(
    db: Database,
    symbols: Sequence[str],
    fundamentals: FundamentalRepository,
    *,
    strategy: str = "GARP",
    horizon: int = 60,
    every: int = 20,
    warmup: int = 60,
    n_buckets: int = 5,
    min_confidence: float = 0.0,
) -> BacktestReport:
    histories = await load_daily_histories(db, [BENCHMARK, *symbols])
    dates = rebalance_dates(histories, every=every, warmup=warmup, horizon=horizon)
    return await run_backtest(
        strategy=strategy,
        rebalance_dates=dates,
        score_fn=research_score_fn(
            histories, fundamentals, strategy=strategy, min_confidence=min_confidence
        ),
        forward_return_fn=forward_return_fn(histories, horizon),
        horizon_days=horizon,
        n_buckets=n_buckets,
        universe_size=len(symbols),
    )
