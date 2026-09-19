"""Integration tests for the Postgres + Redis persistence layer.

Skipped unless SV_RUN_DB_TESTS=1 and a database/redis are reachable (CI sets this up
with service containers). They exercise migrations, the universe seed, and the
Postgres/Redis repositories against the real engines.
"""

from __future__ import annotations

import os

import pytest
from conftest import make_daily_bars

from sentinel_vantage.domain.market.universe import seed_universe
from sentinel_vantage.domain.trend.service import TrendService
from sentinel_vantage.providers.base import Bar
from sentinel_vantage.storage.postgres import Database
from sentinel_vantage.storage.postgres_repos import PostgresBarRepository, PostgresScoreRepository

PG_DSN = os.environ.get("SV_POSTGRES_DSN", "postgresql://sentinel:sentinel@localhost:5432/sentinel")
REDIS_URL = os.environ.get("SV_REDIS_URL", "redis://localhost:6379/0")
_ENABLED = os.environ.get("SV_RUN_DB_TESTS") == "1"

pytestmark = pytest.mark.skipif(not _ENABLED, reason="set SV_RUN_DB_TESTS=1 to run DB tests")


async def _insert_bars(db: Database, bars: list[Bar]) -> None:
    await db.pool.executemany(
        "INSERT INTO market_bar (symbol, ts, timeframe, open, high, low, close, volume, "
        " provider, feed) VALUES ($1,$2,'1d',$3,$4,$5,$6,$7,$8,$9) "
        "ON CONFLICT DO NOTHING",
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
    await database.pool.execute("TRUNCATE security, market_bar, feature_snapshot, trend_score")
    yield database
    await database.close()


async def test_seed_and_scan_over_postgres(db):
    await seed_universe(db)  # includes SPY (benchmark) + large caps

    # Enough liquid history for HOT and MID to pass the gates.
    await _insert_bars(db, make_daily_bars("SPY", [100.0] * 70, [50_000_000.0] * 70))
    await _insert_bars(
        db, make_daily_bars("NVDA", [100.0] * 69 + [118.0], [1_000_000.0] * 69 + [5_000_000.0])
    )
    await _insert_bars(db, make_daily_bars("AAPL", [100.0] * 69 + [101.0], [1_000_000.0] * 70))

    repo = PostgresBarRepository(db)
    universe = await repo.list_active_universe(make_daily_bars("X", [1.0])[0].ts.replace(year=2027))
    assert "SPY" not in universe  # benchmark excluded from scored universe
    assert {"NVDA", "AAPL"} <= set(universe)

    svc = TrendService(repo)
    as_of = make_daily_bars("SPY", [100.0] * 70)[-1].ts
    scan = await svc.scan(as_of=as_of, universe=["NVDA", "AAPL"], limit=10)
    assert [r.symbol for r in scan.results][0] == "NVDA"


async def test_score_snapshot_roundtrip(db):
    from sentinel_vantage.core.config import get_settings

    settings = get_settings()
    await seed_universe(db)
    await _insert_bars(db, make_daily_bars("SPY", [100.0] * 70, [50_000_000.0] * 70))
    await _insert_bars(
        db, make_daily_bars("NVDA", [100.0] * 69 + [118.0], [1_000_000.0] * 69 + [5_000_000.0])
    )
    await _insert_bars(db, make_daily_bars("AAPL", [100.0] * 69 + [101.0], [1_000_000.0] * 70))

    bars_repo = PostgresBarRepository(db)
    scores_repo = PostgresScoreRepository(
        db, provider=settings.provider_name, feed=settings.feed_label
    )
    svc = TrendService(bars_repo, scores=scores_repo)
    as_of = make_daily_bars("SPY", [100.0] * 70)[-1].ts

    # Two-symbol universe so cross-sectional reasons populate on NVDA.
    await svc.scan(as_of=as_of, universe=["NVDA", "AAPL"], persist=True)
    hist = await svc.score_history("NVDA", horizon="1d", start=as_of.replace(hour=0), end=as_of)
    assert len(hist) == 1
    assert hist[0].symbol == "NVDA"
    # JSONB list/dict columns survive the roundtrip.
    assert hist[0].risk_flags == ["EXTENDED_SHORT_TERM_MOVE"]
    assert hist[0].reasons
    assert set(hist[0].factor_z) == {"momentum", "volume", "relative_strength", "acceleration"}


async def test_redis_rank_cache_roundtrip():
    import redis.asyncio as aioredis

    from sentinel_vantage.storage.rank_cache import RedisRankCache
    from sentinel_vantage.storage.redis_store import RedisStore

    try:
        probe = aioredis.from_url(REDIS_URL)
        await probe.ping()
        await probe.aclose()
    except Exception:
        pytest.skip("redis not reachable")

    store = RedisStore(REDIS_URL)
    await store.connect()
    try:
        await store.client.flushdb()
        from sentinel_vantage.core.timeutils import utcnow
        from sentinel_vantage.domain.trend.models import TrendResult

        results = [
            TrendResult(
                symbol="NVDA",
                horizon="1d",
                as_of=utcnow(),
                score=90.0,
                confidence=0.9,
                model_version="trend-v0",
                reasons=["ABNORMAL_VOLUME"],
            ),
            TrendResult(
                symbol="AAPL",
                horizon="1d",
                as_of=utcnow(),
                score=60.0,
                confidence=0.9,
                model_version="trend-v0",
            ),
        ]
        cache = RedisRankCache(store)
        await cache.publish("1d", results)
        top = await cache.top("1d", limit=10)
        assert [r.symbol for r in top] == ["NVDA", "AAPL"]
        assert (await cache.latest("NVDA", "1d")).reasons == ["ABNORMAL_VOLUME"]
    finally:
        await store.close()
