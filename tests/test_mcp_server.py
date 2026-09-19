"""MCP tools return provenance envelopes and map to the trend service."""

from __future__ import annotations

import json

from conftest import make_daily_bars

from sentinel_vantage.apps.mcp_server.server import build_server
from sentinel_vantage.core.config import Settings
from sentinel_vantage.core.versioning import TREND_MODEL_VERSION
from sentinel_vantage.domain.trend.service import TrendService
from sentinel_vantage.storage.memory import InMemoryBarRepository, InMemoryScoreRepository


def _seeded_server():
    histories = {
        "SPY": make_daily_bars("SPY", [100.0] * 70, [50_000_000.0] * 70),
        "HOT": make_daily_bars("HOT", [100.0] * 69 + [118.0], [1_000_000.0] * 69 + [5_000_000.0]),
        "MID": make_daily_bars("MID", [100.0] * 69 + [101.0], [1_000_000.0] * 70),
        "PENNY": make_daily_bars("PENNY", [1.2] * 70, [30_000_000.0] * 70),
    }
    svc = TrendService(InMemoryBarRepository(histories), scores=InMemoryScoreRepository())
    return build_server(Settings(), trend=svc)


def _payload(result):
    assert not result.is_error
    return json.loads(result.content[0].text)


async def test_tools_are_registered():
    server = _seeded_server()
    names = {t.name for t in await server.list_tools()}
    assert {"get_status", "scan_trending_stocks", "analyze_stock", "get_score_history"} <= names


async def test_status_tool_returns_envelope_shape():
    settings = Settings(
        postgres_dsn="postgresql://nope:nope@127.0.0.1:1/none",
        redis_url="redis://127.0.0.1:1/0",
    )
    server = build_server(settings)
    payload = _payload(await server.call_tool("get_status", {}))
    assert payload["provenance"]["feed"] == settings.feed_label
    assert payload["provenance"]["confidence"] is None
    assert payload["provenance"]["model_version"] == "n/a"
    assert "health" in payload["data"]


async def test_scan_tool_ranks_and_reports_ineligible():
    server = _seeded_server()
    payload = _payload(await server.call_tool("scan_trending_stocks", {"limit": 10}))
    assert payload["provenance"]["model_version"] == TREND_MODEL_VERSION
    data = payload["data"]
    symbols = [r["symbol"] for r in data["results"]]
    assert symbols and symbols[0] == "HOT"
    assert "PENNY" not in symbols
    assert any(e["symbol"] == "PENNY" for e in data["ineligible"])
    # AT-5: results carry computed metrics; the model never reconstructs ratios.
    assert data["results"][0]["metrics"]


async def test_analyze_tool_handles_ineligible_symbol():
    server = _seeded_server()
    payload = _payload(await server.call_tool("analyze_stock", {"symbol": "penny"}))
    assert payload["data"]["eligible"] is False
    assert payload["data"]["gate_failures"]


async def test_history_tool_returns_empty_series_by_default():
    server = _seeded_server()
    payload = _payload(await server.call_tool("get_score_history", {"symbol": "HOT"}))
    assert payload["data"]["history"] == []
