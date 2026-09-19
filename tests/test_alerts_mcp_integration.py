"""Alert/watchlist/brief MCP tools over real Postgres (gated by SV_RUN_DB_TESTS)."""

from __future__ import annotations

import json
import os

import pytest
from conftest import make_daily_bars

from sentinel_vantage.apps.mcp_server.dependencies import MCPResources
from sentinel_vantage.apps.mcp_server.server import build_server
from sentinel_vantage.core.config import Settings
from sentinel_vantage.domain.alerts.engine import AlertEngine
from sentinel_vantage.domain.alerts.resolver import MetricResolver
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


async def test_alert_watchlist_brief_flow():
    settings = Settings(postgres_dsn=PG_DSN, redis_url=REDIS_URL)
    await apply_migrations(PG_DSN)
    res = MCPResources.build(settings)
    await res.connect()
    try:
        await res.db.pool.execute(
            "TRUNCATE security, market_bar, watchlist, alert_rule, alert_event"
        )
        await seed_universe(res.db)
        await _insert_bars(res.db, make_daily_bars("SPY", [100.0] * 70, [50_000_000.0] * 70))
        await _insert_bars(
            res.db,
            make_daily_bars("NVDA", [100.0] * 69 + [108.0], [1_000_000.0] * 69 + [4_000_000.0]),
        )
        await _insert_bars(res.db, make_daily_bars("AAPL", [100.0] * 70, [1_000_000.0] * 70))

        server = build_server(settings, resources=res)

        # Create a watchlist and a rule on abnormal volume.
        wl = _payload(
            await server.call_tool(
                "create_watchlist", {"name": "mine", "symbols": ["NVDA", "AAPL"]}
            )
        )
        wl_id = wl["data"]["watchlist_id"]
        rule = _payload(
            await server.call_tool(
                "create_alert_rule",
                {
                    "all_conditions": ["volume_ratio >= 2.0"],
                    "watchlist_id": wl_id,
                    "severity": "warning",
                },
            )
        )
        assert rule["data"]["rule"]["all"][0]["metric"] == "volume_ratio"

        # The scheduler's engine evaluates rules (run once here).
        engine = AlertEngine(
            res.alert_rules,
            res.alert_events,
            MetricResolver(res.service),
            watchlists=res.watchlists,
        )
        fired = await engine.run_once()
        assert {e.symbol for e in fired} == {"NVDA"}  # only NVDA has abnormal volume

        # list_alert_events surfaces it.
        events = _payload(await server.call_tool("list_alert_events", {}))
        assert any(e["symbol"] == "NVDA" for e in events["data"]["events"])

        # get_market_brief returns top trending.
        brief = _payload(await server.call_tool("get_market_brief", {"top": 3}))
        assert brief["data"]["top_trending"]

        # get_watchlist_changes runs (no prior history -> deltas may be null, but shape holds).
        changes = _payload(await server.call_tool("get_watchlist_changes", {"watchlist_id": wl_id}))
        assert {c["symbol"] for c in changes["data"]["changes"]} == {"NVDA", "AAPL"}
    finally:
        await res.close()
