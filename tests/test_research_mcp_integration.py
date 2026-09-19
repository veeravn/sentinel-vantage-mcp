"""Research MCP tools over real Postgres (gated by SV_RUN_DB_TESTS)."""

from __future__ import annotations

import json
import os
from datetime import date

import pytest
from conftest import make_daily_bars

from sentinel_vantage.apps.mcp_server.dependencies import MCPResources
from sentinel_vantage.apps.mcp_server.server import build_server
from sentinel_vantage.core.config import Settings
from sentinel_vantage.domain.market.universe import seed_universe
from sentinel_vantage.providers.base import Bar, FundamentalFact
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


def _facts(cik, rev_prior, rev):
    def annual(tag, value, year, unit="USD"):
        return FundamentalFact(
            cik=cik,
            tag=tag,
            unit=unit,
            value=value,
            period_start=date(year, 1, 1),
            period_end=date(year, 12, 31),
            fy=year,
            fp="FY",
            form="10-K",
            filed_at=date(year + 1, 2, 1),
        )

    return [
        annual("Revenues", rev_prior, 2024),
        annual("Revenues", rev, 2025),
        annual("EarningsPerShareDiluted", 5.0, 2025, unit="USD/shares"),
        annual("GrossProfit", rev * 0.5, 2025),
        annual("OperatingIncomeLoss", rev * 0.25, 2025),
        annual("NetIncomeLoss", rev * 0.15, 2025),
        FundamentalFact(
            cik=cik,
            tag="StockholdersEquity",
            unit="USD",
            value=1000.0,
            period_end=date(2025, 12, 31),
            fy=2025,
            fp="FY",
            form="10-K",
            filed_at=date(2026, 2, 1),
        ),
    ]


def _payload(result):
    assert not result.is_error
    return json.loads(result.content[0].text)


async def test_research_tools_over_postgres():
    settings = Settings(postgres_dsn=PG_DSN, redis_url=REDIS_URL)
    await apply_migrations(PG_DSN)
    res = MCPResources.build(settings)
    await res.connect()
    try:
        await res.db.pool.execute("TRUNCATE security, market_bar, fundamental_fact, strategy_score")
        await seed_universe(res.db)
        # Two liquid names with fundamentals; GARPY grows fast, SLOW fails the gate.
        for sym in ("NVDA", "AAPL"):
            await _insert_bars(
                res.db,
                make_daily_bars(sym, [80.0 + i * 0.15 for i in range(130)], [2_000_000.0] * 130),
            )
        fund_repo = res.research.fundamentals
        await fund_repo.set_cik("NVDA", "C1")
        await fund_repo.set_cik("AAPL", "C2")
        await fund_repo.save_facts(_facts("C1", 1000.0, 1300.0))  # +30%
        await fund_repo.save_facts(_facts("C2", 1000.0, 1020.0))  # +2% -> gate fail

        server = build_server(settings, resources=res)

        cand = _payload(
            await server.call_tool("find_research_candidates", {"strategy": "GARP", "limit": 10})
        )
        assert cand["provenance"]["model_version"] == "research-v0"
        ranked = [r["symbol"] for r in cand["data"]["results"]]
        assert "NVDA" in ranked
        fails = {e["symbol"]: e["hard_gate_failures"] for e in cand["data"]["ineligible"]}
        assert "GATE_GROWTH_BELOW_MIN" in fails.get("AAPL", [])

        cmp = _payload(
            await server.call_tool(
                "compare_stocks", {"symbols": ["nvda", "aapl"], "strategy": "GARP"}
            )
        )
        assert {r["symbol"] for r in cmp["data"]["results"]} == {"NVDA"}  # AAPL still gated out
    finally:
        await res.close()
