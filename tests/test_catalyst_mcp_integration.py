"""explain_move over real Postgres (events + bars), gated by SV_RUN_DB_TESTS."""

from __future__ import annotations

import json
import os

import pytest
from conftest import make_daily_bars

from sentinel_vantage.apps.mcp_server.dependencies import MCPResources
from sentinel_vantage.apps.mcp_server.server import build_server
from sentinel_vantage.core.config import Settings
from sentinel_vantage.domain.catalysts.models import Event
from sentinel_vantage.domain.market.universe import seed_universe
from sentinel_vantage.providers.base import Bar
from sentinel_vantage.storage.migrate import apply_migrations
from sentinel_vantage.storage.postgres_repos import PostgresEventRepository

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


async def test_explain_move_over_postgres():
    settings = Settings(postgres_dsn=PG_DSN, redis_url=REDIS_URL)
    await apply_migrations(PG_DSN)
    res = MCPResources.build(settings)
    await res.connect()
    try:
        await res.db.pool.execute("TRUNCATE security, market_bar, event")
        await seed_universe(res.db)
        bars = make_daily_bars("NVDA", [100.0] * 30 + [113.0], [1_000_000.0] * 30 + [4_000_000.0])
        await _insert_bars(res.db, bars)
        spike_ts = bars[-1].ts
        await PostgresEventRepository(res.db).save_events(
            [
                Event(
                    event_id="acc-x",
                    symbol="NVDA",
                    cik="C1",
                    type="FILING_8K",
                    event_time=spike_ts,
                    title="8-K — Results",
                    url="https://sec.gov/x",
                )
            ]
        )

        server = build_server(settings, resources=res)
        result = await server.call_tool("explain_move", {"symbol": "nvda", "lookback_days": 20})
        assert not result.is_error
        payload = json.loads(result.content[0].text)
        assert payload["provenance"]["model_version"] == "catalyst-v0"
        data = payload["data"]
        assert data["move"]["direction"] == "up"
        assert round(data["move"]["return_pct"], 0) == 13
        assert data["catalysts"][0]["event_type"] == "FILING_8K"
        assert data["causal_confidence"] == "strong"
        assert "not proven causes" in data["disclaimer"]
    finally:
        await res.close()
