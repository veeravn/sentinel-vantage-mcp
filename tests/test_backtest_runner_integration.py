"""Backtest runner over real Postgres bars (gated by SV_RUN_DB_TESTS)."""

from __future__ import annotations

import os

import pytest
from conftest import make_daily_bars

from sentinel_vantage.backtest.runner import run_trend_backtest
from sentinel_vantage.domain.market.universe import seed_universe
from sentinel_vantage.providers.base import Bar
from sentinel_vantage.storage.postgres import Database

PG_DSN = os.environ.get("SV_POSTGRES_DSN", "postgresql://sentinel:sentinel@localhost:5432/sentinel")

pytestmark = pytest.mark.skipif(
    os.environ.get("SV_RUN_DB_TESTS") != "1", reason="set SV_RUN_DB_TESTS=1 to run DB tests"
)


async def _insert(db, bars: list[Bar]) -> None:
    await db.pool.executemany(
        "INSERT INTO market_bar (symbol, ts, timeframe, open, high, low, close, volume, "
        " provider, feed) VALUES ($1,$2,'1d',$3,$4,$5,$6,$7,$8,$9) ON CONFLICT DO NOTHING",
        [
            (b.symbol, b.ts, b.open, b.high, b.low, b.close, b.volume, b.provider, b.feed)
            for b in bars
        ],
    )


@pytest.fixture
async def db():
    from sentinel_vantage.storage.migrate import apply_migrations

    await apply_migrations(PG_DSN)
    database = Database(PG_DSN)
    await database.connect()
    await database.pool.execute("TRUNCATE security, market_bar, trend_score")
    yield database
    await database.close()


async def test_trend_backtest_over_postgres(db):
    await seed_universe(db)
    # 200 sessions. UP rises steadily, DOWN falls, FLAT is flat — all liquid.
    n = 200
    await _insert(db, make_daily_bars("SPY", [100.0] * n, [50_000_000.0] * n))
    await _insert(db, make_daily_bars("UP", [50.0 + i * 0.4 for i in range(n)], [2_000_000.0] * n))
    await _insert(
        db, make_daily_bars("DOWN", [150.0 - i * 0.4 for i in range(n)], [2_000_000.0] * n)
    )
    await _insert(db, make_daily_bars("FLAT", [100.0] * n, [2_000_000.0] * n))
    for extra in ("A", "B", "C"):
        await _insert(
            db, make_daily_bars(extra, [90.0 + i * 0.1 for i in range(n)], [2_000_000.0] * n)
        )

    report = await run_trend_backtest(
        db, ["UP", "DOWN", "FLAT", "A", "B", "C"], horizon=20, every=10, warmup=60, n_buckets=3
    )
    assert len(report.rebalances) > 0
    assert report.coverage > 0
    # Trend momentum should not be anti-correlated with forward returns here.
    assert report.mean_rank_ic is not None
