"""MCP tools over the real Postgres/Redis wiring (gated by SV_RUN_DB_TESTS).

Exercises the actual tool functions through MCPResources: the cold-cache compute path,
the warm Redis fast path after a worker cycle, and get_status health.
"""

from __future__ import annotations

import json
import os

import pytest
from conftest import make_daily_bars

from sentinel_vantage.apps.market_worker.scoring import run_scoring_cycle
from sentinel_vantage.apps.mcp_server.dependencies import MCPResources
from sentinel_vantage.apps.mcp_server.server import build_server
from sentinel_vantage.core.config import Settings
from sentinel_vantage.domain.market.universe import seed_universe
from sentinel_vantage.providers.base import Bar
from sentinel_vantage.storage.migrate import apply_migrations

PG_DSN = os.environ.get("SV_POSTGRES_DSN", "postgresql://sentinel:sentinel@localhost:5432/sentinel")
REDIS_URL = os.environ.get("SV_REDIS_URL", "redis://localhost:6379/0")

pytestmark = pytest.mark.skipif(
    os.environ.get("SV_RUN_DB_TESTS") != "1", reason="set SV_RUN_DB_TESTS=1 to run DB tests"
)


async def _insert_bars(db, bars: list[Bar]) -> None:
    await db.pool.executemany(
        "INSERT INTO market_bar (symbol, ts, timeframe, open, high, low, close, volume, "
        " provider, feed) VALUES ($1,$2,'1d',$3,$4,$5,$6,$7,$8,$9) ON CONFLICT DO NOTHING",
        [
            (b.symbol, b.ts, b.open, b.high, b.low, b.close, b.volume, b.provider, b.feed)
            for b in bars
        ],
    )


def _payload(result):
    assert not result.is_error
    return json.loads(result.content[0].text)


async def test_mcp_tools_over_postgres_and_redis():
    settings = Settings(postgres_dsn=PG_DSN, redis_url=REDIS_URL)
    await apply_migrations(PG_DSN)
    res = MCPResources.build(settings)
    await res.connect()
    try:
        await res.db.pool.execute("TRUNCATE security, market_bar, feature_snapshot, trend_score")
        await res.redis.client.flushdb()
        await seed_universe(res.db)
        await _insert_bars(res.db, make_daily_bars("SPY", [100.0] * 70, [50_000_000.0] * 70))
        await _insert_bars(
            res.db, make_daily_bars("NVDA", [100.0] * 69 + [118.0], [1_000_000.0] * 69 + [5e6])
        )
        await _insert_bars(
            res.db, make_daily_bars("AAPL", [100.0] * 69 + [101.0], [1_000_000.0] * 70)
        )

        server = build_server(settings, resources=res)

        # Cold cache -> recompute from Postgres.
        cold = _payload(await server.call_tool("scan_trending_stocks", {"limit": 10}))
        assert cold["data"]["source"] == "compute"
        assert cold["data"]["results"][0]["symbol"] == "NVDA"
        assert cold["provenance"]["feed"] == "polygon/delayed"

        # Warm the Redis cache via a worker cycle, then the tool reads the fast path.
        as_of = await res.service.bars.latest_bar_ts()
        await run_scoring_cycle(res.service, res.rank_cache, horizon="1d", as_of=as_of)
        warm = _payload(await server.call_tool("scan_trending_stocks", {"limit": 10}))
        assert warm["data"]["source"] == "cache"
        assert warm["data"]["results"][0]["symbol"] == "NVDA"

        analysis = _payload(await server.call_tool("analyze_stock", {"symbol": "nvda"}))
        assert analysis["data"]["eligible"] is True

        # history reads persisted snapshots written by the cycle (fixture dates are old,
        # so pass an explicit start; the default trailing-30d window fits live data).
        hist = _payload(
            await server.call_tool("get_score_history", {"symbol": "NVDA", "start": "2026-01-01"})
        )
        assert len(hist["data"]["history"]) >= 1

        status = _payload(await server.call_tool("get_status", {}))
        assert status["data"]["health"]["status"] == "ok"
    finally:
        await res.close()
